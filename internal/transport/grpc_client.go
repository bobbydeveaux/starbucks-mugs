// Package transport implements the gRPC transport client for the TripWire
// agent. The [GRPCClient] satisfies the [agent.Transport] interface and
// manages a persistent bidirectional StreamAlerts connection to the dashboard
// server with the following key properties:
//
//   - mTLS: the client presents a certificate signed by the shared CA; the
//     server certificate is verified against the same CA.
//   - RegisterAgent: called once on each successful connection to obtain a
//     stable host_id that is embedded in every AgentEvent.
//   - Exponential backoff: on any connection or stream error the client waits
//     an exponentially increasing interval (with ±25 % jitter) before
//     reconnecting.  The back-off ceiling defaults to 60 s and is configurable
//     via [ClientConfig.MaxBackoff].
//   - Queue drain on reconnect: each time the stream is established the client
//     first drains all pending events from the local SQLite queue (oldest first)
//     before forwarding new live events.  Each event is acked in the queue only
//     after the server sends an ACK ServerCommand.
//   - Metrics: [GRPCClient.AlertsSentTotal] and [GRPCClient.ReconnectTotal]
//     are atomic counters that increment on successful delivery and on each
//     reconnect attempt respectively.  [GRPCClient.QueueDepth] reads directly
//     from the underlying queue so that [agent.HealthStatus.QueueDepth] stays
//     accurate.
package transport

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"encoding/json"
	"fmt"
	"log/slog"
	"math/rand"
	"os"
	"sync"
	"sync/atomic"
	"time"

	"github.com/google/uuid"
	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/credentials/insecure"

	"github.com/tripwire/agent/internal/agent"
	"github.com/tripwire/agent/internal/queue"
	alertpb "github.com/tripwire/agent/proto/alert"
)

const (
	// defaultMaxBackoff is the ceiling for the exponential reconnect back-off.
	defaultMaxBackoff = 60 * time.Second

	// initialBackoff is the wait after the first connection failure.
	initialBackoff = time.Second

	// drainBatchSize is the number of events dequeued per iteration in
	// drainQueue.
	drainBatchSize = 50

	// liveChanCap is the capacity of the buffered channel used to forward live
	// AlertEvents from Send to the stream goroutine.
	liveChanCap = 256
)

// DrainQueue is the subset of [queue.SQLiteQueue] used by GRPCClient.  It is
// satisfied by *queue.SQLiteQueue and can be stubbed in unit tests.
type DrainQueue interface {
	// Dequeue returns up to n unacknowledged events in insertion order.
	Dequeue(ctx context.Context, n int) ([]queue.PendingEvent, error)
	// Ack marks events as delivered.  Idempotent.
	Ack(ctx context.Context, ids []int64) error
	// Depth returns the count of pending (unacknowledged) events.
	Depth() int
}

// ClientConfig holds the parameters for connecting to the TripWire dashboard.
type ClientConfig struct {
	// Addr is the dashboard gRPC address (e.g. "dashboard.example.com:4443").
	// Required.
	Addr string

	// CertPath is the path to the PEM-encoded agent client certificate.
	// Required when Insecure is false.
	CertPath string

	// KeyPath is the path to the PEM-encoded agent private key.
	// Required when Insecure is false.
	KeyPath string

	// CAPath is the path to the PEM-encoded CA certificate used to verify the
	// dashboard server certificate.  Required when Insecure is false.
	CAPath string

	// ServerName overrides the TLS server name for SNI verification.  When
	// empty the hostname portion of Addr is used.  Ignored when Insecure is
	// true.
	ServerName string

	// Hostname is the agent host name sent in RegisterAgent.  When empty
	// os.Hostname() is used.
	Hostname string

	// Platform is the OS label sent in RegisterAgent (e.g. "linux").
	Platform string

	// AgentVersion is the semantic version sent in RegisterAgent.
	AgentVersion string

	// MaxBackoff is the maximum reconnect back-off interval.  Defaults to
	// defaultMaxBackoff when zero or negative.
	MaxBackoff time.Duration

	// Insecure disables TLS entirely.  Use only in tests; never in production.
	Insecure bool
}

// GRPCClient is a bidirectional gRPC transport client that implements
// [agent.Transport].  It is safe for concurrent use: [Send] may be called from
// any goroutine while the internal run loop manages the stream.
//
// Use [New] to construct a GRPCClient.  Call [Start] once to begin the
// connection loop.  Call [Stop] to shut down cleanly.
type GRPCClient struct {
	cfg    ClientConfig
	queue  DrainQueue
	logger *slog.Logger

	// liveCh carries alert events from Send to the run-loop goroutine.
	liveCh chan agent.AlertEvent

	// stopCh is closed by Stop to signal the run loop to exit.
	stopCh chan struct{}
	stopOnce sync.Once

	// done is closed by the run loop when it exits.
	done chan struct{}

	// hostID is set after the first successful RegisterAgent call.  Protected
	// by hostMu so that both the run loop (writer) and Send callers (readers)
	// can access it safely.
	hostMu sync.RWMutex
	hostID string

	// Counters.
	alertsSentTotal atomic.Int64
	reconnectTotal  atomic.Int64
}

// New creates a new GRPCClient but does not start it.  Call [Start] to begin
// the connection loop.
//
//   - cfg must have Addr set; CertPath/KeyPath/CAPath are required unless
//     cfg.Insecure is true (testing only).
//   - q is the local SQLite queue; it is used to drain pending events on each
//     reconnect.  May be nil, in which case draining is skipped.
//   - logger is used for structured logging; pass slog.Default() when no
//     custom logger is required.
func New(cfg ClientConfig, q DrainQueue, logger *slog.Logger) *GRPCClient {
	if cfg.MaxBackoff <= 0 {
		cfg.MaxBackoff = defaultMaxBackoff
	}
	if logger == nil {
		logger = slog.Default()
	}
	return &GRPCClient{
		cfg:    cfg,
		queue:  q,
		logger: logger,
		liveCh: make(chan agent.AlertEvent, liveChanCap),
		stopCh: make(chan struct{}),
		done:   make(chan struct{}),
	}
}

// Start launches the connection loop in a background goroutine and returns
// immediately.  It implements [agent.Transport].
//
// Start returns an error only when the client is already running.  Connection
// failures are retried internally with exponential back-off and are not
// surfaced as errors from Start.
func (c *GRPCClient) Start(ctx context.Context) error {
	go c.run(ctx)
	return nil
}

// Send forwards evt to the live channel consumed by the stream goroutine.  It
// implements [agent.Transport].
//
// Send returns an error if the live channel is full (back-pressure from a slow
// stream) or if the client has been stopped.  The caller should already have
// persisted evt to the local queue before calling Send; a failed Send is not
// fatal because the event will be re-delivered by the queue drain on reconnect.
func (c *GRPCClient) Send(ctx context.Context, evt agent.AlertEvent) error {
	select {
	case c.liveCh <- evt:
		return nil
	case <-ctx.Done():
		return ctx.Err()
	case <-c.stopCh:
		return fmt.Errorf("transport: stopped")
	default:
		return fmt.Errorf("transport: live channel full, event will be delivered via queue")
	}
}

// Stop signals the run loop to exit and blocks until it has.  It implements
// [agent.Transport].  Calling Stop more than once is safe.
func (c *GRPCClient) Stop() {
	c.stopOnce.Do(func() { close(c.stopCh) })
	<-c.done
}

// AlertsSentTotal returns the total number of alerts successfully acknowledged
// by the server (ACK commands received) since the client was created.
func (c *GRPCClient) AlertsSentTotal() int64 { return c.alertsSentTotal.Load() }

// ReconnectTotal returns the total number of reconnect attempts (connection
// losses) since the client was created.
func (c *GRPCClient) ReconnectTotal() int64 { return c.reconnectTotal.Load() }

// QueueDepth delegates to the underlying DrainQueue.Depth.  It returns 0 when
// no queue is configured.
func (c *GRPCClient) QueueDepth() int {
	if c.queue == nil {
		return 0
	}
	return c.queue.Depth()
}

// HostID returns the host_id assigned by the dashboard during the most recent
// successful RegisterAgent call.  It returns an empty string before the first
// successful registration.
func (c *GRPCClient) HostID() string {
	c.hostMu.RLock()
	defer c.hostMu.RUnlock()
	return c.hostID
}

// --- internal ---

// run is the main connection loop.  It runs in a background goroutine started
// by Start and exits when stopCh is closed or ctx is cancelled.  On each
// connection failure it increments reconnectTotal and sleeps for an
// exponentially increasing interval with ±25 % jitter before retrying.
func (c *GRPCClient) run(ctx context.Context) {
	defer close(c.done)

	backoff := initialBackoff
	first := true

	for {
		// Check termination before each attempt.
		select {
		case <-ctx.Done():
			return
		case <-c.stopCh:
			return
		default:
		}

		if !first {
			// Wait for back-off period, but exit early on termination signals.
			select {
			case <-time.After(backoff):
			case <-ctx.Done():
				return
			case <-c.stopCh:
				return
			}
		}
		first = false

		err := c.runOnce(ctx)
		if err == nil {
			// Clean exit (ctx cancelled or stopCh closed inside runOnce).
			return
		}

		c.reconnectTotal.Add(1)
		c.logger.Warn("transport: connection lost, reconnecting",
			slog.Any("error", err),
			slog.Duration("backoff", backoff),
		)

		// Compute next back-off: double with ±25 % jitter, capped at MaxBackoff.
		backoff = nextBackoff(backoff, c.cfg.MaxBackoff)
	}
}

// runOnce performs a single connect → register → stream cycle.  It returns nil
// only when the exit is clean (stop/context cancellation).  Any other return
// value means the connection was lost and the caller should retry.
func (c *GRPCClient) runOnce(ctx context.Context) error {
	// --- 1. Dial ---
	creds, err := c.buildCredentials()
	if err != nil {
		return fmt.Errorf("build TLS credentials: %w", err)
	}

	conn, err := grpc.NewClient(c.cfg.Addr, grpc.WithTransportCredentials(creds))
	if err != nil {
		return fmt.Errorf("dial %s: %w", c.cfg.Addr, err)
	}
	defer conn.Close()

	// --- 2. RegisterAgent ---
	client := alertpb.NewAlertServiceClient(conn)

	hostname := c.cfg.Hostname
	if hostname == "" {
		if h, err := os.Hostname(); err == nil {
			hostname = h
		}
	}

	regCtx, regCancel := context.WithTimeout(ctx, 10*time.Second)
	resp, err := client.RegisterAgent(regCtx, &alertpb.RegisterRequest{
		Hostname:     hostname,
		Platform:     c.cfg.Platform,
		AgentVersion: c.cfg.AgentVersion,
	})
	regCancel()

	if err != nil {
		return fmt.Errorf("RegisterAgent: %w", err)
	}

	c.hostMu.Lock()
	c.hostID = resp.HostId
	c.hostMu.Unlock()

	c.logger.Info("transport: registered with dashboard",
		slog.String("host_id", resp.HostId),
		slog.String("dashboard_addr", c.cfg.Addr),
	)

	// --- 3. Open StreamAlerts ---
	stream, err := client.StreamAlerts(ctx)
	if err != nil {
		return fmt.Errorf("StreamAlerts: %w", err)
	}

	// --- 4. Drain SQLite queue ---
	if c.queue != nil && c.queue.Depth() > 0 {
		c.logger.Info("transport: draining queue before live events",
			slog.Int("depth", c.queue.Depth()),
		)
		if err := c.drainQueue(ctx, stream); err != nil {
			// Check whether the exit was caused by a stop signal.
			select {
			case <-c.stopCh:
				return nil
			case <-ctx.Done():
				return nil
			default:
				return fmt.Errorf("queue drain: %w", err)
			}
		}
		c.logger.Info("transport: queue drain complete")
	}

	// --- 5. Process live events ---
	if err := c.processLive(ctx, stream); err != nil {
		// Clean stop — not a transport error.
		select {
		case <-c.stopCh:
			return nil
		case <-ctx.Done():
			return nil
		default:
			return err
		}
	}
	return nil
}

// drainQueue sends all pending events from the queue to the server in FIFO
// order.  For each event it:
//  1. Generates a new alert_id UUID.
//  2. Sends the AgentEvent on the stream.
//  3. Receives the ServerCommand response.
//  4. If the command is ACK, calls Ack on the queue and increments
//     alertsSentTotal.
//
// Events whose server response is ERROR are left in the queue (delivered=0)
// so they are retried on the next reconnect.  Any stream send/recv error
// terminates the drain and is returned to the caller.
func (c *GRPCClient) drainQueue(ctx context.Context, stream alertpb.AlertService_StreamAlertsClient) error {
	hostID := c.HostID()

	for {
		// Check termination signals first.
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-c.stopCh:
			return nil
		default:
		}

		pending, err := c.queue.Dequeue(ctx, drainBatchSize)
		if err != nil {
			return fmt.Errorf("dequeue: %w", err)
		}
		if len(pending) == 0 {
			// Queue is empty; drain complete.
			return nil
		}

		for _, pe := range pending {
			alertID := uuid.NewString()

			if err := stream.Send(&alertpb.AgentEvent{
				AlertId:         alertID,
				HostId:          hostID,
				TimestampUs:     pe.Evt.Timestamp.UnixMicro(),
				TripwireType:    pe.Evt.TripwireType,
				RuleName:        pe.Evt.RuleName,
				Severity:        pe.Evt.Severity,
				EventDetailJson: marshalDetail(pe.Evt.Detail),
			}); err != nil {
				return fmt.Errorf("send (queued): %w", err)
			}

			cmd, err := stream.Recv()
			if err != nil {
				return fmt.Errorf("recv ACK (queued): %w", err)
			}

			switch cmd.Type {
			case "ACK":
				if ackErr := c.queue.Ack(ctx, []int64{pe.ID}); ackErr != nil {
					// Log but do not abort the drain; the event will be
					// re-delivered on the next reconnect.
					c.logger.Warn("transport: queue Ack failed",
						slog.Int64("queue_id", pe.ID),
						slog.Any("error", ackErr),
					)
				} else {
					c.alertsSentTotal.Add(1)
					c.logger.Debug("transport: queued event delivered",
						slog.String("alert_id", alertID),
						slog.String("rule", pe.Evt.RuleName),
					)
				}
			default:
				c.logger.Warn("transport: server rejected queued event",
					slog.String("alert_id", alertID),
					slog.String("server_response", cmd.Type),
					slog.String("rule", pe.Evt.RuleName),
				)
				// Do not ack — retry on next reconnect.
			}
		}
	}
}

// processLive forwards live events received from [Send] onto the gRPC stream.
// It starts a background goroutine that reads ServerCommand ACKs and
// increments alertsSentTotal.  The method returns when:
//   - ctx is cancelled,
//   - stopCh is closed,
//   - the server closes the stream (EOF), or
//   - a send or receive error occurs.
func (c *GRPCClient) processLive(ctx context.Context, stream alertpb.AlertService_StreamAlertsClient) error {
	hostID := c.HostID()

	// Receive ACKs from the server in a separate goroutine so that the send
	// path is not blocked waiting for each individual ACK.  Per the gRPC Go
	// documentation it is safe to call Send and Recv concurrently on the same
	// stream from different goroutines.
	recvErrCh := make(chan error, 1)
	go func() {
		for {
			cmd, err := stream.Recv()
			if err != nil {
				recvErrCh <- err
				return
			}
			if cmd.Type == "ACK" {
				c.alertsSentTotal.Add(1)
			}
		}
	}()

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case <-c.stopCh:
			return nil
		case err := <-recvErrCh:
			return fmt.Errorf("recv: %w", err)
		case evt := <-c.liveCh:
			if err := stream.Send(&alertpb.AgentEvent{
				AlertId:         uuid.NewString(),
				HostId:          hostID,
				TimestampUs:     evt.Timestamp.UnixMicro(),
				TripwireType:    evt.TripwireType,
				RuleName:        evt.RuleName,
				Severity:        evt.Severity,
				EventDetailJson: marshalDetail(evt.Detail),
			}); err != nil {
				return fmt.Errorf("send (live): %w", err)
			}
		}
	}
}

// buildCredentials constructs gRPC transport credentials from the config.
// When cfg.Insecure is true it returns insecure credentials (testing only).
func (c *GRPCClient) buildCredentials() (credentials.TransportCredentials, error) {
	if c.cfg.Insecure {
		return insecure.NewCredentials(), nil
	}

	clientCert, err := tls.LoadX509KeyPair(c.cfg.CertPath, c.cfg.KeyPath)
	if err != nil {
		return nil, fmt.Errorf("load client cert/key (%s, %s): %w", c.cfg.CertPath, c.cfg.KeyPath, err)
	}

	caPEM, err := os.ReadFile(c.cfg.CAPath)
	if err != nil {
		return nil, fmt.Errorf("read CA cert %s: %w", c.cfg.CAPath, err)
	}
	caPool := x509.NewCertPool()
	if !caPool.AppendCertsFromPEM(caPEM) {
		return nil, fmt.Errorf("parse CA cert from %s: no certificates found", c.cfg.CAPath)
	}

	tlsCfg := &tls.Config{
		Certificates: []tls.Certificate{clientCert},
		RootCAs:      caPool,
		MinVersion:   tls.VersionTLS12,
	}
	if c.cfg.ServerName != "" {
		tlsCfg.ServerName = c.cfg.ServerName
	}

	return credentials.NewTLS(tlsCfg), nil
}

// marshalDetail converts the Detail map to JSON bytes.  A nil or empty map
// produces the JSON null byte slice.  Marshalling errors are silently swallowed
// and produce an empty []byte; the server's event_detail_json field is optional.
func marshalDetail(detail map[string]any) []byte {
	if len(detail) == 0 {
		return nil
	}
	b, err := json.Marshal(detail)
	if err != nil {
		return nil
	}
	return b
}

// nextBackoff returns the next back-off duration: double the current value with
// ±25 % jitter, capped at maxBackoff.
func nextBackoff(current, maxBackoff time.Duration) time.Duration {
	// Double the interval.
	next := current * 2
	if next > maxBackoff {
		next = maxBackoff
	}

	// Add ±25 % jitter: multiply by a factor in [0.75, 1.25).
	jitterFactor := 0.75 + rand.Float64()*0.5 // [0.75, 1.25)
	next = time.Duration(float64(next) * jitterFactor)

	// Never drop below initialBackoff or exceed maxBackoff.
	if next < initialBackoff {
		next = initialBackoff
	}
	if next > maxBackoff {
		next = maxBackoff
	}
	return next
}

// Ensure GRPCClient satisfies agent.Transport at compile time.
var _ agent.Transport = (*GRPCClient)(nil)
