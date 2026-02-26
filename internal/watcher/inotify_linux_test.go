//go:build linux

package watcher_test

import (
	"context"
	"log/slog"
	"os"
	"path/filepath"
	"testing"
	"time"

	"github.com/tripwire/agent/internal/agent"
	"github.com/tripwire/agent/internal/config"
	"github.com/tripwire/agent/internal/watcher"
)

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// inoLogger returns a logger that discards all messages below error+10,
// keeping test output clean.
func inoLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelError + 10}))
}

// inoFileRule is a convenience constructor for a FILE-type TripwireRule.
func inoFileRule(name, target, severity string) config.TripwireRule {
	return config.TripwireRule{
		Name:     name,
		Type:     "FILE",
		Target:   target,
		Severity: severity,
	}
}

// startInotifyWatcher creates an InotifyWatcher, starts it, waits for the
// initial watches to be registered via Ready(), and returns the watcher.
func startInotifyWatcher(t *testing.T, rules []config.TripwireRule) *watcher.InotifyWatcher {
	t.Helper()
	iw, err := watcher.NewInotifyWatcher(rules, inoLogger())
	if err != nil {
		t.Fatalf("NewInotifyWatcher: %v", err)
	}
	if err := iw.Start(context.Background()); err != nil {
		t.Fatalf("InotifyWatcher.Start: %v", err)
	}
	select {
	case <-iw.Ready():
	case <-time.After(2 * time.Second):
		t.Fatal("InotifyWatcher.Ready() never fired")
	}
	return iw
}

// waitInotifyEvent reads one AlertEvent from ch within timeout.
func waitInotifyEvent(ch <-chan agent.AlertEvent, timeout time.Duration) (agent.AlertEvent, bool) {
	select {
	case evt, ok := <-ch:
		if !ok {
			return agent.AlertEvent{}, false
		}
		return evt, true
	case <-time.After(timeout):
		return agent.AlertEvent{}, false
	}
}

// ---------------------------------------------------------------------------
// Unit tests
// ---------------------------------------------------------------------------

// TestInotifyWatcher_StartStop verifies that Start and Stop complete without
// error and that the Events channel is closed after Stop returns.
func TestInotifyWatcher_StartStop(t *testing.T) {
	dir := t.TempDir()
	iw, err := watcher.NewInotifyWatcher(
		[]config.TripwireRule{inoFileRule("rule", dir, "INFO")},
		inoLogger(),
	)
	if err != nil {
		t.Fatalf("NewInotifyWatcher: %v", err)
	}

	if err := iw.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}

	done := make(chan struct{})
	go func() {
		iw.Stop()
		close(done)
	}()

	select {
	case <-done:
	case <-time.After(3 * time.Second):
		t.Fatal("Stop did not return within 3 seconds")
	}

	// Events channel must be closed after Stop.
	select {
	case _, ok := <-iw.Events():
		if ok {
			t.Error("expected Events channel to be closed after Stop")
		}
	case <-time.After(time.Second):
		t.Error("Events channel was not closed after Stop")
	}
}

// TestInotifyWatcher_StopIsIdempotent verifies that calling Stop more than
// once does not panic or deadlock.
func TestInotifyWatcher_StopIsIdempotent(t *testing.T) {
	dir := t.TempDir()
	iw := startInotifyWatcher(t, []config.TripwireRule{inoFileRule("rule", dir, "WARN")})

	iw.Stop()
	iw.Stop() // must not panic
}

// TestInotifyWatcher_IgnoresNonFileRules verifies that non-FILE rules are
// silently ignored and do not prevent successful startup.
func TestInotifyWatcher_IgnoresNonFileRules(t *testing.T) {
	rules := []config.TripwireRule{
		{Name: "net-rule", Type: "NETWORK", Target: "8080", Severity: "WARN"},
		{Name: "proc-rule", Type: "PROCESS", Target: "nc", Severity: "CRITICAL"},
	}
	iw, err := watcher.NewInotifyWatcher(rules, inoLogger())
	if err != nil {
		t.Fatalf("NewInotifyWatcher: %v", err)
	}
	if err := iw.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}
	iw.Stop()
}

// TestInotifyWatcher_ReadyChannelClosedAfterStart verifies that the Ready
// channel is closed shortly after Start, confirming watches are established.
func TestInotifyWatcher_ReadyChannelClosedAfterStart(t *testing.T) {
	dir := t.TempDir()
	iw, err := watcher.NewInotifyWatcher(
		[]config.TripwireRule{inoFileRule("rule", dir, "INFO")},
		inoLogger(),
	)
	if err != nil {
		t.Fatalf("NewInotifyWatcher: %v", err)
	}
	if err := iw.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}
	defer iw.Stop()

	select {
	case <-iw.Ready():
		// success
	case <-time.After(time.Second):
		t.Fatal("Ready() channel was not closed within 1 second of Start")
	}
}

// TestInotifyWatcher_DetectsFileCreate verifies that creating a new file in a
// watched directory emits a "create" AlertEvent with correct metadata.
func TestInotifyWatcher_DetectsFileCreate(t *testing.T) {
	dir := t.TempDir()
	iw := startInotifyWatcher(t, []config.TripwireRule{inoFileRule("dir-watch", dir, "WARN")})
	defer iw.Stop()

	newFile := filepath.Join(dir, "canary.txt")
	if err := os.WriteFile(newFile, []byte("trip"), 0600); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}

	// The first event from creating a new file should be "create" (IN_CREATE),
	// which fires before IN_CLOSE_WRITE.
	evt, ok := waitInotifyEvent(iw.Events(), 2*time.Second)
	if !ok {
		t.Fatal("no AlertEvent received within 2 seconds after file create")
	}

	if evt.TripwireType != "FILE" {
		t.Errorf("TripwireType = %q, want %q", evt.TripwireType, "FILE")
	}
	if evt.RuleName != "dir-watch" {
		t.Errorf("RuleName = %q, want %q", evt.RuleName, "dir-watch")
	}
	if evt.Severity != "WARN" {
		t.Errorf("Severity = %q, want %q", evt.Severity, "WARN")
	}
	if evt.Detail["path"] != newFile {
		t.Errorf("Detail[path] = %v, want %q", evt.Detail["path"], newFile)
	}
	if evt.Detail["operation"] != "create" {
		t.Errorf("Detail[operation] = %v, want %q", evt.Detail["operation"], "create")
	}
	if evt.Timestamp.IsZero() {
		t.Error("Timestamp must not be zero")
	}
}

// TestInotifyWatcher_DetectsFileWrite verifies that modifying an existing
// file in a watched directory emits a "write" AlertEvent.
func TestInotifyWatcher_DetectsFileWrite(t *testing.T) {
	dir := t.TempDir()

	// Pre-create the file so the initial state is captured before the watcher
	// starts; only subsequent writes should emit events.
	targetFile := filepath.Join(dir, "watched.txt")
	if err := os.WriteFile(targetFile, []byte("initial"), 0600); err != nil {
		t.Fatalf("WriteFile (setup): %v", err)
	}

	iw := startInotifyWatcher(t, []config.TripwireRule{inoFileRule("dir-watch", dir, "CRITICAL")})
	defer iw.Stop()

	if err := os.WriteFile(targetFile, []byte("modified"), 0600); err != nil {
		t.Fatalf("WriteFile (modify): %v", err)
	}

	// We may get a "create" event if the OS recreates the file (O_TRUNC),
	// followed by a "write" event from IN_CLOSE_WRITE. Drain until we find
	// the "write" event or timeout.
	deadline := time.After(2 * time.Second)
	for {
		select {
		case evt, ok := <-iw.Events():
			if !ok {
				t.Fatal("Events channel closed unexpectedly")
			}
			if evt.Detail["operation"] == "write" {
				if evt.Detail["path"] != targetFile {
					t.Errorf("path = %v, want %q", evt.Detail["path"], targetFile)
				}
				if evt.Severity != "CRITICAL" {
					t.Errorf("Severity = %q, want %q", evt.Severity, "CRITICAL")
				}
				return // test passed
			}
		case <-deadline:
			t.Fatal("no 'write' AlertEvent received within 2 seconds after file write")
		}
	}
}

// TestInotifyWatcher_DetectsFileDelete verifies that removing a file from a
// watched directory emits a "delete" AlertEvent.
func TestInotifyWatcher_DetectsFileDelete(t *testing.T) {
	dir := t.TempDir()

	targetFile := filepath.Join(dir, "ephemeral.txt")
	if err := os.WriteFile(targetFile, []byte("data"), 0600); err != nil {
		t.Fatalf("WriteFile (setup): %v", err)
	}

	iw := startInotifyWatcher(t, []config.TripwireRule{inoFileRule("dir-watch", dir, "INFO")})
	defer iw.Stop()

	if err := os.Remove(targetFile); err != nil {
		t.Fatalf("Remove: %v", err)
	}

	evt, ok := waitInotifyEvent(iw.Events(), 2*time.Second)
	if !ok {
		t.Fatal("no AlertEvent received within 2 seconds after file delete")
	}

	if evt.Detail["operation"] != "delete" {
		t.Errorf("operation = %v, want %q", evt.Detail["operation"], "delete")
	}
	if evt.Detail["path"] != targetFile {
		t.Errorf("path = %v, want %q", evt.Detail["path"], targetFile)
	}
}

// TestInotifyWatcher_WatchesSingleFile verifies that a rule targeting a
// specific file (not a directory) emits a "write" event when that file is
// modified.
func TestInotifyWatcher_WatchesSingleFile(t *testing.T) {
	dir := t.TempDir()
	targetFile := filepath.Join(dir, "secrets.txt")

	if err := os.WriteFile(targetFile, []byte("original"), 0600); err != nil {
		t.Fatalf("WriteFile (setup): %v", err)
	}

	iw := startInotifyWatcher(t, []config.TripwireRule{inoFileRule("single-file-watch", targetFile, "CRITICAL")})
	defer iw.Stop()

	if err := os.WriteFile(targetFile, []byte("tampered"), 0600); err != nil {
		t.Fatalf("WriteFile (modify): %v", err)
	}

	// For single-file watches we watch for IN_CLOSE_WRITE which yields "write".
	// Since os.WriteFile truncates + writes + closes, we expect a "write" event.
	deadline := time.After(2 * time.Second)
	for {
		select {
		case evt, ok := <-iw.Events():
			if !ok {
				t.Fatal("Events channel closed unexpectedly")
			}
			if evt.Detail["operation"] == "write" || evt.Detail["operation"] == "create" {
				if evt.RuleName != "single-file-watch" {
					t.Errorf("RuleName = %q, want %q", evt.RuleName, "single-file-watch")
				}
				if evt.Detail["path"] != targetFile {
					t.Errorf("path = %v, want %q", evt.Detail["path"], targetFile)
				}
				return // test passed
			}
		case <-deadline:
			t.Fatal("no AlertEvent received within 2 seconds after single-file write")
		}
	}
}

// ---------------------------------------------------------------------------
// End-to-end SLA test
// ---------------------------------------------------------------------------

// TestInotifyE2E_FileAlertEmission_WithinSLA is the primary acceptance test
// for the 5-second alert SLA using the inotify-based backend.
//
// It wires a real InotifyWatcher into the Agent orchestrator alongside a fake
// transport, triggers a file creation, and asserts that a correctly-formed
// AlertEvent reaches the transport within the 5-second SLA.
//
// Because inotify delivers events from the kernel without polling, typical
// observed latency is well under 10 ms — >500× margin against the 5-second
// budget.
func TestInotifyE2E_FileAlertEmission_WithinSLA(t *testing.T) {
	const sla = 5 * time.Second

	dir := t.TempDir()
	rule := inoFileRule("sensitive-dir-watch", dir, "CRITICAL")

	iw, err := watcher.NewInotifyWatcher(
		[]config.TripwireRule{rule},
		inoLogger(),
	)
	if err != nil {
		t.Fatalf("NewInotifyWatcher: %v", err)
	}

	tr := &inoCapturingTransport{received: make(chan agent.AlertEvent, 4)}

	ag := agent.New(
		inoMinimalConfig([]config.TripwireRule{rule}),
		inoLogger(),
		agent.WithWatchers(iw),
		agent.WithTransport(tr),
	)

	ctx := context.Background()
	if err := ag.Start(ctx); err != nil {
		t.Fatalf("Agent.Start: %v", err)
	}
	defer ag.Stop()

	// Wait for watches to be registered before triggering the file operation.
	select {
	case <-iw.Ready():
	case <-time.After(2 * time.Second):
		t.Fatal("InotifyWatcher.Ready() timed out")
	}

	start := time.Now()

	triggerFile := filepath.Join(dir, "tripwire-canary.txt")
	if err := os.WriteFile(triggerFile, []byte("unauthorized access"), 0600); err != nil {
		t.Fatalf("WriteFile (trigger): %v", err)
	}

	select {
	case evt := <-tr.received:
		elapsed := time.Since(start)
		t.Logf("inotify alert received in %v (SLA: %v)", elapsed, sla)

		if elapsed > sla {
			t.Errorf("alert emission latency %v exceeded %v SLA", elapsed, sla)
		}
		if evt.TripwireType != "FILE" {
			t.Errorf("TripwireType = %q, want %q", evt.TripwireType, "FILE")
		}
		if evt.RuleName != "sensitive-dir-watch" {
			t.Errorf("RuleName = %q, want %q", evt.RuleName, "sensitive-dir-watch")
		}
		if evt.Severity != "CRITICAL" {
			t.Errorf("Severity = %q, want %q", evt.Severity, "CRITICAL")
		}
		if evt.Detail["path"] != triggerFile {
			t.Errorf("Detail[path] = %v, want %q", evt.Detail["path"], triggerFile)
		}
		if evt.Timestamp.IsZero() {
			t.Error("Timestamp must be set")
		}

	case <-time.After(sla):
		t.Errorf("no inotify alert received within %v SLA after file creation", sla)
	}
}

// TestInotifyE2E_AgentStop verifies that stopping the agent while the
// InotifyWatcher is active does not panic or deadlock.
func TestInotifyE2E_AgentStop(t *testing.T) {
	dir := t.TempDir()
	rule := inoFileRule("stop-test", dir, "INFO")

	iw, err := watcher.NewInotifyWatcher([]config.TripwireRule{rule}, inoLogger())
	if err != nil {
		t.Fatalf("NewInotifyWatcher: %v", err)
	}

	ag := agent.New(
		inoMinimalConfig([]config.TripwireRule{rule}),
		inoLogger(),
		agent.WithWatchers(iw),
	)

	ctx := context.Background()
	if err := ag.Start(ctx); err != nil {
		t.Fatalf("Agent.Start: %v", err)
	}

	<-iw.Ready()

	done := make(chan struct{})
	go func() {
		ag.Stop()
		close(done)
	}()

	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("Agent.Stop did not return within 5 seconds")
	}
}

// ---------------------------------------------------------------------------
// Test helpers (transport + config stubs)
// ---------------------------------------------------------------------------

type inoCapturingTransport struct {
	received chan agent.AlertEvent
}

func (t *inoCapturingTransport) Start(_ context.Context) error { return nil }
func (t *inoCapturingTransport) Stop()                         {}
func (t *inoCapturingTransport) Send(_ context.Context, evt agent.AlertEvent) error {
	select {
	case t.received <- evt:
	default:
	}
	return nil
}

func inoMinimalConfig(rules []config.TripwireRule) *config.Config {
	return &config.Config{
		DashboardAddr: "dashboard.example.com:4443",
		TLS: config.TLSConfig{
			CertPath: "/nonexistent/agent.crt",
			KeyPath:  "/nonexistent/agent.key",
			CAPath:   "/nonexistent/ca.crt",
		},
		LogLevel:   "error",
		HealthAddr: "127.0.0.1:0",
		Rules:      rules,
	}
}
