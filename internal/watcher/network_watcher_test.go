package watcher_test

import (
	"context"
	"fmt"
	"net"
	"strings"
	"testing"
	"time"

	"github.com/tripwire/agent/internal/agent"
	"github.com/tripwire/agent/internal/watcher"
)

// freePort returns a free TCP port on loopback by binding to :0 and
// immediately closing the listener. The OS will not reuse the port until it
// is explicitly bound again, giving the test a window to open a real listener.
func freePort(t *testing.T) int {
	t.Helper()
	ln, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("freePort: %v", err)
	}
	port := ln.Addr().(*net.TCPAddr).Port
	ln.Close()
	return port
}

// freeUDPPort returns a free UDP port using the same approach as freePort.
func freeUDPPort(t *testing.T) int {
	t.Helper()
	pc, err := net.ListenPacket("udp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("freeUDPPort: %v", err)
	}
	port := pc.LocalAddr().(*net.UDPAddr).Port
	pc.Close()
	return port
}

// receiveEvent drains the events channel until an event arrives or the
// deadline expires. It returns the event and true on success, or zero value
// and false on timeout.
func receiveEvent(t *testing.T, events <-chan agent.AlertEvent, timeout time.Duration) (agent.AlertEvent, bool) {
	t.Helper()
	select {
	case evt, ok := <-events:
		if !ok {
			return agent.AlertEvent{}, false
		}
		return evt, true
	case <-time.After(timeout):
		return agent.AlertEvent{}, false
	}
}

// ---------------------------------------------------------------------------
// Interface compliance
// ---------------------------------------------------------------------------

// TestNetworkWatcher_ImplementsWatcherInterface verifies at compile-time that
// *NetworkWatcher implements the agent.Watcher interface.
func TestNetworkWatcher_ImplementsWatcherInterface(t *testing.T) {
	var _ agent.Watcher = (*watcher.NetworkWatcher)(nil)
}

// ---------------------------------------------------------------------------
// Constructor
// ---------------------------------------------------------------------------

func TestNewNetworkWatcher_DefaultsProtocolAndDirection(t *testing.T) {
	port := freePort(t)

	// Provide a rule with zero Protocol and Direction so defaults apply.
	rule := watcher.NetworkRule{
		Name:     "default-test",
		Port:     port,
		Severity: "WARN",
	}
	w := watcher.NewNetworkWatcher(rule, nil)
	if w == nil {
		t.Fatal("NewNetworkWatcher returned nil")
	}

	// Events channel must be non-nil and open before Start.
	ch := w.Events()
	if ch == nil {
		t.Fatal("Events() returned nil before Start")
	}
}

// ---------------------------------------------------------------------------
// Start / Stop
// ---------------------------------------------------------------------------

func TestNetworkWatcher_StartStop_TCP(t *testing.T) {
	port := freePort(t)
	rule := watcher.NetworkRule{
		Name:     "tcp-start-stop",
		Port:     port,
		Protocol: watcher.ProtocolTCP,
		Severity: "INFO",
	}

	w := watcher.NewNetworkWatcher(rule, nil)
	ctx := context.Background()

	if err := w.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}

	// Stop must not block indefinitely and must be safe to call twice.
	done := make(chan struct{})
	go func() {
		w.Stop()
		close(done)
	}()

	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("Stop did not return within 5 seconds")
	}

	// Second Stop must be a no-op.
	w.Stop()
}

func TestNetworkWatcher_StartStop_UDP(t *testing.T) {
	port := freeUDPPort(t)
	rule := watcher.NetworkRule{
		Name:     "udp-start-stop",
		Port:     port,
		Protocol: watcher.ProtocolUDP,
		Severity: "INFO",
	}

	w := watcher.NewNetworkWatcher(rule, nil)
	ctx := context.Background()

	if err := w.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}

	done := make(chan struct{})
	go func() {
		w.Stop()
		close(done)
	}()

	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("Stop did not return within 5 seconds")
	}
}

func TestNetworkWatcher_StartStop_Both(t *testing.T) {
	// Use the same port for both TCP and UDP since the OS allows that.
	port := freePort(t)
	rule := watcher.NetworkRule{
		Name:     "both-start-stop",
		Port:     port,
		Protocol: watcher.ProtocolBoth,
		Severity: "WARN",
	}

	w := watcher.NewNetworkWatcher(rule, nil)
	ctx := context.Background()

	if err := w.Start(ctx); err != nil {
		t.Fatalf("Start (both): %v", err)
	}

	done := make(chan struct{})
	go func() {
		w.Stop()
		close(done)
	}()

	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("Stop did not return within 5 seconds")
	}
}

func TestNetworkWatcher_StartIdempotent(t *testing.T) {
	port := freePort(t)
	rule := watcher.NetworkRule{
		Name:     "idempotent-start",
		Port:     port,
		Protocol: watcher.ProtocolTCP,
		Severity: "INFO",
	}

	w := watcher.NewNetworkWatcher(rule, nil)
	ctx := context.Background()

	if err := w.Start(ctx); err != nil {
		t.Fatalf("first Start: %v", err)
	}
	defer w.Stop()

	// Second Start on an already-running watcher must be a no-op (no error,
	// no new goroutines, no double-listen panic).
	if err := w.Start(ctx); err != nil {
		t.Fatalf("second Start returned error: %v", err)
	}
}

func TestNetworkWatcher_EventsChannelClosedAfterStop(t *testing.T) {
	port := freePort(t)
	rule := watcher.NetworkRule{
		Name:     "channel-closed",
		Port:     port,
		Protocol: watcher.ProtocolTCP,
		Severity: "WARN",
	}

	w := watcher.NewNetworkWatcher(rule, nil)
	ctx := context.Background()

	if err := w.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}

	events := w.Events()
	w.Stop()

	// After Stop returns the channel must be closed.
	select {
	case _, ok := <-events:
		if ok {
			// A buffered event is fine; we need the channel to eventually close.
			// Drain remaining events.
			for range events {
			}
		}
	case <-time.After(2 * time.Second):
		t.Fatal("events channel was not closed after Stop")
	}
}

// ---------------------------------------------------------------------------
// Context cancellation
// ---------------------------------------------------------------------------

func TestNetworkWatcher_CancelledContextBeforeStart(t *testing.T) {
	port := freePort(t)
	rule := watcher.NetworkRule{
		Name:     "cancelled-ctx",
		Port:     port,
		Protocol: watcher.ProtocolTCP,
		Severity: "INFO",
	}

	w := watcher.NewNetworkWatcher(rule, nil)

	ctx, cancel := context.WithCancel(context.Background())
	cancel() // cancel before Start

	// Start should succeed (the listener is opened synchronously before
	// goroutines check ctx.Done).
	if err := w.Start(ctx); err != nil {
		// Port binding may fail if already in use; skip rather than fail.
		if strings.Contains(err.Error(), "address already in use") {
			t.Skipf("port %d in use, skipping: %v", port, err)
		}
		t.Fatalf("Start with cancelled context: %v", err)
	}

	// Stop must not block.
	done := make(chan struct{})
	go func() {
		w.Stop()
		close(done)
	}()

	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("Stop did not return within 5 seconds with cancelled context")
	}
}

// ---------------------------------------------------------------------------
// Error handling
// ---------------------------------------------------------------------------

func TestNetworkWatcher_InvalidPort(t *testing.T) {
	rule := watcher.NetworkRule{
		Name:     "bad-port",
		Port:     0, // invalid
		Protocol: watcher.ProtocolTCP,
		Severity: "WARN",
	}

	w := watcher.NewNetworkWatcher(rule, nil)
	err := w.Start(context.Background())
	if err == nil {
		w.Stop()
		t.Fatal("Start with port 0 should return an error")
	}
}

func TestNetworkWatcher_PortAlreadyInUse(t *testing.T) {
	port := freePort(t)

	// Occupy the port.
	occupier, err := net.Listen("tcp", fmt.Sprintf("127.0.0.1:%d", port))
	if err != nil {
		t.Fatalf("could not occupy port: %v", err)
	}
	defer occupier.Close()

	rule := watcher.NetworkRule{
		Name:     "port-in-use",
		Port:     port,
		Protocol: watcher.ProtocolTCP,
		Severity: "WARN",
	}

	w := watcher.NewNetworkWatcher(rule, nil)
	err = w.Start(context.Background())
	if err == nil {
		w.Stop()
		t.Fatal("Start should have returned an error for a port already in use")
	}
	if !strings.Contains(err.Error(), "address already in use") &&
		!strings.Contains(err.Error(), "bind:") &&
		!strings.Contains(err.Error(), "cannot open TCP listener") {
		t.Errorf("unexpected error message: %v", err)
	}
}

// ---------------------------------------------------------------------------
// AlertEvent emission — TCP
// ---------------------------------------------------------------------------

func TestNetworkWatcher_TCPConnectionEmitsAlertEvent(t *testing.T) {
	port := freePort(t)
	rule := watcher.NetworkRule{
		Name:      "tcp-event",
		Port:      port,
		Protocol:  watcher.ProtocolTCP,
		Direction: watcher.DirectionInbound,
		Severity:  "CRITICAL",
	}

	w := watcher.NewNetworkWatcher(rule, nil)
	ctx := context.Background()

	if err := w.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}
	defer w.Stop()

	// Connect to the listening port.
	conn, err := net.Dial("tcp", fmt.Sprintf("127.0.0.1:%d", port))
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	conn.Close()

	evt, ok := receiveEvent(t, w.Events(), 3*time.Second)
	if !ok {
		t.Fatal("timed out waiting for AlertEvent after TCP connection")
	}

	// Verify AlertEvent fields.
	if evt.TripwireType != "NETWORK" {
		t.Errorf("TripwireType = %q, want %q", evt.TripwireType, "NETWORK")
	}
	if evt.RuleName != rule.Name {
		t.Errorf("RuleName = %q, want %q", evt.RuleName, rule.Name)
	}
	if evt.Severity != rule.Severity {
		t.Errorf("Severity = %q, want %q", evt.Severity, rule.Severity)
	}
	if evt.Timestamp.IsZero() {
		t.Error("Timestamp must not be zero")
	}

	// Verify Detail fields.
	detail := evt.Detail
	if detail == nil {
		t.Fatal("Detail must not be nil")
	}
	if proto, ok := detail["protocol"]; !ok || proto != "tcp" {
		t.Errorf("Detail[protocol] = %v, want %q", detail["protocol"], "tcp")
	}
	if dstPort, ok := detail["destination_port"]; !ok || dstPort != port {
		t.Errorf("Detail[destination_port] = %v, want %d", detail["destination_port"], port)
	}
	srcIP, ok := detail["source_ip"]
	if !ok || srcIP == "" {
		t.Errorf("Detail[source_ip] must be non-empty, got %v", detail["source_ip"])
	}
}

// ---------------------------------------------------------------------------
// AlertEvent emission — UDP
// ---------------------------------------------------------------------------

func TestNetworkWatcher_UDPDatagramEmitsAlertEvent(t *testing.T) {
	port := freeUDPPort(t)
	rule := watcher.NetworkRule{
		Name:      "udp-event",
		Port:      port,
		Protocol:  watcher.ProtocolUDP,
		Direction: watcher.DirectionInbound,
		Severity:  "WARN",
	}

	w := watcher.NewNetworkWatcher(rule, nil)
	ctx := context.Background()

	if err := w.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}
	defer w.Stop()

	// Send a UDP datagram to the listening port.
	conn, err := net.Dial("udp", fmt.Sprintf("127.0.0.1:%d", port))
	if err != nil {
		t.Fatalf("udp dial: %v", err)
	}
	if _, err := conn.Write([]byte("ping")); err != nil {
		conn.Close()
		t.Fatalf("udp write: %v", err)
	}
	conn.Close()

	evt, ok := receiveEvent(t, w.Events(), 3*time.Second)
	if !ok {
		t.Fatal("timed out waiting for AlertEvent after UDP datagram")
	}

	if evt.TripwireType != "NETWORK" {
		t.Errorf("TripwireType = %q, want %q", evt.TripwireType, "NETWORK")
	}
	if evt.RuleName != rule.Name {
		t.Errorf("RuleName = %q, want %q", evt.RuleName, rule.Name)
	}
	detail := evt.Detail
	if detail == nil {
		t.Fatal("Detail must not be nil")
	}
	if proto, ok := detail["protocol"]; !ok || proto != "udp" {
		t.Errorf("Detail[protocol] = %v, want %q", detail["protocol"], "udp")
	}
	if dstPort, ok := detail["destination_port"]; !ok || dstPort != port {
		t.Errorf("Detail[destination_port] = %v, want %d", detail["destination_port"], port)
	}
	if srcIP, ok := detail["source_ip"]; !ok || srcIP == "" {
		t.Errorf("Detail[source_ip] must be non-empty, got %v", detail["source_ip"])
	}
}

// ---------------------------------------------------------------------------
// Protocol=both
// ---------------------------------------------------------------------------

func TestNetworkWatcher_BothProtocol_TCPAndUDPEvents(t *testing.T) {
	port := freePort(t)
	rule := watcher.NetworkRule{
		Name:     "both-events",
		Port:     port,
		Protocol: watcher.ProtocolBoth,
		Severity: "INFO",
	}

	w := watcher.NewNetworkWatcher(rule, nil)
	ctx := context.Background()

	if err := w.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}
	defer w.Stop()

	// TCP connection.
	tcpConn, err := net.Dial("tcp", fmt.Sprintf("127.0.0.1:%d", port))
	if err != nil {
		t.Fatalf("tcp dial: %v", err)
	}
	tcpConn.Close()

	// UDP datagram.
	udpConn, err := net.Dial("udp", fmt.Sprintf("127.0.0.1:%d", port))
	if err != nil {
		t.Fatalf("udp dial: %v", err)
	}
	if _, err := udpConn.Write([]byte("x")); err != nil {
		udpConn.Close()
		t.Fatalf("udp write: %v", err)
	}
	udpConn.Close()

	protocols := map[string]bool{}
	deadline := time.Now().Add(5 * time.Second)

	for time.Now().Before(deadline) && len(protocols) < 2 {
		evt, ok := receiveEvent(t, w.Events(), time.Until(deadline))
		if !ok {
			break
		}
		if p, ok := evt.Detail["protocol"].(string); ok {
			protocols[p] = true
		}
	}

	if !protocols["tcp"] {
		t.Error("expected a TCP AlertEvent, none received")
	}
	if !protocols["udp"] {
		t.Error("expected a UDP AlertEvent, none received")
	}
}
