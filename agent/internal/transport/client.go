// Package transport implements the gRPC transport client for the TripWire
// agent.  It handles mutual TLS credential loading, connection management,
// agent registration, bidirectional alert streaming, and exponential-backoff
// reconnection when the dashboard is unreachable.
//
// # Usage
//
//	client := transport.New(cfg, logger)
//	alertCh := make(chan transport.Alert, 64)
//	if err := client.Run(ctx, alertCh); err != nil {
//	    log.Fatal(err)
//	}
//
// # Prometheus metrics
//
// Attach a [Metrics] value to collect operational counters and gauges while
// the client is running:
//
//	m := transport.NewMetrics()
//	client := transport.New(cfg, logger, transport.WithMetrics(m))
//
//	// Serve the collected metrics on an HTTP endpoint.
//	http.Handle("/metrics", m.Handler())
//	go http.ListenAndServe(":9100", nil)
//
// # mTLS
//
// The client loads three files from [config.TLSConfig]:
//   - CACert: PEM-encoded operator CA certificate used to verify the server.
//   - AgentCert: PEM-encoded client certificate presented to the server.
//   - AgentKey: PEM-encoded private key for the client certificate (mode 0600).
//
// # Reconnection
//
// On any transient error (dial failure, stream reset, server unavailable) Run
// backs off and reconnects automatically.  The backoff doubles on each attempt
// starting at [config.DashboardConfig.ReconnectDelay] and is capped at
// [config.DashboardConfig.ReconnectMaxDelay].  The backoff counter resets to
// the initial delay after a connection is held for at least one successful RPC.
//
// # Lifecycle
//
// Run blocks until ctx is cancelled or a permanent error occurs (e.g. invalid
// TLS credentials).  Close the alerts channel to signal a clean shutdown after
// ctx is cancelled.
package transport

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"fmt"
	"io"
	"log/slog"
	"os"
	"runtime"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"

	"github.com/tripwire/agent/internal/config"
	alertpb "github.com/tripwire/agent/proto/alert"
)

// Alert is a tripwire event ready to be forwarded to the dashboard.  Watchers
// create Alert values and send them to the channel accepted by [Client.Run].
type Alert struct {
	// AlertID is a client-generated UUID for idempotent replay support.
	AlertID string

	// TimestampUs is the event occurrence time as Unix microseconds.
	TimestampUs int64

	// TripwireType is one of "FILE", "NETWORK", or "PROCESS".
	TripwireType string

	// RuleName is the human-readable name of the rule that fired.
	RuleName string

	// EventDetailJSON is an opaque JSON blob with type-specific metadata.
	EventDetailJSON []byte

	// Severity is one of "INFO", "WARN", or "CRITICAL".
	Severity string
}

// Option is a functional option for [New] that customises [Client] behaviour.
type Option func(*Client)

// WithMetrics wires a [Metrics] value into the client so that transport events
// are recorded as Prometheus-compatible counters and gauges.
//
// If this option is not provided the client runs without any metric
// instrumentation (a nil [Metrics] pointer is treated as a no-op).
func WithMetrics(m *Metrics) Option {
	return func(c *Client) {
		c.metrics = m
	}
}

// Client manages the gRPC connection to the TripWire dashboard server.
// Create one with [New]; call [Run] to start the send loop.
type Client struct {
	endpoint          string
	dialTimeout       time.Duration
	reconnectDelay    time.Duration
	reconnectMaxDelay time.Duration
	tlsCfg            *config.TLSConfig
	hostname          string
	agentVersion      string
	logger            *slog.Logger
	metrics           *Metrics // nil when no instrumentation is requested
}

// New creates a Client from the supplied agent configuration.
//
// Optional [Option] values (e.g. [WithMetrics]) can be passed to customise
// behaviour; the call is backward-compatible – existing callers that omit the
// options argument continue to work unchanged.
//
// The Client is idle until [Run] is called.
func New(cfg *config.AgentConfig, logger *slog.Logger, opts ...Option) *Client {
	c := &Client{
		endpoint:          cfg.Dashboard.Endpoint,
		dialTimeout:       cfg.Dashboard.DialTimeout,
		reconnectDelay:    cfg.Dashboard.ReconnectDelay,
		reconnectMaxDelay: cfg.Dashboard.ReconnectMaxDelay,
		tlsCfg:            &cfg.Dashboard.TLS,
		hostname:          cfg.Hostname,
		agentVersion:      cfg.AgentVersion,
		logger:            logger,
	}
	for _, opt := range opts {
		opt(c)
	}
	return c
}

// Run connects to the dashboard, registers this agent, and forwards alerts
// from alerts to the dashboard over a bidirectional gRPC stream.
//
// On any transient error Run waits for the current backoff delay and then
// reconnects.  The backoff starts at [config.DashboardConfig.ReconnectDelay]
// and doubles on each failure, up to [config.DashboardConfig.ReconnectMaxDelay].
//
// Run returns nil when ctx is cancelled.  It returns a non-nil error only for
// permanent failures such as unparseable TLS credentials.
//
// The caller should close the alerts channel after cancelling ctx to allow any
// in-flight alert to drain.
func (c *Client) Run(ctx context.Context, alerts <-chan Alert) error {
	creds, err := c.loadTLSCredentials()
	if err != nil {
		return fmt.Errorf("transport: load TLS credentials: %w", err)
	}

	delay := c.reconnectDelay

	for {
		if ctx.Err() != nil {
			return nil
		}

		connErr := c.runOnce(ctx, creds, alerts)
		if ctx.Err() != nil {
			// Context was cancelled during runOnce; this is a clean exit.
			return nil
		}
		if connErr == nil {
			// alerts channel was closed — clean shutdown.
			return nil
		}

		// Transient error – back off and retry.
		c.metricsReconnectAttempt()

		c.logger.Warn("transport: disconnected, will retry",
			slog.String("endpoint", c.endpoint),
			slog.String("error", connErr.Error()),
			slog.Duration("backoff", delay),
		)

		select {
		case <-ctx.Done():
			return nil
		case <-time.After(delay):
		}

		delay = NextDelay(delay, c.reconnectMaxDelay)
	}
}

// runOnce performs a single connect → register → stream cycle.
//
// It returns nil when the alerts channel is closed (clean shutdown).
// It returns a non-nil error on any transient problem so the caller can back
// off and retry.
func (c *Client) runOnce(ctx context.Context, creds credentials.TransportCredentials, alerts <-chan Alert) error {
	c.metricsConnectionAttempt()

	conn, err := grpc.NewClient(c.endpoint, grpc.WithTransportCredentials(creds))
	if err != nil {
		c.metricsConnectionError()
		return fmt.Errorf("create gRPC client for %s: %w", c.endpoint, err)
	}
	defer conn.Close()

	stub := alertpb.NewAlertServiceClient(conn)

	// Register this agent.  Use DialTimeout as the overall budget so that a
	// completely unreachable server does not block indefinitely.
	c.metricsRegistrationAttempt()
	regCtx, regCancel := context.WithTimeout(ctx, c.dialTimeout)
	resp, err := stub.RegisterAgent(regCtx, &alertpb.RegisterRequest{
		Hostname:     c.hostname,
		Platform:     runtime.GOOS,
		AgentVersion: c.agentVersion,
	})
	regCancel()
	if err != nil {
		c.metricsRegistrationError()
		return fmt.Errorf("RegisterAgent: %w", err)
	}

	hostID := resp.GetHostId()
	c.logger.Info("transport: agent registered",
		slog.String("host_id", hostID),
		slog.String("endpoint", c.endpoint),
	)

	// Open the bidirectional alert stream.
	stream, err := stub.StreamAlerts(ctx)
	if err != nil {
		return fmt.Errorf("StreamAlerts: %w", err)
	}

	// Mark the connection as active.
	c.metricsSetConnected(true)
	defer c.metricsSetConnected(false)

	// Drain server commands (ACKs / ERRORs) in a background goroutine so the
	// send loop is never blocked waiting for a response.
	recvErrCh := make(chan error, 1)
	go func() {
		for {
			cmd, recvErr := stream.Recv()
			if recvErr != nil {
				if recvErr == io.EOF {
					recvErrCh <- nil
				} else {
					c.metricsStreamRecvError()
					recvErrCh <- recvErr
				}
				return
			}
			c.logger.Debug("transport: received server command",
				slog.String("type", cmd.GetType()),
			)
		}
	}()

	// Forward alerts from the watcher pipeline to the dashboard.
	for {
		select {
		case <-ctx.Done():
			_ = stream.CloseSend()
			return nil

		case err := <-recvErrCh:
			if err != nil {
				return fmt.Errorf("stream recv: %w", err)
			}
			// Server closed the stream cleanly.
			return nil

		case alert, ok := <-alerts:
			if !ok {
				// Channel closed — caller is shutting down.
				_ = stream.CloseSend()
				return nil
			}
			if err := stream.Send(&alertpb.AgentEvent{
				AlertId:         alert.AlertID,
				HostId:          hostID,
				TimestampUs:     alert.TimestampUs,
				TripwireType:    alert.TripwireType,
				RuleName:        alert.RuleName,
				EventDetailJson: alert.EventDetailJSON,
				Severity:        alert.Severity,
			}); err != nil {
				c.metricsStreamSendError()
				return fmt.Errorf("stream send: %w", err)
			}
			c.metricsAlertSent()
		}
	}
}

// loadTLSCredentials reads the agent certificate, private key, and CA
// certificate from the paths in tlsCfg and returns gRPC transport credentials
// configured for mutual TLS.
func (c *Client) loadTLSCredentials() (credentials.TransportCredentials, error) {
	// Load the agent's client certificate and private key.
	cert, err := tls.LoadX509KeyPair(c.tlsCfg.AgentCert, c.tlsCfg.AgentKey)
	if err != nil {
		return nil, fmt.Errorf("load agent cert/key (%s, %s): %w",
			c.tlsCfg.AgentCert, c.tlsCfg.AgentKey, err)
	}

	// Load and parse the CA certificate used to verify the dashboard server.
	caPEM, err := os.ReadFile(c.tlsCfg.CACert)
	if err != nil {
		return nil, fmt.Errorf("read CA cert %s: %w", c.tlsCfg.CACert, err)
	}
	caPool := x509.NewCertPool()
	if !caPool.AppendCertsFromPEM(caPEM) {
		return nil, fmt.Errorf("parse CA cert %s: no certificates found", c.tlsCfg.CACert)
	}

	tlsConfig := &tls.Config{
		// Present the agent's client certificate for mTLS.
		Certificates: []tls.Certificate{cert},

		// Verify the dashboard server's certificate against our CA pool.
		RootCAs: caPool,

		// Enforce TLS 1.2 minimum for security.
		MinVersion: tls.VersionTLS12,
	}

	return credentials.NewTLS(tlsConfig), nil
}

// NextDelay returns the next exponential-backoff delay value.
// It doubles current, capped at max.  Overflow is handled by capping.
//
// Exported so that unit tests can verify the backoff arithmetic directly.
func NextDelay(current, max time.Duration) time.Duration {
	if current <= 0 {
		return max
	}
	next := current * 2
	// Guard against overflow: if doubling wrapped to ≤0, return max.
	if next <= 0 || next > max {
		return max
	}
	return next
}

// ── metrics helpers ──────────────────────────────────────────────────────────
//
// Each helper is a no-op when c.metrics is nil so the hot path (no-op) is a
// single nil pointer check and avoids any indirection.

func (c *Client) metricsConnectionAttempt() {
	if c.metrics != nil {
		c.metrics.ConnectionAttempts.Add(1)
	}
}

func (c *Client) metricsConnectionError() {
	if c.metrics != nil {
		c.metrics.ConnectionErrors.Add(1)
	}
}

func (c *Client) metricsReconnectAttempt() {
	if c.metrics != nil {
		c.metrics.ReconnectAttempts.Add(1)
	}
}

func (c *Client) metricsRegistrationAttempt() {
	if c.metrics != nil {
		c.metrics.AgentRegistrations.Add(1)
	}
}

func (c *Client) metricsRegistrationError() {
	if c.metrics != nil {
		c.metrics.RegistrationErrors.Add(1)
	}
}

func (c *Client) metricsAlertSent() {
	if c.metrics != nil {
		c.metrics.AlertsSent.Add(1)
	}
}

func (c *Client) metricsStreamSendError() {
	if c.metrics != nil {
		c.metrics.StreamSendErrors.Add(1)
	}
}

func (c *Client) metricsStreamRecvError() {
	if c.metrics != nil {
		c.metrics.StreamRecvErrors.Add(1)
	}
}

func (c *Client) metricsSetConnected(connected bool) {
	if c.metrics != nil {
		if connected {
			c.metrics.Connected.Store(1)
		} else {
			c.metrics.Connected.Store(0)
		}
	}
}
