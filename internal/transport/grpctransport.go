// Package transport implements the gRPC transport client for TripWire agents.
//
// # Overview
//
// GRPCTransport connects to the TripWire dashboard server using mutual TLS
// (mTLS): the agent presents a client certificate to prove its identity, and
// it verifies the dashboard's server certificate against a trusted CA.
//
// Once connected, the transport:
//  1. Calls RegisterAgent to exchange identity metadata and receive a
//     server-assigned host_id that is embedded in every subsequent event.
//  2. Opens the StreamAlerts bidirectional stream to push AlertEvents.
//  3. Drains ServerCommand messages (ACKs, errors) from the server side of the
//     stream in a background goroutine.
//
// # Reconnection
//
// If the connection drops for any reason, GRPCTransport reconnects
// automatically using exponential backoff: each successive failure doubles the
// wait interval up to MaxBackoff, after which every retry waits MaxBackoff.
// On a successful reconnection the backoff interval resets to InitialBackoff so
// that a transient fault is not penalised on the next failure.
//
// # Usage
//
//	t := transport.New(transport.Config{
//	    DashboardAddr:  "dashboard.example.com:4443",
//	    CertPath:       "/etc/tripwire/agent.crt",
//	    KeyPath:        "/etc/tripwire/agent.key",
//	    CAPath:         "/etc/tripwire/ca.crt",
//	    AgentVersion:   "v1.0.0",
//	}, logger)
//
//	if err := t.Start(ctx); err != nil {
//	    log.Fatal(err)
//	}
//	defer t.Stop()
//
//	err = t.Send(ctx, alertEvent)
package transport

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"fmt"
	"io"
	"log/slog"
	"net"
	"os"
	"runtime"
	"sync"
	"time"

	"github.com/cenkalti/backoff/v4"
	"github.com/google/uuid"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"

	alertpb "github.com/tripwire/agent/proto/alert"
	"github.com/tripwire/agent/internal/watcher"
)

const (
	defaultInitialBackoff = 1 * time.Second
	defaultMaxBackoff     = 2 * time.Minute
	defaultDialTimeout    = 30 * time.Second
)

// Config holds the configuration for the gRPC transport.
type Config struct {
	// DashboardAddr is the "host:port" of the TripWire dashboard gRPC server.
	// Required.
	DashboardAddr string

	// CertPath is the path to the PEM-encoded agent TLS certificate. Required.
	CertPath string

	// KeyPath is the path to the PEM-encoded agent TLS private key. Required.
	KeyPath string

	// CAPath is the path to the PEM-encoded CA certificate used to verify the
	// dashboard server's TLS certificate. Required.
	CAPath string

	// InitialBackoff is the starting interval for exponential-backoff
	// reconnection. Defaults to 1 second when zero.
	InitialBackoff time.Duration

	// MaxBackoff caps the exponential-backoff interval. Defaults to 2 minutes
	// when zero.
	MaxBackoff time.Duration

	// DialTimeout limits how long the transport waits for the initial TCP dial
	// and RegisterAgent RPC to complete on each connection attempt. Defaults to
	// 30 seconds when zero.
	DialTimeout time.Duration

	// Hostname overrides the OS hostname sent in RegisterAgent. Defaults to the
	// value of os.Hostname() when empty.
	Hostname string

	// Platform overrides the OS/architecture string sent in RegisterAgent.
	// Defaults to "GOOS/GOARCH" (e.g. "linux/amd64") when empty.
	Platform string

	// AgentVersion is the human-readable version string (e.g. "v1.0.0") sent
	// to the dashboard during registration.
	AgentVersion string
}

func (c *Config) applyDefaults() {
	if c.InitialBackoff == 0 {
		c.InitialBackoff = defaultInitialBackoff
	}
	if c.MaxBackoff == 0 {
		c.MaxBackoff = defaultMaxBackoff
	}
	if c.DialTimeout == 0 {
		c.DialTimeout = defaultDialTimeout
	}
}

// GRPCTransport implements the agent.Transport interface. It streams
// AlertEvents to the TripWire dashboard via a mTLS-protected gRPC
// bidirectional stream (StreamAlerts), maintaining the connection with
// exponential-backoff reconnection.
type GRPCTransport struct {
	cfg    Config
	logger *slog.Logger

	// creds is loaded once in Start and reused on every reconnect.
	creds credentials.TransportCredentials

	// mu guards stream and hostID which are updated on every (re)connect.
	mu     sync.RWMutex
	stream alertpb.AlertService_StreamAlertsClient
	hostID string

	// sendMu serialises calls to stream.Send. gRPC client streams are not safe
	// for concurrent sends; the agent may call Send from multiple goroutines
	// (one per watcher), so we must serialise them here.
	sendMu sync.Mutex

	// cancel terminates the connection loop; set by Start.
	cancel context.CancelFunc

	// wg tracks the connectLoop goroutine so Stop can wait for it.
	wg sync.WaitGroup
}

// New creates a new GRPCTransport with the given configuration and logger.
// Call [GRPCTransport.Start] to begin connecting.
func New(cfg Config, logger *slog.Logger) *GRPCTransport {
	cfg.applyDefaults()
	return &GRPCTransport{
		cfg:    cfg,
		logger: logger,
	}
}

// Start validates the mTLS credentials from disk, then launches a background
// goroutine that connects to the dashboard and keeps the connection alive.
//
// Start returns an error only if the TLS certificate files cannot be loaded.
// All connectivity failures (server unreachable, registration errors) are
// handled internally with exponential-backoff retries.
func (t *GRPCTransport) Start(ctx context.Context) error {
	creds, err := t.loadTLSCredentials()
	if err != nil {
		return fmt.Errorf("transport: %w", err)
	}
	t.creds = creds

	// Resolve hostname default once so all connections report the same value.
	if t.cfg.Hostname == "" {
		h, err := os.Hostname()
		if err != nil {
			h = "unknown"
		}
		t.cfg.Hostname = h
	}

	// Resolve platform default once.
	if t.cfg.Platform == "" {
		t.cfg.Platform = runtime.GOOS + "/" + runtime.GOARCH
	}

	connectCtx, cancel := context.WithCancel(ctx)
	t.cancel = cancel

	t.wg.Add(1)
	go t.connectLoop(connectCtx)

	return nil
}

// Send converts evt to a protobuf AgentEvent and writes it to the active
// StreamAlerts stream. It returns an error if the transport is currently
// reconnecting (i.e., there is no active stream). The caller should treat
// such errors as transient; the agent's local queue provides durability.
func (t *GRPCTransport) Send(_ context.Context, evt watcher.AlertEvent) error {
	t.mu.RLock()
	stream := t.stream
	hostID := t.hostID
	t.mu.RUnlock()

	if stream == nil {
		return fmt.Errorf("transport: not connected to dashboard")
	}

	detailJSON, err := json.Marshal(evt.Detail)
	if err != nil {
		return fmt.Errorf("transport: marshal event detail: %w", err)
	}

	pbEvt := &alertpb.AgentEvent{
		AlertId:         uuid.New().String(),
		HostId:          hostID,
		TimestampUs:     evt.Timestamp.UnixMicro(),
		TripwireType:    evt.TripwireType,
		RuleName:        evt.RuleName,
		Severity:        evt.Severity,
		EventDetailJson: detailJSON,
	}

	t.sendMu.Lock()
	defer t.sendMu.Unlock()

	// Re-check the stream under the send mutex; it may have been cleared by
	// a concurrent reconnect between the RLock above and now.
	t.mu.RLock()
	stream = t.stream
	t.mu.RUnlock()
	if stream == nil {
		return fmt.Errorf("transport: not connected to dashboard")
	}

	if err := stream.Send(pbEvt); err != nil {
		return fmt.Errorf("transport: send event: %w", err)
	}
	return nil
}

// Stop cancels the connection loop and waits for all background goroutines to
// exit. It is safe to call Stop multiple times.
func (t *GRPCTransport) Stop() {
	if t.cancel != nil {
		t.cancel()
	}
	t.wg.Wait()
}

// ─── Connection loop ──────────────────────────────────────────────────────────

// connectLoop runs until ctx is cancelled. On each iteration it calls connect
// which blocks for the lifetime of one gRPC connection. Between failed
// attempts (or after a connection is lost) it applies exponential backoff.
func (t *GRPCTransport) connectLoop(ctx context.Context) {
	defer t.wg.Done()

	b := backoff.NewExponentialBackOff()
	b.InitialInterval = t.cfg.InitialBackoff
	b.MaxInterval = t.cfg.MaxBackoff
	b.MaxElapsedTime = 0 // retry indefinitely
	b.Reset()

	for {
		// Exit immediately if the context has already been cancelled.
		if ctx.Err() != nil {
			return
		}

		t.logger.Info("transport: connecting to dashboard",
			slog.String("addr", t.cfg.DashboardAddr))

		wasConnected, err := t.connect(ctx)

		// If the context was cancelled while connecting, exit cleanly.
		if ctx.Err() != nil {
			return
		}

		if wasConnected {
			// Successful connection followed by a disconnection: reset the
			// backoff so the next reconnect starts from InitialBackoff again.
			b.Reset()
		}

		if err != nil {
			t.logger.Warn("transport: connection ended",
				slog.Any("error", err),
				slog.String("addr", t.cfg.DashboardAddr))
		}

		wait := b.NextBackOff()
		if wait == backoff.Stop {
			// Should not happen when MaxElapsedTime == 0, but guard anyway.
			t.logger.Error("transport: backoff exhausted; giving up")
			return
		}

		t.logger.Info("transport: will reconnect",
			slog.String("addr", t.cfg.DashboardAddr),
			slog.Duration("after", wait))

		select {
		case <-ctx.Done():
			return
		case <-time.After(wait):
		}
	}
}

// connect performs one full connection lifecycle:
//  1. Dials the dashboard with mTLS.
//  2. Calls RegisterAgent to obtain a host_id.
//  3. Opens the StreamAlerts bidirectional stream.
//  4. Blocks in drainStream until the stream closes or ctx is cancelled.
//
// It returns (true, err) when the stream was successfully established before
// failing, or (false, err) when the dial or registration itself failed.
func (t *GRPCTransport) connect(ctx context.Context) (wasConnected bool, err error) {
	conn, err := grpc.NewClient(
		t.cfg.DashboardAddr,
		grpc.WithTransportCredentials(t.creds),
	)
	if err != nil {
		return false, fmt.Errorf("dial %s: %w", t.cfg.DashboardAddr, err)
	}
	defer conn.Close()

	client := alertpb.NewAlertServiceClient(conn)

	// RegisterAgent enforces the per-attempt dial timeout.
	regCtx, regCancel := context.WithTimeout(ctx, t.cfg.DialTimeout)
	resp, err := client.RegisterAgent(regCtx, &alertpb.RegisterRequest{
		Hostname:     t.cfg.Hostname,
		Platform:     t.cfg.Platform,
		AgentVersion: t.cfg.AgentVersion,
	})
	regCancel()
	if err != nil {
		return false, fmt.Errorf("RegisterAgent: %w", err)
	}

	hostID := resp.GetHostId()
	t.logger.Info("transport: agent registered with dashboard",
		slog.String("host_id", hostID),
		slog.String("addr", t.cfg.DashboardAddr))

	// Open the bidirectional event stream.
	stream, err := client.StreamAlerts(ctx)
	if err != nil {
		return false, fmt.Errorf("StreamAlerts: %w", err)
	}

	// Publish the stream so concurrent Send() calls can use it.
	t.mu.Lock()
	t.stream = stream
	t.hostID = hostID
	t.mu.Unlock()

	t.logger.Info("transport: stream established",
		slog.String("addr", t.cfg.DashboardAddr),
		slog.String("host_id", hostID))

	// Block until the stream closes or ctx is cancelled.
	streamErr := t.drainStream(stream)

	// Retract the stream so Send() returns an error while disconnected.
	t.mu.Lock()
	t.stream = nil
	t.mu.Unlock()

	if streamErr == io.EOF {
		// Server closed the stream gracefully.
		return true, nil
	}
	return true, streamErr
}

// drainStream reads ServerCommand messages from stream until the stream is
// closed by the server (io.EOF) or an error occurs. ACKs and errors from the
// server are logged at debug level.
func (t *GRPCTransport) drainStream(stream alertpb.AlertService_StreamAlertsClient) error {
	for {
		cmd, err := stream.Recv()
		if err != nil {
			return err
		}
		t.logger.Debug("transport: received server command",
			slog.String("type", cmd.GetType()),
			slog.String("payload", string(cmd.GetPayload())))
	}
}

// ─── TLS helpers ─────────────────────────────────────────────────────────────

// loadTLSCredentials reads the agent certificate+key and the CA certificate
// from the configured paths, then constructs gRPC transport credentials for
// mTLS. The ServerName is derived from the host component of DashboardAddr so
// that the TLS handshake verifies the dashboard's certificate CN/SAN.
func (t *GRPCTransport) loadTLSCredentials() (credentials.TransportCredentials, error) {
	// Load the agent's client certificate and private key.
	agentCert, err := tls.LoadX509KeyPair(t.cfg.CertPath, t.cfg.KeyPath)
	if err != nil {
		return nil, fmt.Errorf("load agent cert/key (%s, %s): %w",
			t.cfg.CertPath, t.cfg.KeyPath, err)
	}

	// Load the CA certificate used to verify the dashboard server cert.
	caPEM, err := os.ReadFile(t.cfg.CAPath)
	if err != nil {
		return nil, fmt.Errorf("read CA cert %s: %w", t.cfg.CAPath, err)
	}
	caPool := x509.NewCertPool()
	if !caPool.AppendCertsFromPEM(caPEM) {
		return nil, fmt.Errorf("parse CA cert from %s: no certificates found", t.cfg.CAPath)
	}

	// Extract the hostname from DashboardAddr for ServerName verification.
	serverName, _, splitErr := net.SplitHostPort(t.cfg.DashboardAddr)
	if splitErr != nil {
		// DashboardAddr has no port; use it verbatim as the server name.
		serverName = t.cfg.DashboardAddr
	}

	tlsCfg := &tls.Config{
		// Present the agent's client certificate for mutual authentication.
		Certificates: []tls.Certificate{agentCert},

		// Verify the dashboard's server certificate against our CA pool.
		RootCAs: caPool,

		// ServerName must match the CN or a SAN in the server's certificate.
		ServerName: serverName,

		// Enforce TLS 1.2 minimum to match the server configuration.
		MinVersion: tls.VersionTLS12,
	}

	return credentials.NewTLS(tlsCfg), nil
}
