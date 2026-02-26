// Package watcher contains the concrete watcher implementations for the
// TripWire agent: file, network, and process monitors.
package watcher

import (
	"context"
	"fmt"
	"log/slog"
	"net"
	"sync"
	"time"

	"github.com/tripwire/agent/internal/agent"
)

// Protocol specifies which transport protocol(s) the NetworkWatcher monitors.
type Protocol string

const (
	// ProtocolTCP monitors TCP connections only.
	ProtocolTCP Protocol = "tcp"
	// ProtocolUDP monitors UDP datagrams only.
	ProtocolUDP Protocol = "udp"
	// ProtocolBoth monitors both TCP connections and UDP datagrams.
	ProtocolBoth Protocol = "both"
)

// Direction specifies which connection directions trigger an alert.
// Currently only inbound connections are detected by the listener-based
// approach; outbound detection requires eBPF/netlink and is reserved for a
// future implementation.
type Direction string

const (
	// DirectionInbound alerts on connections received by the host.
	DirectionInbound Direction = "inbound"
	// DirectionOutbound alerts on connections initiated by the host (reserved).
	DirectionOutbound Direction = "outbound"
	// DirectionBoth alerts on connections in either direction (reserved).
	DirectionBoth Direction = "both"
)

// NetworkRule configures a single network port tripwire for the NetworkWatcher.
type NetworkRule struct {
	// Name is the human-readable rule identifier; it becomes RuleName in
	// emitted AlertEvents.
	Name string

	// Port is the port number to monitor (1–65535).
	Port int

	// Protocol specifies tcp, udp, or both. Defaults to ProtocolTCP when
	// the zero value is provided to NewNetworkWatcher.
	Protocol Protocol

	// Direction specifies inbound, outbound, or both. Currently only
	// DirectionInbound is fully implemented. Defaults to DirectionInbound.
	Direction Direction

	// Severity is copied verbatim into every AlertEvent emitted by this
	// watcher. Must be one of "INFO", "WARN", or "CRITICAL".
	Severity string
}

// NetworkWatcher implements agent.Watcher and monitors inbound TCP and/or UDP
// connections on a configured port. It uses the standard net package listeners
// (net.Listen for TCP, net.ListenPacket for UDP) to accept connections and
// emits an AlertEvent for each observed connection or datagram. Closing a
// listener is the mechanism used to unblock Accept/ReadFrom when Stop is
// called.
//
// It is safe for concurrent use: Start and Stop may be called from different
// goroutines, and the Events channel may be read concurrently with Stop.
type NetworkWatcher struct {
	rule   NetworkRule
	logger *slog.Logger

	// events is the channel on which AlertEvents are published. It is
	// closed by Stop once all goroutines have exited.
	events chan agent.AlertEvent

	mu          sync.Mutex
	listeners   []net.Listener   // active TCP listeners
	packetConns []net.PacketConn // active UDP connections

	cancel context.CancelFunc // cancels the watcher's internal context
	wg     sync.WaitGroup     // tracks running goroutines
}

// NewNetworkWatcher creates a new NetworkWatcher for the given rule. The
// returned watcher is not yet started; call Start to begin monitoring.
//
// Providing a zero-value Protocol defaults to ProtocolTCP; a zero-value
// Direction defaults to DirectionInbound.
func NewNetworkWatcher(rule NetworkRule, logger *slog.Logger) *NetworkWatcher {
	if rule.Protocol == "" {
		rule.Protocol = ProtocolTCP
	}
	if rule.Direction == "" {
		rule.Direction = DirectionInbound
	}
	if logger == nil {
		logger = slog.Default()
	}
	return &NetworkWatcher{
		rule:   rule,
		logger: logger,
		events: make(chan agent.AlertEvent, 64),
	}
}

// Start begins monitoring the configured port. It opens one or two listeners
// (TCP, UDP, or both according to rule.Protocol) and launches goroutines to
// process incoming connections and emit AlertEvents.
//
// Start returns an error if any required listener cannot be opened, for
// example because the port is already in use or the process lacks sufficient
// capability (e.g. for ports below 1024 or raw-socket listeners).
//
// Calling Start on an already-running watcher is a no-op.
func (w *NetworkWatcher) Start(ctx context.Context) error {
	w.mu.Lock()
	defer w.mu.Unlock()

	if w.cancel != nil {
		// Already running.
		return nil
	}

	if w.rule.Port < 1 || w.rule.Port > 65535 {
		return fmt.Errorf("network watcher %q: invalid port %d (must be 1–65535)", w.rule.Name, w.rule.Port)
	}

	ctx, cancel := context.WithCancel(ctx)
	w.cancel = cancel

	addr := fmt.Sprintf(":%d", w.rule.Port)

	if w.rule.Protocol == ProtocolTCP || w.rule.Protocol == ProtocolBoth {
		ln, err := net.Listen("tcp", addr)
		if err != nil {
			cancel()
			w.cancel = nil
			return fmt.Errorf("network watcher %q: cannot open TCP listener on %s: %w", w.rule.Name, addr, err)
		}
		w.listeners = append(w.listeners, ln)
		w.wg.Add(1)
		go w.acceptTCP(ctx, ln)
	}

	if w.rule.Protocol == ProtocolUDP || w.rule.Protocol == ProtocolBoth {
		pc, err := net.ListenPacket("udp", addr)
		if err != nil {
			// Roll back any TCP listeners opened above.
			for _, ln := range w.listeners {
				ln.Close()
			}
			w.listeners = nil
			cancel()
			w.cancel = nil
			return fmt.Errorf("network watcher %q: cannot open UDP listener on %s: %w", w.rule.Name, addr, err)
		}
		w.packetConns = append(w.packetConns, pc)
		w.wg.Add(1)
		go w.readUDP(ctx, pc)
	}

	w.logger.Info("network watcher started",
		slog.String("rule", w.rule.Name),
		slog.Int("port", w.rule.Port),
		slog.String("protocol", string(w.rule.Protocol)),
		slog.String("direction", string(w.rule.Direction)),
	)

	return nil
}

// Stop signals the watcher to cease monitoring and release resources. It
// closes all open listeners (which unblocks any pending Accept or ReadFrom
// calls), waits for all goroutines to exit, and then closes the Events
// channel.
//
// Stop is safe to call multiple times; subsequent calls are no-ops.
func (w *NetworkWatcher) Stop() {
	w.mu.Lock()
	if w.cancel == nil {
		w.mu.Unlock()
		return
	}

	cancel := w.cancel
	w.cancel = nil

	// Close all listeners to unblock goroutines waiting in Accept/ReadFrom.
	for _, ln := range w.listeners {
		ln.Close()
	}
	for _, pc := range w.packetConns {
		pc.Close()
	}
	w.listeners = nil
	w.packetConns = nil

	w.mu.Unlock()

	// Cancel the context and wait for goroutines.
	cancel()
	w.wg.Wait()

	// Close the events channel after all producers have exited.
	close(w.events)

	w.logger.Info("network watcher stopped", slog.String("rule", w.rule.Name))
}

// Events returns a read-only channel from which callers receive AlertEvents.
// The channel is closed when the watcher stops (after Stop returns).
func (w *NetworkWatcher) Events() <-chan agent.AlertEvent {
	return w.events
}

// acceptTCP loops, accepting TCP connections on ln and emitting an AlertEvent
// for each one. It exits when ln is closed or ctx is done.
func (w *NetworkWatcher) acceptTCP(ctx context.Context, ln net.Listener) {
	defer w.wg.Done()

	for {
		conn, err := ln.Accept()
		if err != nil {
			// Check whether we are shutting down.
			select {
			case <-ctx.Done():
				return
			default:
			}
			w.logger.Warn("network watcher: TCP accept error",
				slog.String("rule", w.rule.Name),
				slog.Any("error", err),
			)
			// A closed listener returns immediately; avoid a tight spin on
			// any other permanent error.
			return
		}

		// Extract source information before closing the connection.
		sourceIP, _, _ := net.SplitHostPort(conn.RemoteAddr().String())
		conn.Close()

		w.emit(agent.AlertEvent{
			TripwireType: "NETWORK",
			RuleName:     w.rule.Name,
			Severity:     w.rule.Severity,
			Timestamp:    time.Now().UTC(),
			Detail: map[string]any{
				"source_ip":        sourceIP,
				"destination_port": w.rule.Port,
				"protocol":         "tcp",
			},
		})
	}
}

// readUDP loops, reading UDP datagrams from pc and emitting an AlertEvent
// for each one. It exits when pc is closed or ctx is done.
func (w *NetworkWatcher) readUDP(ctx context.Context, pc net.PacketConn) {
	defer w.wg.Done()

	// A one-byte buffer is sufficient; we only need the source address.
	buf := make([]byte, 1)

	for {
		_, addr, err := pc.ReadFrom(buf)
		if err != nil {
			select {
			case <-ctx.Done():
				return
			default:
			}
			w.logger.Warn("network watcher: UDP read error",
				slog.String("rule", w.rule.Name),
				slog.Any("error", err),
			)
			return
		}

		var sourceIP string
		if udpAddr, ok := addr.(*net.UDPAddr); ok {
			sourceIP = udpAddr.IP.String()
		} else {
			// Fallback: strip the port from the string representation.
			sourceIP, _, _ = net.SplitHostPort(addr.String())
		}

		w.emit(agent.AlertEvent{
			TripwireType: "NETWORK",
			RuleName:     w.rule.Name,
			Severity:     w.rule.Severity,
			Timestamp:    time.Now().UTC(),
			Detail: map[string]any{
				"source_ip":        sourceIP,
				"destination_port": w.rule.Port,
				"protocol":         "udp",
			},
		})
	}
}

// emit sends an event to the Events channel in a non-blocking fashion. If the
// channel buffer is full the event is dropped and a warning is logged rather
// than blocking the listener goroutine.
func (w *NetworkWatcher) emit(evt agent.AlertEvent) {
	select {
	case w.events <- evt:
	default:
		w.logger.Warn("network watcher: event channel full, dropping event",
			slog.String("rule", w.rule.Name),
			slog.String("type", evt.TripwireType),
		)
	}
}
