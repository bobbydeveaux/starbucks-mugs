// Package agent contains the TripWire agent orchestrator. It wires together
// the file, network, and process watchers, the local alert queue, and the
// gRPC transport client, managing their lifecycle through a shared context.
package agent

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"sync"
	"time"

	"github.com/tripwire/agent/internal/config"
)

// AlertEvent is a generic event emitted by a watcher component.
type AlertEvent struct {
	// TripwireType is one of "FILE", "NETWORK", or "PROCESS".
	TripwireType string
	// RuleName is the name of the rule that triggered this event.
	RuleName string
	// Severity is one of "INFO", "WARN", or "CRITICAL".
	Severity string
	// Timestamp is when the event occurred on the agent host.
	Timestamp time.Time
	// Detail holds type-specific metadata (file path, port, pid, etc.).
	Detail map[string]any
}

// Watcher is the common interface implemented by file, network, and process
// watcher components. Implementations must be safe for concurrent use.
type Watcher interface {
	// Start begins monitoring and sends events to the channel returned by
	// Events. It returns an error if initialisation fails.
	Start(ctx context.Context) error
	// Stop signals the watcher to cease monitoring and release resources.
	// It blocks until all internal goroutines have exited.
	Stop()
	// Events returns a read-only channel from which callers receive alert
	// events. The channel is closed when the watcher stops.
	Events() <-chan AlertEvent
}

// Queue is the interface for the local SQLite-backed alert queue.
type Queue interface {
	// Enqueue persists an alert event for at-least-once delivery.
	Enqueue(ctx context.Context, evt AlertEvent) error
	// Depth returns the number of pending (unacknowledged) events.
	Depth() int
	// Close releases resources held by the queue.
	Close() error
}

// Transport is the interface for the gRPC transport client that streams
// events to the dashboard server.
type Transport interface {
	// Start dials the dashboard and begins the bidirectional stream.
	Start(ctx context.Context) error
	// Send forwards an event to the dashboard. It may block if the stream
	// is congested or reconnecting.
	Send(ctx context.Context, evt AlertEvent) error
	// Stop gracefully closes the stream and underlying connection.
	Stop()
}

// Agent is the central orchestrator of the TripWire agent. It starts and
// supervises all watcher, queue, and transport components.
type Agent struct {
	cfg       *config.Config
	logger    *slog.Logger
	watchers  []Watcher
	queue     Queue
	transport Transport

	startTime time.Time
	cancel    context.CancelFunc

	mu          sync.RWMutex
	lastAlertAt time.Time
	running     bool
	wg          sync.WaitGroup
}

// New creates a new Agent from the provided configuration and logger.
// Provide watchers, queue, and transport via the functional options returned by
// WithWatchers, WithQueue, and WithTransport. These components are optional —
// the agent starts with zero watchers and no-op stubs for any component that
// is not provided, which is useful in tests.
func New(cfg *config.Config, logger *slog.Logger, opts ...Option) *Agent {
	a := &Agent{
		cfg:    cfg,
		logger: logger,
	}
	for _, opt := range opts {
		opt(a)
	}
	return a
}

// Option is a functional option for Agent construction.
type Option func(*Agent)

// WithWatchers registers one or more watcher components with the agent.
func WithWatchers(ws ...Watcher) Option {
	return func(a *Agent) {
		a.watchers = append(a.watchers, ws...)
	}
}

// WithQueue registers the local alert queue.
func WithQueue(q Queue) Option {
	return func(a *Agent) { a.queue = q }
}

// WithTransport registers the gRPC transport client.
func WithTransport(t Transport) Option {
	return func(a *Agent) { a.transport = t }
}

// Start initialises and starts all registered components using the provided
// context. It returns a non-nil error if any component fails to initialise.
// On success, internal goroutines handle ongoing event processing until Stop
// is called or ctx is cancelled.
func (a *Agent) Start(ctx context.Context) error {
	a.mu.Lock()
	if a.running {
		a.mu.Unlock()
		return fmt.Errorf("agent: already running")
	}
	a.running = true
	a.startTime = time.Now()
	a.mu.Unlock()

	ctx, cancel := context.WithCancel(ctx)
	a.cancel = cancel

	a.logger.Info("starting tripwire agent",
		slog.String("dashboard_addr", a.cfg.DashboardAddr),
		slog.String("log_level", a.cfg.LogLevel),
		slog.String("health_addr", a.cfg.HealthAddr),
		slog.Int("num_rules", len(a.cfg.Rules)),
	)

	// Start transport first so watchers can deliver events immediately.
	if a.transport != nil {
		if err := a.transport.Start(ctx); err != nil {
			cancel()
			a.mu.Lock()
			a.running = false
			a.mu.Unlock()
			return fmt.Errorf("agent: transport failed to start: %w", err)
		}
	}

	// Start all registered watchers.
	for i, w := range a.watchers {
		if err := w.Start(ctx); err != nil {
			cancel()
			a.mu.Lock()
			a.running = false
			a.mu.Unlock()
			return fmt.Errorf("agent: watcher[%d] failed to start: %w", i, err)
		}
		// Fan-in: read events from each watcher.
		a.wg.Add(1)
		go a.processEvents(ctx, w)
	}

	a.logger.Info("tripwire agent started")
	return nil
}

// Stop signals all components to shut down and waits for internal goroutines
// to exit. It is safe to call Stop multiple times.
func (a *Agent) Stop() {
	a.mu.Lock()
	if !a.running {
		a.mu.Unlock()
		return
	}
	a.running = false
	a.mu.Unlock()

	if a.cancel != nil {
		a.cancel()
	}

	// Stop all watchers.
	for _, w := range a.watchers {
		w.Stop()
	}

	// Wait for event-processing goroutines.
	a.wg.Wait()

	if a.transport != nil {
		a.transport.Stop()
	}

	if a.queue != nil {
		if err := a.queue.Close(); err != nil {
			a.logger.Warn("error closing alert queue", slog.Any("error", err))
		}
	}

	a.logger.Info("tripwire agent stopped")
}

// processEvents reads AlertEvents from watcher w, enqueues them for durable
// storage, and forwards them to the transport. It exits when the watcher's
// event channel is closed or ctx is cancelled.
func (a *Agent) processEvents(ctx context.Context, w Watcher) {
	defer a.wg.Done()

	for {
		select {
		case <-ctx.Done():
			return
		case evt, ok := <-w.Events():
			if !ok {
				return
			}
			a.handleEvent(ctx, evt)
		}
	}
}

// handleEvent records the event in the local queue and forwards it to the
// transport. Errors are logged but do not stop the agent.
func (a *Agent) handleEvent(ctx context.Context, evt AlertEvent) {
	a.mu.Lock()
	a.lastAlertAt = evt.Timestamp
	a.mu.Unlock()

	a.logger.Info("alert event received",
		slog.String("type", evt.TripwireType),
		slog.String("rule", evt.RuleName),
		slog.String("severity", evt.Severity),
	)

	if a.queue != nil {
		if err := a.queue.Enqueue(ctx, evt); err != nil {
			a.logger.Warn("failed to enqueue alert event", slog.Any("error", err))
		}
	}

	if a.transport != nil {
		if err := a.transport.Send(ctx, evt); err != nil {
			a.logger.Warn("failed to send alert event via transport", slog.Any("error", err))
		}
	}
}

// HealthStatus is the payload returned by the /healthz endpoint.
type HealthStatus struct {
	Status      string  `json:"status"`
	UptimeS     float64 `json:"uptime_s"`
	QueueDepth  int     `json:"queue_depth"`
	LastAlertAt string  `json:"last_alert_at,omitempty"`
}

// Health returns a snapshot of the current agent health state.
func (a *Agent) Health() HealthStatus {
	a.mu.RLock()
	defer a.mu.RUnlock()

	h := HealthStatus{
		Status:  "ok",
		UptimeS: time.Since(a.startTime).Seconds(),
	}

	if a.queue != nil {
		h.QueueDepth = a.queue.Depth()
	}

	if !a.lastAlertAt.IsZero() {
		h.LastAlertAt = a.lastAlertAt.UTC().Format(time.RFC3339)
	}

	return h
}

// HealthzHandler is an http.HandlerFunc that responds with the agent's health
// status as a JSON object and HTTP 200.
func (a *Agent) HealthzHandler(w http.ResponseWriter, r *http.Request) {
	h := a.Health()
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	if err := json.NewEncoder(w).Encode(h); err != nil {
		a.logger.Warn("healthz: failed to encode response", slog.Any("error", err))
	}
}
