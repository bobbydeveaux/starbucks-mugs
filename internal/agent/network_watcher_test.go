package agent_test

import (
	"context"
	"errors"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/tripwire/agent/internal/agent"
	"github.com/tripwire/agent/internal/config"
)

// ---------------------------------------------------------------------------
// Test doubles
// ---------------------------------------------------------------------------

// fakeProcNetReader implements agent.ProcNetReader with injectable slices of
// ConnEntry values.  All fields are protected by a mutex so that the test
// goroutine can safely mutate them between polls while the watcher goroutine
// is calling ReadTCP concurrently.
type fakeProcNetReader struct {
	mu         sync.Mutex
	tcpEntries []agent.ConnEntry
	udpEntries []agent.ConnEntry
	tcpErr     error
	udpErr     error
}

func (f *fakeProcNetReader) ReadTCP() ([]agent.ConnEntry, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.tcpEntries, f.tcpErr
}
func (f *fakeProcNetReader) ReadUDP() ([]agent.ConnEntry, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.udpEntries, f.udpErr
}

// setTCP atomically replaces the TCP connection list.
func (f *fakeProcNetReader) setTCP(entries []agent.ConnEntry) {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.tcpEntries = entries
}

// errorThenSucceedReader returns an error on the first ReadTCP call and a
// real connection on all subsequent calls.  Used to test error recovery.
type errorThenSucceedReader struct {
	conn  agent.ConnEntry
	calls int
}

func (r *errorThenSucceedReader) ReadTCP() ([]agent.ConnEntry, error) {
	r.calls++
	if r.calls == 1 {
		return nil, errors.New("simulated proc read error")
	}
	return []agent.ConnEntry{r.conn}, nil
}
func (r *errorThenSucceedReader) ReadUDP() ([]agent.ConnEntry, error) { return nil, nil }

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// mkNetworkRule builds a NETWORK TripwireRule for use in tests.
func mkNetworkRule(name, port, severity string) config.TripwireRule {
	return config.TripwireRule{
		Name:     name,
		Type:     "NETWORK",
		Target:   port,
		Severity: severity,
	}
}

// establishedConn returns a ConnEntry simulating an established inbound TCP
// connection: local port is destPort, remote side is remoteIP:remotePort.
func establishedConn(destPort int, remoteIP string, remotePort int) agent.ConnEntry {
	return agent.ConnEntry{
		LocalAddr:  "10.0.0.1",
		LocalPort:  destPort,
		RemoteAddr: remoteIP,
		RemotePort: remotePort,
		State:      1, // TCP_ESTABLISHED
	}
}

// listenConn returns a ConnEntry in the LISTEN state on the given port.
func listenConn(port int) agent.ConnEntry {
	return agent.ConnEntry{
		LocalAddr:  "0.0.0.0",
		LocalPort:  port,
		RemoteAddr: "0.0.0.0",
		RemotePort: 0,
		State:      10, // TCP_LISTEN
	}
}

// drainEvents reads all available events from ch until it is either closed or
// timeout elapses, then returns whatever was collected.
func drainEvents(ch <-chan agent.AlertEvent, timeout time.Duration) []agent.AlertEvent {
	var evts []agent.AlertEvent
	timer := time.NewTimer(timeout)
	defer timer.Stop()
	for {
		select {
		case evt, ok := <-ch:
			if !ok {
				return evts
			}
			evts = append(evts, evt)
		case <-timer.C:
			return evts
		}
	}
}

// waitForN blocks until at least n events have been collected or timeout
// elapses, then returns whatever was collected.
func waitForN(ch <-chan agent.AlertEvent, n int, timeout time.Duration) []agent.AlertEvent {
	var evts []agent.AlertEvent
	timer := time.NewTimer(timeout)
	defer timer.Stop()
	for {
		select {
		case evt, ok := <-ch:
			if !ok {
				return evts
			}
			evts = append(evts, evt)
			if len(evts) >= n {
				return evts
			}
		case <-timer.C:
			return evts
		}
	}
}

// ---------------------------------------------------------------------------
// Constructor tests
// ---------------------------------------------------------------------------

func TestNewNetworkWatcher_ReturnsNonNilWatcher(t *testing.T) {
	rules := []config.TripwireRule{mkNetworkRule("ssh-watch", "22", "WARN")}
	w := agent.NewNetworkWatcher(rules, noopLogger())
	if w == nil {
		t.Fatal("NewNetworkWatcher returned nil")
	}
}

func TestNewNetworkWatcher_SkipsNonNetworkRules(t *testing.T) {
	// FILE and PROCESS rules must be silently ignored.
	rules := []config.TripwireRule{
		{Name: "file-watch", Type: "FILE", Target: "/etc/passwd", Severity: "CRITICAL"},
		{Name: "proc-watch", Type: "PROCESS", Target: "bash", Severity: "WARN"},
	}
	reader := &fakeProcNetReader{
		tcpEntries: []agent.ConnEntry{establishedConn(8080, "1.2.3.4", 50000)},
	}
	w := agent.NewNetworkWatcher(rules, noopLogger(),
		agent.WithProcNetReader(reader),
		agent.WithPollInterval(10*time.Millisecond),
	)

	if err := w.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}
	evts := drainEvents(w.Events(), 100*time.Millisecond)
	w.Stop()

	if len(evts) != 0 {
		t.Errorf("got %d event(s), want 0 (non-NETWORK rules must be ignored)", len(evts))
	}
}

func TestNewNetworkWatcher_SkipsInvalidPortTargets(t *testing.T) {
	// Non-numeric, zero, and out-of-range port values must all be discarded.
	rules := []config.TripwireRule{
		mkNetworkRule("bad-alpha", "notaport", "WARN"),
		mkNetworkRule("bad-zero", "0", "WARN"),
		mkNetworkRule("bad-high", "65536", "WARN"),
		mkNetworkRule("bad-neg", "-1", "WARN"),
	}
	reader := &fakeProcNetReader{
		// Include connections on those "ports" to confirm no spurious alert.
		tcpEntries: []agent.ConnEntry{
			establishedConn(0, "1.2.3.4", 50000),
		},
	}
	w := agent.NewNetworkWatcher(rules, noopLogger(),
		agent.WithProcNetReader(reader),
		agent.WithPollInterval(10*time.Millisecond),
	)

	if err := w.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}
	evts := drainEvents(w.Events(), 100*time.Millisecond)
	w.Stop()

	if len(evts) != 0 {
		t.Errorf("got %d event(s) from invalid port rules, want 0", len(evts))
	}
}

func TestNewNetworkWatcher_MixedRuleTypes_OnlyNetworkRulesMonitored(t *testing.T) {
	rules := []config.TripwireRule{
		{Name: "file-etc", Type: "FILE", Target: "/etc/shadow", Severity: "CRITICAL"},
		mkNetworkRule("http-watch", "80", "WARN"),
		{Name: "proc-nc", Type: "PROCESS", Target: "nc", Severity: "WARN"},
		mkNetworkRule("ssh-watch", "22", "CRITICAL"),
	}
	reader := &fakeProcNetReader{
		tcpEntries: []agent.ConnEntry{
			establishedConn(80, "5.6.7.8", 12345),
			establishedConn(22, "9.10.11.12", 54321),
		},
	}
	w := agent.NewNetworkWatcher(rules, noopLogger(),
		agent.WithProcNetReader(reader),
		agent.WithPollInterval(10*time.Millisecond),
	)

	if err := w.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}
	evts := waitForN(w.Events(), 2, 500*time.Millisecond)
	w.Stop()

	if len(evts) != 2 {
		t.Errorf("got %d events, want 2 (one per NETWORK rule)", len(evts))
	}
}

// ---------------------------------------------------------------------------
// Watcher interface compliance tests
// ---------------------------------------------------------------------------

func TestNetworkWatcher_ImplementsWatcherInterface(t *testing.T) {
	// Compile-time assertion: *NetworkWatcher must satisfy agent.Watcher.
	var _ agent.Watcher = agent.NewNetworkWatcher(nil, noopLogger())
}

func TestNetworkWatcher_StartStop_NoRules(t *testing.T) {
	w := agent.NewNetworkWatcher(nil, noopLogger(),
		agent.WithPollInterval(10*time.Millisecond),
	)
	if err := w.Start(context.Background()); err != nil {
		t.Fatalf("Start with no rules: %v", err)
	}
	w.Stop() // must not block or panic
}

func TestNetworkWatcher_StopIsIdempotent(t *testing.T) {
	w := agent.NewNetworkWatcher(nil, noopLogger())
	if err := w.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}
	// Multiple Stop calls must not panic or deadlock.
	w.Stop()
	w.Stop()
}

// ---------------------------------------------------------------------------
// Event emission tests
// ---------------------------------------------------------------------------

func TestNetworkWatcher_EmitsEventForEstablishedConnection(t *testing.T) {
	reader := &fakeProcNetReader{
		tcpEntries: []agent.ConnEntry{
			establishedConn(2222, "192.168.1.50", 45678),
		},
	}
	rules := []config.TripwireRule{mkNetworkRule("ssh-tripwire", "2222", "CRITICAL")}

	w := agent.NewNetworkWatcher(rules, noopLogger(),
		agent.WithProcNetReader(reader),
		agent.WithPollInterval(10*time.Millisecond),
	)
	if err := w.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}
	evts := waitForN(w.Events(), 1, 500*time.Millisecond)
	w.Stop()

	if len(evts) != 1 {
		t.Fatalf("got %d event(s), want 1", len(evts))
	}
	evt := evts[0]
	if evt.TripwireType != "NETWORK" {
		t.Errorf("TripwireType = %q, want %q", evt.TripwireType, "NETWORK")
	}
	if evt.RuleName != "ssh-tripwire" {
		t.Errorf("RuleName = %q, want %q", evt.RuleName, "ssh-tripwire")
	}
	if evt.Severity != "CRITICAL" {
		t.Errorf("Severity = %q, want %q", evt.Severity, "CRITICAL")
	}
}

func TestNetworkWatcher_EventDetail_ContainsPRDRequiredFields(t *testing.T) {
	// PRD US-04 requires: source IP, destination port, and protocol.
	conn := establishedConn(2222, "10.10.10.5", 55000)
	reader := &fakeProcNetReader{tcpEntries: []agent.ConnEntry{conn}}
	rules := []config.TripwireRule{mkNetworkRule("ssh-watch", "2222", "WARN")}

	w := agent.NewNetworkWatcher(rules, noopLogger(),
		agent.WithProcNetReader(reader),
		agent.WithPollInterval(10*time.Millisecond),
	)
	if err := w.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}
	evts := waitForN(w.Events(), 1, 500*time.Millisecond)
	w.Stop()

	if len(evts) != 1 {
		t.Fatalf("got %d event(s), want 1", len(evts))
	}

	d := evts[0].Detail
	checks := []struct {
		key  string
		want any
	}{
		{"source_ip", "10.10.10.5"},
		{"dest_port", 2222},
		{"protocol", "tcp"},
		{"direction", "inbound"},
	}
	for _, c := range checks {
		got, ok := d[c.key]
		if !ok {
			t.Errorf("Detail missing key %q", c.key)
			continue
		}
		if got != c.want {
			t.Errorf("Detail[%q] = %v (%T), want %v (%T)",
				c.key, got, got, c.want, c.want)
		}
	}
}

func TestNetworkWatcher_EventTimestampIsRecent(t *testing.T) {
	before := time.Now().UTC().Add(-time.Second)
	reader := &fakeProcNetReader{
		tcpEntries: []agent.ConnEntry{establishedConn(9090, "1.2.3.4", 60000)},
	}
	rules := []config.TripwireRule{mkNetworkRule("web-watch", "9090", "INFO")}

	w := agent.NewNetworkWatcher(rules, noopLogger(),
		agent.WithProcNetReader(reader),
		agent.WithPollInterval(10*time.Millisecond),
	)
	if err := w.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}
	evts := waitForN(w.Events(), 1, 500*time.Millisecond)
	w.Stop()

	if len(evts) != 1 {
		t.Fatalf("got %d event(s), want 1", len(evts))
	}
	after := time.Now().UTC().Add(time.Second)
	ts := evts[0].Timestamp
	if ts.Before(before) || ts.After(after) {
		t.Errorf("Timestamp %v is outside expected window [%v, %v]", ts, before, after)
	}
}

func TestNetworkWatcher_NoEventForListenOnlyState(t *testing.T) {
	// A port in LISTEN state (state 10) without an established peer must not
	// generate an alert.
	reader := &fakeProcNetReader{
		tcpEntries: []agent.ConnEntry{listenConn(2222)},
	}
	rules := []config.TripwireRule{mkNetworkRule("ssh-watch", "2222", "CRITICAL")}

	w := agent.NewNetworkWatcher(rules, noopLogger(),
		agent.WithProcNetReader(reader),
		agent.WithPollInterval(10*time.Millisecond),
	)
	if err := w.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}
	evts := drainEvents(w.Events(), 150*time.Millisecond)
	w.Stop()

	if len(evts) != 0 {
		t.Errorf("got %d event(s) for LISTEN-only entry, want 0", len(evts))
	}
}

func TestNetworkWatcher_NoEventForUnmonitoredPort(t *testing.T) {
	// Connections on ports absent from the rule list must be silently ignored.
	reader := &fakeProcNetReader{
		tcpEntries: []agent.ConnEntry{
			establishedConn(80, "1.2.3.4", 50000),
			establishedConn(443, "5.6.7.8", 60000),
		},
	}
	rules := []config.TripwireRule{mkNetworkRule("ssh-watch", "22", "CRITICAL")}

	w := agent.NewNetworkWatcher(rules, noopLogger(),
		agent.WithProcNetReader(reader),
		agent.WithPollInterval(10*time.Millisecond),
	)
	if err := w.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}
	evts := drainEvents(w.Events(), 150*time.Millisecond)
	w.Stop()

	if len(evts) != 0 {
		t.Errorf("got %d event(s) for unmonitored ports, want 0", len(evts))
	}
}

// ---------------------------------------------------------------------------
// De-duplication and reconnection tests
// ---------------------------------------------------------------------------

func TestNetworkWatcher_DeduplicatesPersistentConnection(t *testing.T) {
	// A connection that persists across several polls must generate exactly one
	// alert.
	conn := establishedConn(22, "192.168.0.10", 51000)
	reader := &fakeProcNetReader{tcpEntries: []agent.ConnEntry{conn}}
	rules := []config.TripwireRule{mkNetworkRule("ssh-watch", "22", "WARN")}

	w := agent.NewNetworkWatcher(rules, noopLogger(),
		agent.WithProcNetReader(reader),
		agent.WithPollInterval(10*time.Millisecond),
	)
	if err := w.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}
	// Allow at least 5 polls to occur.
	time.Sleep(80 * time.Millisecond)
	w.Stop()

	evts := drainEvents(w.Events(), 50*time.Millisecond)
	if len(evts) != 1 {
		t.Errorf("got %d event(s) for persistent connection, want exactly 1", len(evts))
	}
}

func TestNetworkWatcher_ReAlertsAfterReconnect(t *testing.T) {
	// When a connection disappears and then reappears (client reconnects), a
	// fresh alert must be generated.
	conn := establishedConn(22, "192.168.0.10", 51000)
	reader := &fakeProcNetReader{tcpEntries: []agent.ConnEntry{conn}}
	rules := []config.TripwireRule{mkNetworkRule("ssh-watch", "22", "WARN")}

	w := agent.NewNetworkWatcher(rules, noopLogger(),
		agent.WithProcNetReader(reader),
		agent.WithPollInterval(20*time.Millisecond),
	)
	if err := w.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}

	// Wait for the first alert.
	first := waitForN(w.Events(), 1, 500*time.Millisecond)
	if len(first) != 1 {
		t.Fatalf("expected 1 initial event, got %d", len(first))
	}

	// Simulate disconnect: clear the connection table.
	reader.setTCP(nil)
	time.Sleep(50 * time.Millisecond)

	// Simulate reconnect from the same source.
	reader.setTCP([]agent.ConnEntry{conn})

	second := waitForN(w.Events(), 1, 500*time.Millisecond)
	w.Stop()

	if len(second) != 1 {
		t.Errorf("expected 1 re-alert after reconnect, got %d", len(second))
	}
}

func TestNetworkWatcher_MultipleSimultaneousConnectionsSamePort(t *testing.T) {
	// Two concurrent connections from different source IPs must each produce
	// exactly one event.
	reader := &fakeProcNetReader{
		tcpEntries: []agent.ConnEntry{
			establishedConn(2222, "10.0.0.1", 40001),
			establishedConn(2222, "10.0.0.2", 40002),
		},
	}
	rules := []config.TripwireRule{mkNetworkRule("ssh-watch", "2222", "CRITICAL")}

	w := agent.NewNetworkWatcher(rules, noopLogger(),
		agent.WithProcNetReader(reader),
		agent.WithPollInterval(10*time.Millisecond),
	)
	if err := w.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}
	evts := waitForN(w.Events(), 2, 500*time.Millisecond)
	// Extra dwell to catch any spurious duplicates.
	time.Sleep(60 * time.Millisecond)
	w.Stop()
	evts = append(evts, drainEvents(w.Events(), 50*time.Millisecond)...)

	if len(evts) != 2 {
		t.Errorf("got %d event(s), want 2 (one per source IP)", len(evts))
	}
}

func TestNetworkWatcher_MultipleRulesSamePort_EachRuleAlerts(t *testing.T) {
	// Two rules watching the same port must each emit an independent alert for
	// the same connection.
	conn := establishedConn(80, "1.1.1.1", 55000)
	reader := &fakeProcNetReader{tcpEntries: []agent.ConnEntry{conn}}
	rules := []config.TripwireRule{
		mkNetworkRule("http-info", "80", "INFO"),
		mkNetworkRule("http-warn", "80", "WARN"),
	}

	w := agent.NewNetworkWatcher(rules, noopLogger(),
		agent.WithProcNetReader(reader),
		agent.WithPollInterval(10*time.Millisecond),
	)
	if err := w.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}
	evts := waitForN(w.Events(), 2, 500*time.Millisecond)
	w.Stop()

	if len(evts) != 2 {
		t.Fatalf("got %d event(s), want 2 (one per rule)", len(evts))
	}
	names := map[string]bool{}
	for _, e := range evts {
		names[e.RuleName] = true
	}
	if !names["http-info"] || !names["http-warn"] {
		t.Errorf("rule names in events = %v, want both http-info and http-warn", names)
	}
}

// ---------------------------------------------------------------------------
// Severity propagation tests
// ---------------------------------------------------------------------------

func TestNetworkWatcher_PropagatesSeverity(t *testing.T) {
	for _, sev := range []string{"INFO", "WARN", "CRITICAL"} {
		t.Run(sev, func(t *testing.T) {
			reader := &fakeProcNetReader{
				tcpEntries: []agent.ConnEntry{establishedConn(9999, "1.2.3.4", 50000)},
			}
			rules := []config.TripwireRule{mkNetworkRule("test-rule", "9999", sev)}

			w := agent.NewNetworkWatcher(rules, noopLogger(),
				agent.WithProcNetReader(reader),
				agent.WithPollInterval(10*time.Millisecond),
			)
			if err := w.Start(context.Background()); err != nil {
				t.Fatalf("Start: %v", err)
			}
			evts := waitForN(w.Events(), 1, 500*time.Millisecond)
			w.Stop()

			if len(evts) != 1 {
				t.Fatalf("got %d event(s), want 1", len(evts))
			}
			if evts[0].Severity != sev {
				t.Errorf("Severity = %q, want %q", evts[0].Severity, sev)
			}
		})
	}
}

// ---------------------------------------------------------------------------
// Error recovery tests
// ---------------------------------------------------------------------------

func TestNetworkWatcher_ContinuesPollingAfterReadError(t *testing.T) {
	// ReadTCP fails on the first poll; the watcher must recover and emit an
	// alert on the subsequent successful poll.
	conn := establishedConn(22, "10.0.0.1", 50000)
	reader := &errorThenSucceedReader{conn: conn}
	rules := []config.TripwireRule{mkNetworkRule("ssh-watch", "22", "WARN")}

	w := agent.NewNetworkWatcher(rules, noopLogger(),
		agent.WithProcNetReader(reader),
		agent.WithPollInterval(10*time.Millisecond),
	)
	if err := w.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}
	evts := waitForN(w.Events(), 1, 500*time.Millisecond)
	w.Stop()

	if len(evts) != 1 {
		t.Errorf("got %d event(s); watcher must recover after a read error", len(evts))
	}
}

// ---------------------------------------------------------------------------
// ParseProcNet unit tests
// ---------------------------------------------------------------------------

func TestParseProcNet_EmptyInput(t *testing.T) {
	// An empty reader (no lines at all) should return nil, nil.
	entries, err := agent.ParseProcNet(strings.NewReader(""))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(entries) != 0 {
		t.Errorf("got %d entries, want 0", len(entries))
	}
}

func TestParseProcNet_HeaderOnlyReturnsEmpty(t *testing.T) {
	// A file containing only the header line should return zero entries.
	input := "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
	entries, err := agent.ParseProcNet(strings.NewReader(input))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(entries) != 0 {
		t.Errorf("got %d entries, want 0", len(entries))
	}
}

func TestParseProcNet_IPv4EstablishedConnection(t *testing.T) {
	// 0100007F:0016 → 127.0.0.1:22  (local, little-endian IPv4)
	// 050F020A:D0B7 → 10.2.15.5:53431 (remote)
	// State 01 → TCP_ESTABLISHED
	input := strings.Join([]string{
		"  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode",
		"   0: 0100007F:0016 050F020A:D0B7 01 00000000:00000000 00:00000000 00000000     0        0 12345 1 0000000000000000 100 0 0 10 0",
	}, "\n")

	entries, err := agent.ParseProcNet(strings.NewReader(input))
	if err != nil {
		t.Fatalf("ParseProcNet error: %v", err)
	}
	if len(entries) != 1 {
		t.Fatalf("got %d entries, want 1", len(entries))
	}
	e := entries[0]
	if e.LocalAddr != "127.0.0.1" {
		t.Errorf("LocalAddr = %q, want 127.0.0.1", e.LocalAddr)
	}
	if e.LocalPort != 22 {
		t.Errorf("LocalPort = %d, want 22", e.LocalPort)
	}
	if e.RemoteAddr != "10.2.15.5" {
		t.Errorf("RemoteAddr = %q, want 10.2.15.5", e.RemoteAddr)
	}
	if e.RemotePort != 53431 {
		t.Errorf("RemotePort = %d, want 53431", e.RemotePort)
	}
	if e.State != 1 {
		t.Errorf("State = %d, want 1 (ESTABLISHED)", e.State)
	}
}

func TestParseProcNet_ListenEntry(t *testing.T) {
	// 00000000:0016 → 0.0.0.0:22 in LISTEN (0A hex = 10)
	input := strings.Join([]string{
		"  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode",
		"   0: 00000000:0016 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 1000 1 0000000000000000 100 0 0 10 0",
	}, "\n")

	entries, err := agent.ParseProcNet(strings.NewReader(input))
	if err != nil {
		t.Fatalf("ParseProcNet error: %v", err)
	}
	if len(entries) != 1 {
		t.Fatalf("got %d entries, want 1", len(entries))
	}
	if entries[0].State != 10 {
		t.Errorf("State = %d, want 10 (LISTEN)", entries[0].State)
	}
}

func TestParseProcNet_MultipleEntries(t *testing.T) {
	// Two data rows should produce two ConnEntry values.
	input := strings.Join([]string{
		"  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode",
		"   0: 0100007F:0016 050F020A:D0B7 01 00000000:00000000 00:00000000 00000000     0        0 100 1 0000000000000000 100 0 0 10 0",
		"   1: 0100007F:0050 060F020A:C350 01 00000000:00000000 00:00000000 00000000     0        0 101 1 0000000000000000 100 0 0 10 0",
	}, "\n")

	entries, err := agent.ParseProcNet(strings.NewReader(input))
	if err != nil {
		t.Fatalf("ParseProcNet error: %v", err)
	}
	if len(entries) != 2 {
		t.Errorf("got %d entries, want 2", len(entries))
	}
}

func TestParseProcNet_SkipsMalformedLines(t *testing.T) {
	// Lines with too few fields or unparseable hex values must be silently
	// skipped; valid rows must still be returned.
	input := strings.Join([]string{
		"  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode",
		"a b c",                                          // only 3 fields → skipped
		"   x: ZZZZZZZZ:0016 050F020A:D0B7 01",          // invalid IP hex → skipped
		"   0: 0100007F:0016 050F020A:D0B7 ZZHEX extra", // invalid state hex → skipped
		"   0: 0100007F:0016 050F020A:D0B7 01 extra-fields-here ignored 0 0 0 0 0 0 0 0",
	}, "\n")

	entries, err := agent.ParseProcNet(strings.NewReader(input))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	// Only the last line (fully valid) should produce an entry.
	if len(entries) != 1 {
		t.Errorf("got %d entries, want 1 (malformed lines must be skipped)", len(entries))
	}
}

func TestParseProcNet_LoopbackAddress(t *testing.T) {
	// 0100007F hex (little-endian) = 127.0.0.1
	input := strings.Join([]string{
		"  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode",
		"   0: 0100007F:1F90 0100007F:C350 01 00000000:00000000 00:00000000 00000000     0        0 200 1 0000000000000000 100 0 0 10 0",
	}, "\n")

	entries, err := agent.ParseProcNet(strings.NewReader(input))
	if err != nil {
		t.Fatalf("ParseProcNet error: %v", err)
	}
	if len(entries) != 1 {
		t.Fatalf("got %d entries, want 1", len(entries))
	}
	e := entries[0]
	if e.LocalAddr != "127.0.0.1" {
		t.Errorf("LocalAddr = %q, want 127.0.0.1", e.LocalAddr)
	}
	if e.RemoteAddr != "127.0.0.1" {
		t.Errorf("RemoteAddr = %q, want 127.0.0.1", e.RemoteAddr)
	}
	// 0x1F90 = 8080, 0xC350 = 50000
	if e.LocalPort != 8080 {
		t.Errorf("LocalPort = %d, want 8080 (0x1F90)", e.LocalPort)
	}
	if e.RemotePort != 50000 {
		t.Errorf("RemotePort = %d, want 50000 (0xC350)", e.RemotePort)
	}
}

// ---------------------------------------------------------------------------
// Real /proc/net/tcp integration (runs only on Linux with the file present)
// ---------------------------------------------------------------------------

func TestNetworkWatcher_RealProcNetTCP_StartStop(t *testing.T) {
	// Start the watcher with the real reader and verify no crash occurs.
	// Port 65535 is unlikely to have an active connection; this is purely a
	// "does it not panic" smoke test.
	w := agent.NewNetworkWatcher(
		[]config.TripwireRule{mkNetworkRule("smoke-test", "65535", "INFO")},
		noopLogger(),
		agent.WithPollInterval(50*time.Millisecond),
	)
	if err := w.Start(context.Background()); err != nil {
		t.Fatalf("Start with real reader: %v", err)
	}
	time.Sleep(120 * time.Millisecond)
	w.Stop()
	// Draining the closed channel must not block or panic.
	drainEvents(w.Events(), 20*time.Millisecond)
}
