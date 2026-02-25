//go:build darwin

package watcher_test

import (
	"context"
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

// kqueueRule is a convenience constructor for a FILE-type TripwireRule.
func kqueueRule(name, target, severity string) config.TripwireRule {
	return config.TripwireRule{
		Name:     name,
		Type:     "FILE",
		Target:   target,
		Severity: severity,
	}
}

// startKqueueWatcher creates a KqueueWatcher, starts it, waits for Ready(),
// and registers cleanup via t.Cleanup.
func startKqueueWatcher(t *testing.T, rules []config.TripwireRule) *watcher.KqueueWatcher {
	t.Helper()
	kw, err := watcher.NewKqueueWatcher(rules, noopLogger())
	if err != nil {
		t.Fatalf("NewKqueueWatcher: %v", err)
	}
	if err := kw.Start(context.Background()); err != nil {
		t.Fatalf("KqueueWatcher.Start: %v", err)
	}
	t.Cleanup(kw.Stop)
	select {
	case <-kw.Ready():
	case <-time.After(2 * time.Second):
		t.Fatal("KqueueWatcher.Ready() timed out")
	}
	return kw
}

// waitKqueueEvent reads one AlertEvent from ch within timeout.
func waitKqueueEvent(ch <-chan agent.AlertEvent, timeout time.Duration) (agent.AlertEvent, bool) {
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
// Lifecycle tests
// ---------------------------------------------------------------------------

// TestKqueueWatcher_StartStop verifies that Start and Stop complete without
// error and that the Events channel is closed after Stop returns.
func TestKqueueWatcher_StartStop(t *testing.T) {
	dir := t.TempDir()
	kw, err := watcher.NewKqueueWatcher(
		[]config.TripwireRule{kqueueRule("rule", dir, "INFO")},
		noopLogger(),
	)
	if err != nil {
		t.Fatalf("NewKqueueWatcher: %v", err)
	}
	if err := kw.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}

	done := make(chan struct{})
	go func() {
		kw.Stop()
		close(done)
	}()
	select {
	case <-done:
	case <-time.After(3 * time.Second):
		t.Fatal("Stop did not return within 3 seconds")
	}

	select {
	case _, ok := <-kw.Events():
		if ok {
			t.Error("expected Events channel to be closed after Stop")
		}
	case <-time.After(time.Second):
		t.Error("Events channel was not closed after Stop")
	}
}

// TestKqueueWatcher_StopIsIdempotent verifies that calling Stop more than once
// does not panic or deadlock.
func TestKqueueWatcher_StopIsIdempotent(t *testing.T) {
	dir := t.TempDir()
	kw := startKqueueWatcher(t, []config.TripwireRule{kqueueRule("rule", dir, "WARN")})
	kw.Stop()
	kw.Stop() // must not panic
}

// TestKqueueWatcher_IgnoresNonFileRules verifies that NETWORK and PROCESS
// rules are silently ignored and Start returns nil.
func TestKqueueWatcher_IgnoresNonFileRules(t *testing.T) {
	rules := []config.TripwireRule{
		{Name: "net", Type: "NETWORK", Target: "8080", Severity: "WARN"},
		{Name: "proc", Type: "PROCESS", Target: "nc", Severity: "CRITICAL"},
	}
	kw, err := watcher.NewKqueueWatcher(rules, noopLogger())
	if err != nil {
		t.Fatalf("NewKqueueWatcher: %v", err)
	}
	if err := kw.Start(context.Background()); err != nil {
		t.Fatalf("Start: unexpected error: %v", err)
	}
	kw.Stop()
}

// TestKqueueWatcher_ReadyChannelClosedAfterStart verifies that the Ready
// channel is closed promptly after Start is called.
func TestKqueueWatcher_ReadyChannelClosedAfterStart(t *testing.T) {
	dir := t.TempDir()
	kw, err := watcher.NewKqueueWatcher(
		[]config.TripwireRule{kqueueRule("rule", dir, "INFO")},
		noopLogger(),
	)
	if err != nil {
		t.Fatalf("NewKqueueWatcher: %v", err)
	}
	if err := kw.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}
	defer kw.Stop()

	select {
	case <-kw.Ready():
		// success
	case <-time.After(2 * time.Second):
		t.Fatal("Ready() was not closed within 2 seconds of Start")
	}
}

// ---------------------------------------------------------------------------
// Event detection tests
// ---------------------------------------------------------------------------

// TestKqueueWatcher_DetectsFileCreate verifies that creating a new file in a
// watched directory emits a "create" AlertEvent with the correct metadata.
func TestKqueueWatcher_DetectsFileCreate(t *testing.T) {
	dir := t.TempDir()
	kw := startKqueueWatcher(t, []config.TripwireRule{kqueueRule("dir-watch", dir, "WARN")})

	newFile := filepath.Join(dir, "canary.txt")
	if err := os.WriteFile(newFile, []byte("data"), 0600); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}

	evt, ok := waitKqueueEvent(kw.Events(), 5*time.Second)
	if !ok {
		t.Fatal("no AlertEvent received within 5 seconds after file create")
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
	if evt.Detail["pid"] != -1 {
		t.Errorf("Detail[pid] = %v, want -1 (sentinel for unknown)", evt.Detail["pid"])
	}
	if evt.Detail["username"] != "unknown" {
		t.Errorf("Detail[username] = %v, want %q", evt.Detail["username"], "unknown")
	}
}

// TestKqueueWatcher_DetectsFileWrite verifies that modifying a file in a
// watched directory emits a "write" AlertEvent.
func TestKqueueWatcher_DetectsFileWrite(t *testing.T) {
	dir := t.TempDir()

	targetFile := filepath.Join(dir, "watched.txt")
	if err := os.WriteFile(targetFile, []byte("initial"), 0600); err != nil {
		t.Fatalf("WriteFile (setup): %v", err)
	}

	kw := startKqueueWatcher(t, []config.TripwireRule{kqueueRule("dir-watch", dir, "CRITICAL")})

	// Small sleep so the OS advances mtime on the next write.
	time.Sleep(10 * time.Millisecond)

	if err := os.WriteFile(targetFile, []byte("modified"), 0600); err != nil {
		t.Fatalf("WriteFile (modify): %v", err)
	}

	deadline := time.After(5 * time.Second)
	for {
		select {
		case evt, ok := <-kw.Events():
			if !ok {
				t.Fatal("Events channel closed unexpectedly")
			}
			if evt.Detail["path"] == targetFile && evt.Detail["operation"] == "write" {
				if evt.Severity != "CRITICAL" {
					t.Errorf("Severity = %q, want CRITICAL", evt.Severity)
				}
				return
			}
		case <-deadline:
			t.Fatal("no write AlertEvent received within 5 seconds after file write")
		}
	}
}

// TestKqueueWatcher_DetectsFileDelete verifies that removing a file from a
// watched directory emits a "delete" AlertEvent.
func TestKqueueWatcher_DetectsFileDelete(t *testing.T) {
	dir := t.TempDir()

	targetFile := filepath.Join(dir, "ephemeral.txt")
	if err := os.WriteFile(targetFile, []byte("data"), 0600); err != nil {
		t.Fatalf("WriteFile (setup): %v", err)
	}

	kw := startKqueueWatcher(t, []config.TripwireRule{kqueueRule("dir-watch", dir, "INFO")})

	if err := os.Remove(targetFile); err != nil {
		t.Fatalf("Remove: %v", err)
	}

	deadline := time.After(5 * time.Second)
	for {
		select {
		case evt, ok := <-kw.Events():
			if !ok {
				t.Fatal("Events channel closed unexpectedly")
			}
			if evt.Detail["path"] == targetFile && evt.Detail["operation"] == "delete" {
				return // success
			}
		case <-deadline:
			t.Fatal("no delete AlertEvent received within 5 seconds after file remove")
		}
	}
}

// TestKqueueWatcher_WatchesSingleFile verifies that a rule targeting an
// individual file (not a directory) emits a write event when that file is
// modified.
func TestKqueueWatcher_WatchesSingleFile(t *testing.T) {
	dir := t.TempDir()
	targetFile := filepath.Join(dir, "secrets.txt")

	if err := os.WriteFile(targetFile, []byte("original"), 0600); err != nil {
		t.Fatalf("WriteFile (setup): %v", err)
	}

	kw := startKqueueWatcher(t, []config.TripwireRule{kqueueRule("single-file", targetFile, "CRITICAL")})

	time.Sleep(10 * time.Millisecond)

	if err := os.WriteFile(targetFile, []byte("tampered"), 0600); err != nil {
		t.Fatalf("WriteFile (modify): %v", err)
	}

	deadline := time.After(5 * time.Second)
	for {
		select {
		case evt, ok := <-kw.Events():
			if !ok {
				t.Fatal("Events channel closed unexpectedly")
			}
			if evt.RuleName == "single-file" && evt.Detail["path"] == targetFile {
				return // success
			}
		case <-deadline:
			t.Fatal("no AlertEvent received within 5 seconds for single-file watch")
		}
	}
}

// ---------------------------------------------------------------------------
// SLA test
// ---------------------------------------------------------------------------

// TestKqueueWatcher_AlertWithinSLA verifies that a create AlertEvent is
// delivered within the 5-second alert SLA after a file is created in a
// watched directory.
func TestKqueueWatcher_AlertWithinSLA(t *testing.T) {
	const sla = 5 * time.Second
	dir := t.TempDir()

	kw := startKqueueWatcher(t, []config.TripwireRule{kqueueRule("sla-watch", dir, "CRITICAL")})

	start := time.Now()
	triggerFile := filepath.Join(dir, "tripwire.txt")
	if err := os.WriteFile(triggerFile, []byte("alert"), 0600); err != nil {
		t.Fatalf("WriteFile (trigger): %v", err)
	}

	deadline := time.After(sla)
	for {
		select {
		case evt, ok := <-kw.Events():
			if !ok {
				t.Fatal("Events channel closed unexpectedly")
			}
			if evt.Detail["path"] == triggerFile && evt.Detail["operation"] == "create" {
				elapsed := time.Since(start)
				t.Logf("kqueue alert received in %v (SLA: %v)", elapsed, sla)
				if elapsed > sla {
					t.Errorf("latency %v exceeded %v SLA", elapsed, sla)
				}
				return
			}
		case <-deadline:
			t.Errorf("no create AlertEvent received within %v SLA", sla)
			return
		}
	}
}
