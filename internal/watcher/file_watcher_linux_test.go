//go:build linux

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

// inotifyRule is a convenience constructor for a FILE-type TripwireRule.
func inotifyRule(name, target, severity string) config.TripwireRule {
	return config.TripwireRule{
		Name:     name,
		Type:     "FILE",
		Target:   target,
		Severity: severity,
	}
}

// startInotifyWatcher creates an InotifyWatcher, starts it, waits for Ready(),
// and registers cleanup via t.Cleanup.
func startInotifyWatcher(t *testing.T, rules []config.TripwireRule) *watcher.InotifyWatcher {
	t.Helper()
	iw, err := watcher.NewInotifyWatcher(rules, noopLogger())
	if err != nil {
		t.Fatalf("NewInotifyWatcher: %v", err)
	}
	if err := iw.Start(context.Background()); err != nil {
		t.Fatalf("InotifyWatcher.Start: %v", err)
	}
	t.Cleanup(iw.Stop)
	select {
	case <-iw.Ready():
	case <-time.After(2 * time.Second):
		t.Fatal("InotifyWatcher.Ready() timed out")
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
// Lifecycle tests
// ---------------------------------------------------------------------------

// TestInotifyWatcher_StartStop verifies that Start and Stop complete without
// error and that the Events channel is closed after Stop returns.
func TestInotifyWatcher_StartStop(t *testing.T) {
	dir := t.TempDir()
	iw, err := watcher.NewInotifyWatcher(
		[]config.TripwireRule{inotifyRule("rule", dir, "INFO")},
		noopLogger(),
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
	iw := startInotifyWatcher(t, []config.TripwireRule{inotifyRule("rule", dir, "WARN")})
	iw.Stop()
	iw.Stop() // must not panic
}

// TestInotifyWatcher_IgnoresNonFileRules verifies that NETWORK and PROCESS
// rules are silently ignored and Start returns nil.
func TestInotifyWatcher_IgnoresNonFileRules(t *testing.T) {
	rules := []config.TripwireRule{
		{Name: "net", Type: "NETWORK", Target: "8080", Severity: "WARN"},
		{Name: "proc", Type: "PROCESS", Target: "nc", Severity: "CRITICAL"},
	}
	iw, err := watcher.NewInotifyWatcher(rules, noopLogger())
	if err != nil {
		t.Fatalf("NewInotifyWatcher: %v", err)
	}
	if err := iw.Start(context.Background()); err != nil {
		t.Fatalf("Start: unexpected error: %v", err)
	}
	iw.Stop()
}

// TestInotifyWatcher_ReadyChannelClosedAfterStart verifies that the Ready
// channel is closed promptly after Start is called.
func TestInotifyWatcher_ReadyChannelClosedAfterStart(t *testing.T) {
	dir := t.TempDir()
	iw, err := watcher.NewInotifyWatcher(
		[]config.TripwireRule{inotifyRule("rule", dir, "INFO")},
		noopLogger(),
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
	case <-time.After(2 * time.Second):
		t.Fatal("Ready() was not closed within 2 seconds of Start")
	}
}

// ---------------------------------------------------------------------------
// Event detection tests
// ---------------------------------------------------------------------------

// TestInotifyWatcher_DetectsFileCreate verifies that creating a new file in a
// watched directory emits a "create" AlertEvent with the correct metadata.
func TestInotifyWatcher_DetectsFileCreate(t *testing.T) {
	dir := t.TempDir()
	iw := startInotifyWatcher(t, []config.TripwireRule{inotifyRule("dir-watch", dir, "WARN")})

	newFile := filepath.Join(dir, "canary.txt")
	if err := os.WriteFile(newFile, []byte("data"), 0600); err != nil {
		t.Fatalf("WriteFile: %v", err)
	}

	evt, ok := waitInotifyEvent(iw.Events(), 5*time.Second)
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
	// Verify PID sentinel value (inotify cannot provide PID).
	if evt.Detail["pid"] != -1 {
		t.Errorf("Detail[pid] = %v, want -1 (sentinel for unknown)", evt.Detail["pid"])
	}
	if evt.Detail["username"] != "unknown" {
		t.Errorf("Detail[username] = %v, want %q", evt.Detail["username"], "unknown")
	}
}

// TestInotifyWatcher_DetectsFileWrite verifies that modifying an existing file
// in a watched directory emits a "write" AlertEvent.
func TestInotifyWatcher_DetectsFileWrite(t *testing.T) {
	dir := t.TempDir()

	// Pre-create the file so it exists when the watcher starts.
	targetFile := filepath.Join(dir, "watched.txt")
	if err := os.WriteFile(targetFile, []byte("initial"), 0600); err != nil {
		t.Fatalf("WriteFile (setup): %v", err)
	}

	iw := startInotifyWatcher(t, []config.TripwireRule{inotifyRule("dir-watch", dir, "CRITICAL")})

	if err := os.WriteFile(targetFile, []byte("modified"), 0600); err != nil {
		t.Fatalf("WriteFile (modify): %v", err)
	}

	// Drain events until we see a write (there may be access events first).
	deadline := time.After(5 * time.Second)
	for {
		select {
		case evt, ok := <-iw.Events():
			if !ok {
				t.Fatal("Events channel closed unexpectedly")
			}
			if evt.Detail["path"] == targetFile && evt.Detail["operation"] == "write" {
				// Success — verify metadata.
				if evt.Severity != "CRITICAL" {
					t.Errorf("Severity = %q, want CRITICAL", evt.Severity)
				}
				return
			}
			// Keep draining other events (e.g. access, create).
		case <-deadline:
			t.Fatal("no write AlertEvent received within 5 seconds after file write")
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

	iw := startInotifyWatcher(t, []config.TripwireRule{inotifyRule("dir-watch", dir, "INFO")})

	if err := os.Remove(targetFile); err != nil {
		t.Fatalf("Remove: %v", err)
	}

	deadline := time.After(5 * time.Second)
	for {
		select {
		case evt, ok := <-iw.Events():
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

// TestInotifyWatcher_DetectsFileAccess verifies that reading a file in a
// watched directory emits an "access" AlertEvent, distinguishing the
// InotifyWatcher from the polling-based FileWatcher (which cannot detect reads).
func TestInotifyWatcher_DetectsFileAccess(t *testing.T) {
	dir := t.TempDir()

	targetFile := filepath.Join(dir, "secret.txt")
	if err := os.WriteFile(targetFile, []byte("sensitive"), 0600); err != nil {
		t.Fatalf("WriteFile (setup): %v", err)
	}

	iw := startInotifyWatcher(t, []config.TripwireRule{inotifyRule("dir-watch", dir, "WARN")})

	// Read the file to trigger IN_ACCESS.
	f, err := os.Open(targetFile)
	if err != nil {
		t.Fatalf("Open: %v", err)
	}
	buf := make([]byte, 32)
	_, _ = f.Read(buf)
	f.Close()

	deadline := time.After(5 * time.Second)
	for {
		select {
		case evt, ok := <-iw.Events():
			if !ok {
				t.Fatal("Events channel closed unexpectedly")
			}
			if evt.Detail["path"] == targetFile && evt.Detail["operation"] == "access" {
				return // success
			}
		case <-deadline:
			t.Fatal("no access AlertEvent received within 5 seconds after file read")
		}
	}
}

// TestInotifyWatcher_WatchesSingleFile verifies that a rule targeting an
// individual file (not a directory) emits events when that file is modified.
func TestInotifyWatcher_WatchesSingleFile(t *testing.T) {
	dir := t.TempDir()
	targetFile := filepath.Join(dir, "secrets.txt")

	if err := os.WriteFile(targetFile, []byte("original"), 0600); err != nil {
		t.Fatalf("WriteFile (setup): %v", err)
	}

	iw := startInotifyWatcher(t, []config.TripwireRule{inotifyRule("single-file", targetFile, "CRITICAL")})

	if err := os.WriteFile(targetFile, []byte("tampered"), 0600); err != nil {
		t.Fatalf("WriteFile (modify): %v", err)
	}

	deadline := time.After(5 * time.Second)
	for {
		select {
		case evt, ok := <-iw.Events():
			if !ok {
				t.Fatal("Events channel closed unexpectedly")
			}
			if evt.RuleName == "single-file" && evt.Detail["path"] == targetFile {
				return // success (any operation is acceptable)
			}
		case <-deadline:
			t.Fatalf("no AlertEvent received within 5 seconds for single-file watch")
		}
	}
}

// ---------------------------------------------------------------------------
// SLA test
// ---------------------------------------------------------------------------

// TestInotifyWatcher_AlertWithinSLA verifies that an AlertEvent is delivered
// to a consuming goroutine within the 5-second alert SLA after a file is
// created in a watched directory.
func TestInotifyWatcher_AlertWithinSLA(t *testing.T) {
	const sla = 5 * time.Second
	dir := t.TempDir()

	iw := startInotifyWatcher(t, []config.TripwireRule{inotifyRule("sla-watch", dir, "CRITICAL")})

	start := time.Now()
	triggerFile := filepath.Join(dir, "tripwire.txt")
	if err := os.WriteFile(triggerFile, []byte("alert"), 0600); err != nil {
		t.Fatalf("WriteFile (trigger): %v", err)
	}

	deadline := time.After(sla)
	for {
		select {
		case evt, ok := <-iw.Events():
			if !ok {
				t.Fatal("Events channel closed unexpectedly")
			}
			if evt.Detail["path"] == triggerFile && evt.Detail["operation"] == "create" {
				elapsed := time.Since(start)
				t.Logf("inotify alert received in %v (SLA: %v)", elapsed, sla)
				if elapsed > sla {
					t.Errorf("latency %v exceeded %v SLA", elapsed, sla)
				}
				if evt.TripwireType != "FILE" {
					t.Errorf("TripwireType = %q, want FILE", evt.TripwireType)
				}
				return
			}
		case <-deadline:
			t.Errorf("no create AlertEvent received within %v SLA", sla)
			return
		}
	}
}
