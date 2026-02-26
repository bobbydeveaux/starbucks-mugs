// Package grpc implements the TripWire dashboard's gRPC alert ingestion
// service.  The AlertService handles two RPCs:
//
//   - RegisterAgent — records or updates the agent's host identity.
//   - StreamAlerts  — receives a bidirectional stream of AgentEvents, validates
//     each one, persists valid alerts to PostgreSQL, and fans every
//     successfully persisted alert to the WebSocket broadcaster so
//     connected browser clients receive real-time updates.
//
// Broadcaster fan-out is performed with a non-blocking send so that a slow or
// disconnected WebSocket consumer never applies back-pressure to the gRPC
// stream goroutine (acceptance criteria §1 and §2).
package grpc

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"strings"
	"time"

	"github.com/google/uuid"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/peer"
	"google.golang.org/grpc/status"

	alertpb "github.com/tripwire/agent/proto/alert"
	"github.com/tripwire/agent/internal/server/storage"
	"github.com/tripwire/agent/internal/server/websocket"
)

// Store is the subset of the storage layer used by AlertService.
type Store interface {
	// UpsertHost inserts or updates a host record and returns the effective
	// host_id persisted in the database.  On a first insert the supplied
	// h.HostID is stored and returned; on a hostname conflict the pre-existing
	// host_id is returned unchanged, giving callers a stable identifier across
	// agent reconnects.
	UpsertHost(ctx context.Context, h storage.Host) (string, error)
	BatchInsertAlerts(ctx context.Context, a storage.Alert) error
}

// Broadcaster is the subset of the websocket.Broadcaster interface used by
// AlertService.  Declaring a local interface (rather than importing the
// concrete type) makes the service trivially testable with a stub.
type Broadcaster interface {
	Publish(a storage.Alert)
}

// AlertService implements alertpb.AlertServiceServer.  It validates incoming
// agent events, persists them to PostgreSQL, and publishes each persisted alert
// to the WebSocket broadcaster for real-time browser delivery.
type AlertService struct {
	alertpb.UnimplementedAlertServiceServer

	store       Store
	broadcaster Broadcaster
	logger      *slog.Logger

	// maxEventAgeSecs is the maximum age of a reported event relative to the
	// server clock.  Events older than this are rejected as stale.
	maxEventAgeSecs int64
}

// NewAlertService creates an AlertService.
//
//   - store must be an open, ready-to-use storage.Store (or a test stub).
//   - broadcaster must be a running websocket.InProcessBroadcaster (or a test stub).
//   - logger is used for structured per-event logging.
//   - maxEventAgeSecs is the tolerated clock skew window; ≤0 uses the default
//     of 300 seconds (5 minutes).
func NewAlertService(store Store, broadcaster Broadcaster, logger *slog.Logger, maxEventAgeSecs int64) *AlertService {
	if maxEventAgeSecs <= 0 {
		maxEventAgeSecs = 300
	}
	return &AlertService{
		store:           store,
		broadcaster:     broadcaster,
		logger:          logger,
		maxEventAgeSecs: maxEventAgeSecs,
	}
}

// RegisterAgent implements alertpb.AlertServiceServer.RegisterAgent.
//
// It upserts a Host record in the database, deriving the hostname from the
// mTLS client-certificate CN when available, falling back to the hostname
// field in the request.
func (s *AlertService) RegisterAgent(ctx context.Context, req *alertpb.RegisterRequest) (*alertpb.RegisterResponse, error) {
	hostname := req.GetHostname()

	// Prefer the CN embedded in the client certificate over the self-reported
	// hostname so that identity is tied to the PKI, not the agent's claim.
	if cn := certCN(ctx); cn != "" {
		hostname = cn
	}

	if hostname == "" {
		return nil, status.Error(codes.InvalidArgument, "register_agent: hostname must not be empty")
	}

	now := time.Now().UTC()
	// Generate a candidate UUID for new registrations.  UpsertHost uses
	// ON CONFLICT (hostname) DO UPDATE … RETURNING host_id, so if a host
	// with the same hostname already exists the DB returns the pre-existing
	// UUID and candidateID is discarded.  This guarantees that every agent
	// reconnect receives the same stable host_id, preserving alert correlation
	// across disconnects.
	candidateID := uuid.NewString()
	host := storage.Host{
		HostID:       candidateID,
		Hostname:     hostname,
		Platform:     req.GetPlatform(),
		AgentVersion: req.GetAgentVersion(),
		LastSeen:     &now,
		Status:       storage.HostStatusOnline,
	}

	effectiveHostID, err := s.store.UpsertHost(ctx, host)
	if err != nil {
		s.logger.Error("register_agent: upsert host failed",
			slog.String("hostname", hostname),
			slog.Any("error", err),
		)
		return nil, status.Errorf(codes.Internal, "register_agent: store: %v", err)
	}

	s.logger.Info("agent registered",
		slog.String("host_id", effectiveHostID),
		slog.String("hostname", hostname),
		slog.String("platform", req.GetPlatform()),
	)

	return &alertpb.RegisterResponse{
		HostId:       effectiveHostID,
		ServerTimeUs: now.UnixMicro(),
	}, nil
}

// StreamAlerts implements alertpb.AlertServiceServer.StreamAlerts.
//
// The method reads AgentEvent messages from the client stream until EOF or
// context cancellation.  For each valid event it:
//  1. Validates required fields, timestamp bounds, and enum values.
//  2. Persists the alert via store.BatchInsertAlerts (batched, non-blocking).
//  3. Publishes the alert to the WebSocket broadcaster using a non-blocking
//     send so slow or disconnected clients cannot stall this goroutine.
//  4. Sends an ACK ServerCommand back to the agent.
//
// Invalid events receive an error ACK and are not written to the database.
func (s *AlertService) StreamAlerts(stream alertpb.AlertService_StreamAlertsServer) error {
	ctx := stream.Context()

	for {
		evt, err := stream.Recv()
		if err == io.EOF {
			return nil
		}
		if err != nil {
			// Stream closed by the client or network error.
			return err
		}

		alert, validationErr := s.validateAndConvert(evt)
		if validationErr != nil {
			s.logger.Warn("stream_alerts: invalid event rejected",
				slog.String("alert_id", evt.GetAlertId()),
				slog.String("reason", validationErr.Error()),
			)
			if sendErr := stream.Send(errorACK(evt.GetAlertId(), validationErr)); sendErr != nil {
				return sendErr
			}
			continue
		}

		// Persist to PostgreSQL (batched; flushes every 100 ms or at 100 rows).
		if err := s.store.BatchInsertAlerts(ctx, *alert); err != nil {
			s.logger.Error("stream_alerts: persist alert failed",
				slog.String("alert_id", alert.AlertID),
				slog.Any("error", err),
			)
			if sendErr := stream.Send(errorACK(evt.GetAlertId(), err)); sendErr != nil {
				return sendErr
			}
			continue
		}

		// Fan the persisted alert to all connected WebSocket subscribers.
		// This is a non-blocking call: InProcessBroadcaster.Publish uses a
		// select/default so a stalled subscriber never blocks this goroutine.
		s.broadcaster.Publish(*alert)

		s.logger.Info("stream_alerts: alert persisted and broadcast",
			slog.String("alert_id", alert.AlertID),
			slog.String("host_id", alert.HostID),
			slog.String("tripwire_type", string(alert.TripwireType)),
			slog.String("severity", string(alert.Severity)),
		)

		if sendErr := stream.Send(ackCommand(alert.AlertID)); sendErr != nil {
			return sendErr
		}
	}
}

// validateAndConvert checks that evt carries all required fields and converts
// it to a storage.Alert ready for insertion.
//
// Validation rules:
//   - alert_id, host_id, tripwire_type, rule_name, severity must be non-empty.
//   - timestamp_us must be within [now − maxEventAgeSecs, now + 60s].
//   - tripwire_type must be FILE, NETWORK, or PROCESS.
//   - severity must be INFO, WARN, or CRITICAL.
//   - event_detail_json, if non-empty, must be valid JSON.
func (s *AlertService) validateAndConvert(evt *alertpb.AgentEvent) (*storage.Alert, error) {
	if evt.GetAlertId() == "" {
		return nil, fmt.Errorf("alert_id is required")
	}
	if evt.GetHostId() == "" {
		return nil, fmt.Errorf("host_id is required")
	}
	if evt.GetRuleName() == "" {
		return nil, fmt.Errorf("rule_name is required")
	}

	// --- tripwire_type ---
	tt, err := parseTripwireType(evt.GetTripwireType())
	if err != nil {
		return nil, err
	}

	// --- severity ---
	sev, err := parseSeverity(evt.GetSeverity())
	if err != nil {
		return nil, err
	}

	// --- timestamp_us ---
	if evt.GetTimestampUs() == 0 {
		return nil, fmt.Errorf("timestamp_us is required")
	}
	ts := time.UnixMicro(evt.GetTimestampUs()).UTC()
	now := time.Now().UTC()
	if ts.Before(now.Add(-time.Duration(s.maxEventAgeSecs) * time.Second)) {
		return nil, fmt.Errorf("timestamp_us %d is too old (>%ds)", evt.GetTimestampUs(), s.maxEventAgeSecs)
	}
	if ts.After(now.Add(60 * time.Second)) {
		return nil, fmt.Errorf("timestamp_us %d is too far in the future (>60s)", evt.GetTimestampUs())
	}

	// --- event_detail_json ---
	var detail json.RawMessage
	if len(evt.GetEventDetailJson()) > 0 {
		if !json.Valid(evt.GetEventDetailJson()) {
			return nil, fmt.Errorf("event_detail_json is not valid JSON")
		}
		detail = json.RawMessage(evt.GetEventDetailJson())
	}

	return &storage.Alert{
		AlertID:      evt.GetAlertId(),
		HostID:       evt.GetHostId(),
		Timestamp:    ts,
		TripwireType: tt,
		RuleName:     evt.GetRuleName(),
		EventDetail:  detail,
		Severity:     sev,
		ReceivedAt:   time.Now().UTC(),
	}, nil
}

// --- helpers ---

// parseTripwireType validates and converts the string tripwire type.
func parseTripwireType(s string) (storage.TripwireType, error) {
	switch strings.ToUpper(s) {
	case "FILE":
		return storage.TripwireTypeFile, nil
	case "NETWORK":
		return storage.TripwireTypeNetwork, nil
	case "PROCESS":
		return storage.TripwireTypeProcess, nil
	default:
		return "", fmt.Errorf("tripwire_type %q is invalid; must be FILE, NETWORK, or PROCESS", s)
	}
}

// parseSeverity validates and converts the string severity.
func parseSeverity(s string) (storage.Severity, error) {
	switch strings.ToUpper(s) {
	case "INFO":
		return storage.SeverityInfo, nil
	case "WARN":
		return storage.SeverityWarn, nil
	case "CRITICAL":
		return storage.SeverityCritical, nil
	default:
		return "", fmt.Errorf("severity %q is invalid; must be INFO, WARN, or CRITICAL", s)
	}
}

// ackCommand builds a successful ACK response.
func ackCommand(alertID string) *alertpb.ServerCommand {
	payload, _ := json.Marshal(map[string]string{"alert_id": alertID})
	return &alertpb.ServerCommand{
		Type:    "ACK",
		Payload: payload,
	}
}

// errorACK builds an error ACK response containing the rejection reason.
func errorACK(alertID string, err error) *alertpb.ServerCommand {
	payload, _ := json.Marshal(map[string]string{
		"alert_id": alertID,
		"error":    err.Error(),
	})
	return &alertpb.ServerCommand{
		Type:    "ERROR",
		Payload: payload,
	}
}

// certCN extracts the CommonName from the mTLS client certificate attached to
// ctx.  Returns an empty string when no peer info or certificate is available.
func certCN(ctx context.Context) string {
	p, ok := peer.FromContext(ctx)
	if !ok {
		return ""
	}
	tlsInfo, ok := p.AuthInfo.(credentials.TLSInfo)
	if !ok || len(tlsInfo.State.VerifiedChains) == 0 || len(tlsInfo.State.VerifiedChains[0]) == 0 {
		return ""
	}
	return tlsInfo.State.VerifiedChains[0][0].Subject.CommonName
}

// Ensure InProcessBroadcaster satisfies the local Broadcaster interface at
// compile time.
var _ Broadcaster = (*websocket.InProcessBroadcaster)(nil)
