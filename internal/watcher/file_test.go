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

func noopLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelError + 10}))
}

// fileRule is a convenience constructor for a single FILE-type TripwireRule.
func fileRule(name, target, severity string) config.TripwireRule {
	return config.TripwireRule{
		Name:     name,
		Type:     "FILE",
		Target:   target,
		Severity: severity,
	}
}

// waitForEvent reads one AlertEvent from ch within timeout. It returns the
// event and true on success, or the zero value and false if no event arrives
// within the deadline.
func waitForEvent(ch <-chan agent.AlertEvent, timeout time.Duration) (agent.AlertEvent, bool) {
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

// startWatcher creates a FileWatcher with the given rules, starts it,
// waits for the initial snapshot to be taken, and returns the watcher.
// The poll interval is shortened to 50 ms for faster test feedback.
func startWatcher(t *testing.T, rules []config.TripwireRule) *watcher.FileWatcher {
	t.Helper()
	fw := watcher.NewFileWatcher(rules, noopLogger(), 50*time.Millisecond)
	if err := fw.Start(context.Background()); err != nil {
		t.Fatalf("FileWatcher.Start: %v", err)
	}
	// Wait for the initial snapshot so subsequent file operations are detected
	// as changes, not as the initial state.
	select {
	case <-fw.Ready():
	case <-time.After(2 * time.Second):
		t.Fatal("FileWatcher.Ready() never fired")
	}
	return fw
}

// ---------------------------------------------------------------------------
// Unit tests
// ---------------------------------------------------------------------------

// TestFileWatcher_StartStop verifies that Start and Stop complete without error
// and that the Events channel is closed after Stop returns.
func TestFileWatcher_StartStop(t *testing.T) {
	dir := t.TempDir()
	fw := watcher.NewFileWatcher(
		[]config.TripwireRule{fileRule("test-rule", dir, "INFO")},
		noopLogger(),
		50*time.Millisecond,
	)

	if err := fw.Start(context.Background()); err != nil {
		t.Fatalf("Start: unexpected error: %v", err)
	}

	// Stop should return without hanging.
	done := make(chan struct{})
	go func() {
		fw.Stop()
		close(done)
	}()

	select {
	case <-done:
	case <-time.After(3 * time.Second):
		t.Fatal("Stop did not return within 3 seconds")
	}

	// Events channel must be closed after Stop.
	select {
	case _, ok := <-fw.Events():
		if ok {
			t.Error("expected Events channel to be closed after Stop")
		}
	case <-time.After(time.Second):
		t.Error("Events channel was not closed after Stop")
	}
}

// TestFileWatcher_StopIsIdempotent verifies that calling Stop more than once
// does not panic or deadlock.
func TestFileWatcher_StopIsIdempotent(t *testing.T) {
	dir := t.TempDir()
	fw := startWatcher(t, []config.TripwireRule{fileRule("rule", dir, "WARN")})

	fw.Stop()
	fw.Stop() // must not panic
}

// TestFileWatcher_IgnoresNonFileRules verifies that rules with types other
// than "FILE" are silently ignored and do not cause Start to return an error.
func TestFileWatcher_IgnoresNonFileRules(t *testing.T) {
	rules := []config.TripwireRule{
		{Name: "net-rule", Type: "NETWORK", Target: "8080", Severity: "WARN"},
		{Name: "proc-rule", Type: "PROCESS", Target: "nc", Severity: "CRITICAL"},
	}
	fw := watcher.NewFileWatcher(rules, noopLogger(), 50*time.Millisecond)
	if err := fw.Start(context.Background()); err != nil {
		t.Fatalf("Start: unexpected error: %v", err)
	}
	fw.Stop()
}

// TestFileWatcher_DetectsFileCreate verifies that creating a new file in a
// watched directory emits a "create" AlertEvent with the correct metadata.
func TestFileWatcher_DetectsFileCreate(t *testing.T) {
	dir := t.TempDir()
	fw := startWatcher(t, []config.TripwireRule{fileRule("dir-watch", dir, "WARN")})
	defer fw.Stop()

	newFile := filepath.Join(dir, "canary.txt")
	if err := os.WriteFile(newFile, []byte("trip"), 0600); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}

	evt, ok := waitForEvent(fw.Events(), 2*time.Second)
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

// TestFileWatcher_DetectsFileWrite verifies that modifying an existing file
// in a watched directory emits a "write" AlertEvent.
func TestFileWatcher_DetectsFileWrite(t *testing.T) {
	dir := t.TempDir()

	// Pre-create the file so the initial snapshot includes it.
	targetFile := filepath.Join(dir, "watched.txt")
	if err := os.WriteFile(targetFile, []byte("initial"), 0600); err != nil {
		t.Fatalf("WriteFile (setup): %v", err)
	}

	fw := startWatcher(t, []config.TripwireRule{fileRule("dir-watch", dir, "CRITICAL")})
	defer fw.Stop()

	// Sleep briefly to ensure the OS advances the file mtime on the next write.
	time.Sleep(10 * time.Millisecond)

	if err := os.WriteFile(targetFile, []byte("modified"), 0600); err != nil {
		t.Fatalf("WriteFile (modify): %v", err)
	}

	evt, ok := waitForEvent(fw.Events(), 2*time.Second)
	if !ok {
		t.Fatal("no AlertEvent received within 2 seconds after file write")
	}

	if evt.Detail["operation"] != "write" {
		t.Errorf("operation = %v, want %q", evt.Detail["operation"], "write")
	}
	if evt.Detail["path"] != targetFile {
		t.Errorf("path = %v, want %q", evt.Detail["path"], targetFile)
	}
	if evt.Severity != "CRITICAL" {
		t.Errorf("Severity = %q, want %q", evt.Severity, "CRITICAL")
	}
}

// TestFileWatcher_DetectsFileDelete verifies that removing a file from a
// watched directory emits a "delete" AlertEvent.
func TestFileWatcher_DetectsFileDelete(t *testing.T) {
	dir := t.TempDir()

	targetFile := filepath.Join(dir, "ephemeral.txt")
	if err := os.WriteFile(targetFile, []byte("data"), 0600); err != nil {
		t.Fatalf("WriteFile (setup): %v", err)
	}

	fw := startWatcher(t, []config.TripwireRule{fileRule("dir-watch", dir, "INFO")})
	defer fw.Stop()

	if err := os.Remove(targetFile); err != nil {
		t.Fatalf("Remove: %v", err)
	}

	evt, ok := waitForEvent(fw.Events(), 2*time.Second)
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

// TestFileWatcher_WatchesSingleFile verifies that a rule targeting a specific
// file (not a directory) emits an event when that file is modified.
func TestFileWatcher_WatchesSingleFile(t *testing.T) {
	dir := t.TempDir()
	targetFile := filepath.Join(dir, "secrets.txt")

	if err := os.WriteFile(targetFile, []byte("original"), 0600); err != nil {
		t.Fatalf("WriteFile (setup): %v", err)
	}

	fw := startWatcher(t, []config.TripwireRule{fileRule("single-file-watch", targetFile, "CRITICAL")})
	defer fw.Stop()

	time.Sleep(10 * time.Millisecond)

	if err := os.WriteFile(targetFile, []byte("tampered"), 0600); err != nil {
		t.Fatalf("WriteFile (modify): %v", err)
	}

	evt, ok := waitForEvent(fw.Events(), 2*time.Second)
	if !ok {
		t.Fatal("no AlertEvent received within 2 seconds after single-file write")
	}

	if evt.RuleName != "single-file-watch" {
		t.Errorf("RuleName = %q, want %q", evt.RuleName, "single-file-watch")
	}
	if evt.Detail["path"] != targetFile {
		t.Errorf("path = %v, want %q", evt.Detail["path"], targetFile)
	}
}

// TestFileWatcher_ReadyChannelClosedAfterStart verifies that the Ready channel
// is closed shortly after Start is called, confirming the initial snapshot
// guard works correctly.
func TestFileWatcher_ReadyChannelClosedAfterStart(t *testing.T) {
	dir := t.TempDir()
	fw := watcher.NewFileWatcher(
		[]config.TripwireRule{fileRule("rule", dir, "INFO")},
		noopLogger(),
		50*time.Millisecond,
	)
	if err := fw.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}
	defer fw.Stop()

	select {
	case <-fw.Ready():
		// success
	case <-time.After(time.Second):
		t.Fatal("Ready() channel was not closed within 1 second of Start")
	}
}

// ---------------------------------------------------------------------------
// End-to-end SLA test
// ---------------------------------------------------------------------------

// capturingTransport is a minimal agent.Transport implementation that records
// every event forwarded to it via a buffered channel for test inspection.
type capturingTransport struct {
	received chan agent.AlertEvent
}

func (t *capturingTransport) Start(_ context.Context) error { return nil }
func (t *capturingTransport) Stop()                         {}
func (t *capturingTransport) Send(_ context.Context, evt agent.AlertEvent) error {
	select {
	case t.received <- evt:
	default:
	}
	return nil
}

// minimalConfig returns a config.Config with the mandatory fields set. The TLS
// paths are intentionally non-existent because the test does not start a real
// agent binary that would validate them.
func minimalConfig(rules []config.TripwireRule) *config.Config {
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

// TestE2E_FileAlertEmission_WithinSLA is the primary acceptance test for the
// 5-second alert SLA defined in PRD Goal G-2 and User Story US-01.
//
// The test wires a real FileWatcher into the Agent orchestrator alongside a
// fake transport. It then:
//
//  1. Creates a temporary directory and configures a FILE tripwire rule.
//  2. Starts the Agent (which starts the FileWatcher).
//  3. Waits for the FileWatcher's initial snapshot to complete.
//  4. Records a start timestamp.
//  5. Writes a new file to the watched directory.
//  6. Asserts that a correctly-formed AlertEvent reaches the transport
//     within the 5-second SLA.
//
// The 100 ms poll interval means detection typically occurs within 200 ms,
// giving >25× margin against the 5-second budget.
func TestE2E_FileAlertEmission_WithinSLA(t *testing.T) {
	const sla = 5 * time.Second

	// ── Setup ──────────────────────────────────────────────────────────────
	dir := t.TempDir()
	rule := fileRule("sensitive-dir-watch", dir, "CRITICAL")

	fw := watcher.NewFileWatcher(
		[]config.TripwireRule{rule},
		noopLogger(),
		50*time.Millisecond, // fast polling for deterministic SLA measurement
	)

	tr := &capturingTransport{received: make(chan agent.AlertEvent, 4)}

	ag := agent.New(
		minimalConfig([]config.TripwireRule{rule}),
		noopLogger(),
		agent.WithWatchers(fw),
		agent.WithTransport(tr),
	)

	// ── Start ──────────────────────────────────────────────────────────────
	ctx := context.Background()
	if err := ag.Start(ctx); err != nil {
		t.Fatalf("Agent.Start: %v", err)
	}
	defer ag.Stop()

	// Wait for the FileWatcher to take its initial snapshot. This guarantees
	// that the file we create below is seen as a new entry, not pre-existing.
	select {
	case <-fw.Ready():
	case <-time.After(2 * time.Second):
		t.Fatal("FileWatcher.Ready() timed out")
	}

	// ── Trigger ────────────────────────────────────────────────────────────
	start := time.Now()

	triggerFile := filepath.Join(dir, "tripwire-canary.txt")
	if err := os.WriteFile(triggerFile, []byte("unauthorized access"), 0600); err != nil {
		t.Fatalf("WriteFile (trigger): %v", err)
	}

	// ── Assert: alert arrives within SLA ───────────────────────────────────
	select {
	case evt := <-tr.received:
		elapsed := time.Since(start)
		t.Logf("Alert received in %v (SLA: %v)", elapsed, sla)

		if elapsed > sla {
			t.Errorf("alert emission latency %v exceeded %v SLA", elapsed, sla)
		}

		// Verify the event is correctly formed.
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
		if evt.Detail["operation"] != "create" {
			t.Errorf("Detail[operation] = %v, want %q", evt.Detail["operation"], "create")
		}
		if evt.Timestamp.IsZero() {
			t.Error("Timestamp must be set")
		}

	case <-time.After(sla):
		t.Errorf("no alert received within %v SLA after file creation", sla)
	}
}

// TestE2E_FileAlertEmission_MultipleEvents verifies that successive file
// operations each produce an alert and all arrive within the SLA.
func TestE2E_FileAlertEmission_MultipleEvents(t *testing.T) {
	const sla = 5 * time.Second

	dir := t.TempDir()
	rule := fileRule("multi-event-watch", dir, "WARN")

	fw := watcher.NewFileWatcher(
		[]config.TripwireRule{rule},
		noopLogger(),
		50*time.Millisecond,
	)

	tr := &capturingTransport{received: make(chan agent.AlertEvent, 16)}

	ag := agent.New(
		minimalConfig([]config.TripwireRule{rule}),
		noopLogger(),
		agent.WithWatchers(fw),
		agent.WithTransport(tr),
	)

	ctx := context.Background()
	if err := ag.Start(ctx); err != nil {
		t.Fatalf("Agent.Start: %v", err)
	}
	defer ag.Stop()

	<-fw.Ready()

	// Create two files to generate two separate alerts.
	files := []string{
		filepath.Join(dir, "file-a.txt"),
		filepath.Join(dir, "file-b.txt"),
	}
	start := time.Now()
	for _, f := range files {
		if err := os.WriteFile(f, []byte("data"), 0600); err != nil {
			t.Fatalf("WriteFile %q: %v", f, err)
		}
	}

	received := make([]agent.AlertEvent, 0, len(files))
	timeout := time.After(sla)
	for len(received) < len(files) {
		select {
		case evt := <-tr.received:
			received = append(received, evt)
		case <-timeout:
			t.Errorf("only received %d/%d alerts within %v SLA", len(received), len(files), sla)
			return
		}
	}

	elapsed := time.Since(start)
	t.Logf("All %d alerts received in %v (SLA: %v)", len(received), elapsed, sla)

	if elapsed > sla {
		t.Errorf("total alert latency %v exceeded %v SLA", elapsed, sla)
	}
}

// TestE2E_FileAlertEmission_AgentStop verifies that stopping the agent while
// the FileWatcher is active does not panic or deadlock.
func TestE2E_FileAlertEmission_AgentStop(t *testing.T) {
	dir := t.TempDir()
	rule := fileRule("stop-test", dir, "INFO")

	fw := watcher.NewFileWatcher(
		[]config.TripwireRule{rule},
		noopLogger(),
		50*time.Millisecond,
	)

	ag := agent.New(
		minimalConfig([]config.TripwireRule{rule}),
		noopLogger(),
		agent.WithWatchers(fw),
	)

	ctx := context.Background()
	if err := ag.Start(ctx); err != nil {
		t.Fatalf("Agent.Start: %v", err)
	}

	<-fw.Ready()

	// Stop must complete without hanging.
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
