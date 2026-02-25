package agent_test

import (
	"context"
	"errors"
	"log/slog"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/tripwire/agent/internal/agent"
	"github.com/tripwire/agent/internal/config"
)

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

func mkRule(name, target, severity string) config.TripwireRule {
	return config.TripwireRule{
		Name:     name,
		Type:     "NETWORK",
		Target:   target,
		Severity: severity,
	}
}

func silentLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelError + 100}))
}

// drainFor reads all events available on ch within the given duration.
func drainFor(ch <-chan agent.AlertEvent, d time.Duration) []agent.AlertEvent {
	deadline := time.After(d)
	var evts []agent.AlertEvent
	for {
		select {
		case evt, ok := <-ch:
			if !ok {
				return evts
			}
			evts = append(evts, evt)
		case <-deadline:
			return evts
		}
	}
}

// expectEvent blocks until an event arrives or the test times out.
func expectEvent(t *testing.T, ch <-chan agent.AlertEvent, d time.Duration) agent.AlertEvent {
	t.Helper()
	select {
	case evt, ok := <-ch:
		if !ok {
			t.Fatal("events channel closed before receiving an event")
		}
		return evt
	case <-time.After(d):
		t.Fatalf("timed out waiting for AlertEvent after %v", d)
		return agent.AlertEvent{}
	}
}

// ---------------------------------------------------------------------------
// HexToAddr tests
// ---------------------------------------------------------------------------

func TestHexToAddr_IPv4_Loopback(t *testing.T) {
	// 0100007F = 127.0.0.1 in little-endian; 0050 = port 80
	got, err := agent.HexToAddr("0100007F:0050")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	want := "127.0.0.1:80"
	if got != want {
		t.Errorf("got %q, want %q", got, want)
	}
}

func TestHexToAddr_IPv4_AllZeros(t *testing.T) {
	got, err := agent.HexToAddr("00000000:0000")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	want := "0.0.0.0:0"
	if got != want {
		t.Errorf("got %q, want %q", got, want)
	}
}

func TestHexToAddr_IPv4_HighPort(t *testing.T) {
	// 0100A8C0 = 192.168.0.1 in little-endian: bytes [01 00 A8 C0] → reversed → C0.A8.00.01
	// Port 0x01BB = 443
	got, err := agent.HexToAddr("0100A8C0:01BB")
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	want := "192.168.0.1:443"
	if got != want {
		t.Errorf("got %q, want %q", got, want)
	}
}

func TestHexToAddr_InvalidFormat_NoColon(t *testing.T) {
	_, err := agent.HexToAddr("0100007F0050")
	if err == nil {
		t.Fatal("expected error for input without colon, got nil")
	}
}

func TestHexToAddr_InvalidFormat_BadPort(t *testing.T) {
	_, err := agent.HexToAddr("0100007F:ZZZZ")
	if err == nil {
		t.Fatal("expected error for invalid port hex, got nil")
	}
}

func TestHexToAddr_InvalidFormat_UnknownIPLength(t *testing.T) {
	// 6-char hex is neither 8 (IPv4) nor 32 (IPv6)
	_, err := agent.HexToAddr("010000:0050")
	if err == nil {
		t.Fatal("expected error for unknown IP hex length, got nil")
	}
}

// ---------------------------------------------------------------------------
// ParseProcNetFile tests
// ---------------------------------------------------------------------------

func TestParseProcNetFile_EstablishedConnections(t *testing.T) {
	// Three entries:
	//   line 1 (sl=0): ESTABLISHED (state=01), non-zero remote → included
	//   line 2 (sl=1): LISTEN (state=0A)                       → excluded
	//   line 3 (sl=2): ESTABLISHED but remote is all zeros     → excluded
	content := `  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 901F0000:1F90 0101A8C0:D1E0 01 00000000:00000000 00:00000000 00000000     0        0 12345 1 0000000000000000 100 0 0 10 0
   1: 00000000:1F90 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 12346 1 0000000000000000 100 0 0 10 0
   2: 901F0000:1F90 00000000:0000 01 00000000:00000000 00:00000000 00000000     0        0 12347 1 0000000000000000 100 0 0 10 0
`
	dir := t.TempDir()
	path := filepath.Join(dir, "tcp")
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatalf("writing temp file: %v", err)
	}

	conns, err := agent.ParseProcNetFile(path, "tcp")
	if err != nil {
		t.Fatalf("ParseProcNetFile: %v", err)
	}
	if len(conns) != 1 {
		t.Fatalf("got %d connections, want 1; conns=%+v", len(conns), conns)
	}
	if conns[0].Protocol != "tcp" {
		t.Errorf("protocol = %q, want %q", conns[0].Protocol, "tcp")
	}
}

func TestParseProcNetFile_HeaderOnly(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "tcp")
	if err := os.WriteFile(path, []byte("  sl  local_address rem_address   st\n"), 0o644); err != nil {
		t.Fatalf("writing temp file: %v", err)
	}

	conns, err := agent.ParseProcNetFile(path, "tcp")
	if err != nil {
		t.Fatalf("ParseProcNetFile: %v", err)
	}
	if len(conns) != 0 {
		t.Errorf("got %d connections for header-only file, want 0", len(conns))
	}
}

func TestParseProcNetFile_NonExistentFile(t *testing.T) {
	_, err := agent.ParseProcNetFile("/nonexistent/path/tcp", "tcp")
	if err == nil {
		t.Fatal("expected error for non-existent file, got nil")
	}
}

// ---------------------------------------------------------------------------
// NewNetworkWatcher validation tests
// ---------------------------------------------------------------------------

func TestNewNetworkWatcher_RejectsInvalidPort(t *testing.T) {
	cases := []struct {
		name   string
		target string
	}{
		{"non-numeric", "abc"},
		{"zero", "0"},
		{"too-large", "99999"},
		{"negative", "-1"},
		{"empty", ""},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			_, err := agent.NewNetworkWatcher(
				[]config.TripwireRule{mkRule("bad", tc.target, "WARN")},
				silentLogger(),
				100*time.Millisecond,
			)
			if err == nil {
				t.Fatalf("expected error for port target %q, got nil", tc.target)
			}
		})
	}
}

func TestNewNetworkWatcher_AcceptsValidPorts(t *testing.T) {
	for _, port := range []string{"1", "80", "443", "8080", "65535"} {
		t.Run(port, func(t *testing.T) {
			w, err := agent.NewNetworkWatcher(
				[]config.TripwireRule{mkRule("rule", port, "WARN")},
				silentLogger(),
				100*time.Millisecond,
			)
			if err != nil {
				t.Fatalf("unexpected error for port %q: %v", port, err)
			}
			if w == nil {
				t.Fatal("got nil watcher")
			}
		})
	}
}

func TestNewNetworkWatcher_IgnoresNonNetworkRules(t *testing.T) {
	rules := []config.TripwireRule{
		{Name: "file-rule", Type: "FILE", Target: "/etc/passwd", Severity: "WARN"},
		{Name: "proc-rule", Type: "PROCESS", Target: "nc", Severity: "CRITICAL"},
		{Name: "net-rule", Type: "NETWORK", Target: "22", Severity: "CRITICAL"},
	}
	w, err := agent.NewNetworkWatcher(rules, silentLogger(), 100*time.Millisecond)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if w == nil {
		t.Fatal("got nil watcher")
	}
}

// ---------------------------------------------------------------------------
// Watcher interface compliance
// ---------------------------------------------------------------------------

func TestNetworkWatcher_ImplementsWatcherInterface(t *testing.T) {
	w, err := agent.NewNetworkWatcher(
		[]config.TripwireRule{mkRule("ssh-watch", "22", "CRITICAL")},
		silentLogger(),
		100*time.Millisecond,
	)
	if err != nil {
		t.Fatalf("NewNetworkWatcher: %v", err)
	}
	// Static interface check.
	var _ agent.Watcher = w
}

// ---------------------------------------------------------------------------
// Lifecycle tests
// ---------------------------------------------------------------------------

func TestNetworkWatcher_StartStop_NoRules(t *testing.T) {
	// With no NETWORK rules the events channel should be closed immediately
	// after Start (the goroutine exits right away).
	w, err := agent.NewNetworkWatcher(nil, silentLogger(), 50*time.Millisecond)
	if err != nil {
		t.Fatalf("NewNetworkWatcher: %v", err)
	}

	if err := w.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}

	select {
	case _, ok := <-w.Events():
		if ok {
			t.Fatal("expected closed events channel for no-rules watcher, got data")
		}
	case <-time.After(500 * time.Millisecond):
		t.Fatal("timed out waiting for events channel to close (no-rules case)")
	}

	w.Stop() // must not block
}

func TestNetworkWatcher_StopIsIdempotent(t *testing.T) {
	w, err := agent.NewNetworkWatcher(nil, silentLogger(), 50*time.Millisecond)
	if err != nil {
		t.Fatalf("NewNetworkWatcher: %v", err)
	}
	if err := w.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}

	w.Stop()
	w.Stop() // second call must not panic or deadlock
}

// ---------------------------------------------------------------------------
// Event emission tests with injected ProcReader
// ---------------------------------------------------------------------------

// TestNetworkWatcher_EmitsEventOnNewConnection verifies that a new TCP
// connection on a monitored port triggers an AlertEvent with correct fields.
func TestNetworkWatcher_EmitsEventOnNewConnection(t *testing.T) {
	call := 0
	reader := agent.ProcReader(func() (map[agent.ConnKey]struct{}, error) {
		call++
		if call == 1 {
			// First poll: no connections.
			return map[agent.ConnKey]struct{}{}, nil
		}
		// Second poll onward: new connection on port 8080.
		return map[agent.ConnKey]struct{}{
			{LocalAddr: "0.0.0.0:8080", RemoteAddr: "10.0.0.1:54321", Protocol: "tcp"}: {},
		}, nil
	})

	w, err := agent.NewNetworkWatcherWithReader(
		[]config.TripwireRule{mkRule("http-watch", "8080", "WARN")},
		silentLogger(),
		20*time.Millisecond,
		reader,
	)
	if err != nil {
		t.Fatalf("NewNetworkWatcherWithReader: %v", err)
	}

	if err := w.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}
	defer w.Stop()

	evt := expectEvent(t, w.Events(), 2*time.Second)

	if evt.TripwireType != "NETWORK" {
		t.Errorf("TripwireType = %q, want %q", evt.TripwireType, "NETWORK")
	}
	if evt.RuleName != "http-watch" {
		t.Errorf("RuleName = %q, want %q", evt.RuleName, "http-watch")
	}
	if evt.Severity != "WARN" {
		t.Errorf("Severity = %q, want %q", evt.Severity, "WARN")
	}
	if evt.Timestamp.IsZero() {
		t.Error("Timestamp must not be zero")
	}
	if evt.Detail["local_addr"] != "0.0.0.0:8080" {
		t.Errorf("Detail[local_addr] = %v, want %q", evt.Detail["local_addr"], "0.0.0.0:8080")
	}
	if evt.Detail["remote_addr"] != "10.0.0.1:54321" {
		t.Errorf("Detail[remote_addr] = %v, want %q", evt.Detail["remote_addr"], "10.0.0.1:54321")
	}
	if evt.Detail["protocol"] != "tcp" {
		t.Errorf("Detail[protocol] = %v, want %q", evt.Detail["protocol"], "tcp")
	}
}

// TestNetworkWatcher_NoDuplicateEventsForPersistentConnections verifies that
// a connection present in consecutive polls triggers only one event.
func TestNetworkWatcher_NoDuplicateEventsForPersistentConnections(t *testing.T) {
	existing := agent.ConnKey{
		LocalAddr:  "0.0.0.0:22",
		RemoteAddr: "192.168.1.50:60000",
		Protocol:   "tcp",
	}

	reader := agent.ProcReader(func() (map[agent.ConnKey]struct{}, error) {
		return map[agent.ConnKey]struct{}{existing: {}}, nil
	})

	w, err := agent.NewNetworkWatcherWithReader(
		[]config.TripwireRule{mkRule("ssh-watch", "22", "CRITICAL")},
		silentLogger(),
		20*time.Millisecond,
		reader,
	)
	if err != nil {
		t.Fatalf("NewNetworkWatcherWithReader: %v", err)
	}

	if err := w.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}

	// Run for several poll cycles.
	evts := drainFor(w.Events(), 200*time.Millisecond)
	w.Stop()

	// First poll sees the connection as new → 1 event; subsequent polls see it
	// as already-seen → no duplicates.
	if len(evts) != 1 {
		t.Errorf("got %d events, want exactly 1 (connection seen once)", len(evts))
	}
}

// TestNetworkWatcher_IgnoresUnmonitoredPorts verifies that connections on
// ports not covered by any rule do not produce events.
func TestNetworkWatcher_IgnoresUnmonitoredPorts(t *testing.T) {
	call := 0
	reader := agent.ProcReader(func() (map[agent.ConnKey]struct{}, error) {
		call++
		if call == 1 {
			return map[agent.ConnKey]struct{}{}, nil
		}
		// Connection on port 9999, which is not in any rule.
		return map[agent.ConnKey]struct{}{
			{LocalAddr: "0.0.0.0:9999", RemoteAddr: "10.0.0.1:55000", Protocol: "tcp"}: {},
		}, nil
	})

	w, err := agent.NewNetworkWatcherWithReader(
		[]config.TripwireRule{mkRule("ssh-watch", "22", "CRITICAL")},
		silentLogger(),
		20*time.Millisecond,
		reader,
	)
	if err != nil {
		t.Fatalf("NewNetworkWatcherWithReader: %v", err)
	}

	if err := w.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}

	evts := drainFor(w.Events(), 200*time.Millisecond)
	w.Stop()

	if len(evts) != 0 {
		t.Errorf("got %d events for unmonitored port 9999, want 0", len(evts))
	}
}

// TestNetworkWatcher_MultipleRulesMatchSamePort verifies that multiple rules
// targeting the same port each produce their own event for a single connection.
func TestNetworkWatcher_MultipleRulesMatchSamePort(t *testing.T) {
	call := 0
	reader := agent.ProcReader(func() (map[agent.ConnKey]struct{}, error) {
		call++
		if call == 1 {
			return map[agent.ConnKey]struct{}{}, nil
		}
		return map[agent.ConnKey]struct{}{
			{LocalAddr: "0.0.0.0:80", RemoteAddr: "10.0.0.2:11111", Protocol: "tcp"}: {},
		}, nil
	})

	rules := []config.TripwireRule{
		{Name: "http-watch", Type: "NETWORK", Target: "80", Severity: "WARN"},
		{Name: "http-strict", Type: "NETWORK", Target: "80", Severity: "CRITICAL"},
	}

	w, err := agent.NewNetworkWatcherWithReader(rules, silentLogger(), 20*time.Millisecond, reader)
	if err != nil {
		t.Fatalf("NewNetworkWatcherWithReader: %v", err)
	}

	if err := w.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}
	defer w.Stop()

	// Collect until we have ≥ 2 events or time out.
	var evts []agent.AlertEvent
	deadline := time.After(2 * time.Second)
collect:
	for {
		select {
		case evt, ok := <-w.Events():
			if !ok {
				break collect
			}
			evts = append(evts, evt)
			if len(evts) >= 2 {
				break collect
			}
		case <-deadline:
			break collect
		}
	}

	if len(evts) < 2 {
		t.Errorf("got %d events, want at least 2 (one per matching rule)", len(evts))
	}
}

// TestNetworkWatcher_ReaderErrorDoesNotCrash verifies that a transient error
// from the ProcReader is tolerated and monitoring resumes on the next poll.
func TestNetworkWatcher_ReaderErrorDoesNotCrash(t *testing.T) {
	call := 0
	goodConn := agent.ConnKey{
		LocalAddr:  "0.0.0.0:8080",
		RemoteAddr: "10.0.0.1:12345",
		Protocol:   "tcp",
	}

	reader := agent.ProcReader(func() (map[agent.ConnKey]struct{}, error) {
		call++
		switch call {
		case 1:
			return map[agent.ConnKey]struct{}{}, nil
		case 2:
			return nil, errors.New("transient read error")
		default:
			return map[agent.ConnKey]struct{}{goodConn: {}}, nil
		}
	})

	w, err := agent.NewNetworkWatcherWithReader(
		[]config.TripwireRule{mkRule("http-watch", "8080", "WARN")},
		silentLogger(),
		20*time.Millisecond,
		reader,
	)
	if err != nil {
		t.Fatalf("NewNetworkWatcherWithReader: %v", err)
	}

	if err := w.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}
	defer w.Stop()

	// An event should still arrive from poll 3+ (after the error in poll 2).
	expectEvent(t, w.Events(), 2*time.Second)
}
