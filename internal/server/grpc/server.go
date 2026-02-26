// Package grpc implements the TripWire dashboard gRPC server.
//
// The Server type satisfies the AlertServiceServer interface generated from
// proto/alert.proto and wires together the storage layer (PostgreSQL) and the
// WebSocket broadcaster for real-time alert fan-out to browser clients.
//
// Lifecycle
//
//	srv := grpc.NewServer(store, broadcaster, logger)
//	grpcSrv := grpc.NewGRPCServer()
//	alertpb.RegisterAlertServiceServer(grpcSrv, srv)
//	grpcSrv.Serve(listener)
package grpc

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"time"

	"github.com/google/uuid"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	"github.com/tripwire/agent/internal/server/grpc/alertpb"
	"github.com/tripwire/agent/internal/server/storage"
	ws "github.com/tripwire/agent/internal/server/websocket"
)

// Store is the subset of storage.Store methods used by the gRPC server.
// Defined as an interface so tests can substitute a fake.
type Store interface {
	// UpsertHost persists the host record and returns the stable host_id that
	// is stored in the database.  On a hostname conflict the existing host_id
	// is returned so that alert correlation remains intact across reconnects.
	UpsertHost(ctx context.Context, h storage.Host) (string, error)
	GetHost(ctx context.Context, hostID string) (*storage.Host, error)
	BatchInsertAlerts(ctx context.Context, alert storage.Alert) error
}

// Server implements alertpb.AlertServiceServer.
type Server struct {
	alertpb.UnimplementedAlertServiceServer

	store       Store
	broadcaster *ws.Broadcaster
	logger      *slog.Logger
}

// NewServer creates a Server wired to store and broadcaster.
func NewServer(store Store, broadcaster *ws.Broadcaster, logger *slog.Logger) *Server {
	return &Server{
		store:       store,
		broadcaster: broadcaster,
		logger:      logger,
	}
}

// RegisterAgent handles the RegisterAgent RPC.
//
// It upserts the host record in PostgreSQL and returns the stable host_id
// UUID that the agent must embed in every subsequent AgentEvent.  When an
// agent reconnects under the same hostname, the existing host_id is returned
// so that alert correlation with historical records is preserved.
func (s *Server) RegisterAgent(ctx context.Context, req *alertpb.RegisterRequest) (*alertpb.RegisterResponse, error) {
	if req.Hostname == "" {
		return nil, status.Error(codes.InvalidArgument, "hostname is required")
	}

	// Generate a candidate UUID.  UpsertHost will return the existing host_id
	// if the hostname already exists, discarding this candidate.
	candidateID := uuid.NewString()
	now := time.Now().UTC()

	h := storage.Host{
		HostID:       candidateID,
		Hostname:     req.Hostname,
		Platform:     req.Platform,
		AgentVersion: req.AgentVersion,
		LastSeen:     &now,
		Status:       storage.HostStatusOnline,
	}

	// effectiveHostID is the UUID that is actually stored in the database.
	// On the first registration it equals candidateID; on reconnects it is
	// the original UUID that was assigned when the host first registered.
	effectiveHostID, err := s.store.UpsertHost(ctx, h)
	if err != nil {
		s.logger.Error("grpc: UpsertHost failed",
			slog.String("hostname", req.Hostname),
			slog.Any("error", err),
		)
		return nil, status.Errorf(codes.Internal, "register agent: %v", err)
	}

	s.logger.Info("agent registered",
		slog.String("hostname", req.Hostname),
		slog.String("host_id", effectiveHostID),
		slog.String("platform", req.Platform),
		slog.String("agent_version", req.AgentVersion),
	)

	return &alertpb.RegisterResponse{
		HostId:       effectiveHostID,
		ServerTimeUs: time.Now().UnixMicro(),
	}, nil
}

// StreamAlerts handles the bidirectional StreamAlerts RPC.
//
// For each incoming AgentEvent the handler:
//  1. Validates the required fields.
//  2. Persists the alert to PostgreSQL via BatchInsertAlerts.
//  3. Publishes an AlertMessage to the WebSocket Broadcaster for real-time
//     fan-out to connected browser clients.
//
// The response stream is used only for server-initiated ServerCommand
// messages (currently only a PING keepalive to detect stale streams).
func (s *Server) StreamAlerts(stream alertpb.AlertService_StreamAlertsServer) error {
	ctx := stream.Context()

	for {
		evt, err := stream.Recv()
		if err != nil {
			// io.EOF is the canonical end-of-stream signal from the gRPC
			// runtime.  Context cancellation and deadline exceeded are also
			// considered normal closure (e.g. agent restart, client timeout).
			// All other errors are genuine transport failures and are returned
			// so that the caller can observe and log them appropriately.
			if err == io.EOF ||
				err == context.Canceled ||
				err == context.DeadlineExceeded ||
				status.Code(err) == codes.Canceled ||
				status.Code(err) == codes.DeadlineExceeded {
				s.logger.Debug("grpc: StreamAlerts stream closed", slog.Any("reason", err))
				return nil
			}
			s.logger.Error("grpc: StreamAlerts transport error", slog.Any("error", err))
			return err
		}

		if err := s.handleEvent(ctx, stream, evt); err != nil {
			return err
		}
	}
}

// handleEvent processes a single AgentEvent received from the stream.
func (s *Server) handleEvent(ctx context.Context, stream alertpb.AlertService_StreamAlertsServer, evt *alertpb.AgentEvent) error {
	// --- Validation ---
	if evt.AlertId == "" {
		return status.Error(codes.InvalidArgument, "alert_id is required")
	}
	if evt.HostId == "" {
		return status.Error(codes.InvalidArgument, "host_id is required")
	}
	if !isValidTripwireType(evt.TripwireType) {
		return status.Errorf(codes.InvalidArgument, "invalid tripwire_type %q", evt.TripwireType)
	}
	if !isValidSeverity(evt.Severity) {
		return status.Errorf(codes.InvalidArgument, "invalid severity %q", evt.Severity)
	}

	// --- Resolve hostname for WebSocket fan-out (best-effort) ---
	hostname := evt.HostId // fallback when DB lookup fails
	if host, err := s.store.GetHost(ctx, evt.HostId); err == nil {
		hostname = host.Hostname
	}

	// --- Convert timestamp ---
	var ts time.Time
	if evt.TimestampUs > 0 {
		ts = time.UnixMicro(evt.TimestampUs).UTC()
	} else {
		ts = time.Now().UTC()
	}
	receivedAt := time.Now().UTC()

	// --- Normalise event_detail ---
	detail, err := normaliseDetail(evt.EventDetailJson)
	if err != nil {
		s.logger.Warn("grpc: invalid event_detail_json, using null",
			slog.String("alert_id", evt.AlertId),
			slog.Any("error", err),
		)
		detail = json.RawMessage("null")
	}

	// --- Persist to PostgreSQL ---
	alert := storage.Alert{
		AlertID:      evt.AlertId,
		HostID:       evt.HostId,
		Timestamp:    ts,
		TripwireType: storage.TripwireType(evt.TripwireType),
		RuleName:     evt.RuleName,
		EventDetail:  detail,
		Severity:     storage.Severity(evt.Severity),
		ReceivedAt:   receivedAt,
	}

	if err := s.store.BatchInsertAlerts(ctx, alert); err != nil {
		s.logger.Error("grpc: BatchInsertAlerts failed",
			slog.String("alert_id", evt.AlertId),
			slog.Any("error", err),
		)
		return status.Errorf(codes.Internal, "persist alert %s: %v", evt.AlertId, err)
	}

	s.logger.Info("alert ingested",
		slog.String("alert_id", evt.AlertId),
		slog.String("host_id", evt.HostId),
		slog.String("type", evt.TripwireType),
		slog.String("rule", evt.RuleName),
		slog.String("severity", evt.Severity),
	)

	// --- Fan out to WebSocket clients ---
	s.broadcaster.Broadcast(ws.AlertMessage{
		Type: "alert",
		Data: ws.AlertData{
			AlertID:      evt.AlertId,
			HostID:       evt.HostId,
			Hostname:     hostname,
			Timestamp:    ts.Format(time.RFC3339),
			TripwireType: evt.TripwireType,
			RuleName:     evt.RuleName,
			Severity:     evt.Severity,
			EventDetail:  detail,
		},
	})

	return nil
}

// --- Validation helpers -------------------------------------------------------

func isValidTripwireType(t string) bool {
	switch storage.TripwireType(t) {
	case storage.TripwireTypeFile, storage.TripwireTypeNetwork, storage.TripwireTypeProcess:
		return true
	}
	return false
}

func isValidSeverity(s string) bool {
	switch storage.Severity(s) {
	case storage.SeverityInfo, storage.SeverityWarn, storage.SeverityCritical:
		return true
	}
	return false
}

// normaliseDetail ensures that b is valid JSON.  An empty or nil slice is
// treated as SQL NULL (returned as json.RawMessage("null")).  An invalid JSON
// payload returns an error.
func normaliseDetail(b []byte) (json.RawMessage, error) {
	if len(b) == 0 {
		return json.RawMessage("null"), nil
	}
	if !json.Valid(b) {
		return nil, fmt.Errorf("event_detail_json is not valid JSON")
	}
	return json.RawMessage(b), nil
}
