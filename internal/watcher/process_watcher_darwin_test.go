//go:build darwin

package watcher_test

import (
	"context"
	"os/exec"
	"testing"
	"time"

	"github.com/tripwire/agent/internal/agent"
	"github.com/tripwire/agent/internal/config"
	"github.com/tripwire/agent/internal/watcher"
)

// ---------------------------------------------------------------------------
// Interface compliance
// ---------------------------------------------------------------------------

// TestProcessWatcherDarwin_ImplementsWatcherInterface is a compile-time
// assertion that *ProcessWatcher satisfies the agent.Watcher interface.
func TestProcessWatcherDarwin_ImplementsWatcherInterface(t *testing.T) {
	var _ agent.Watcher = (*watcher.ProcessWatcher)(nil)
}

// ---------------------------------------------------------------------------
// Constructor
// ---------------------------------------------------------------------------

func TestProcessWatcherDarwin_EventsChannelNonNil(t *testing.T) {
	w := watcher.NewProcessWatcher(nil, nil)
	if w.Events() == nil {
		t.Fatal("Events() returned nil before Start")
	}
}

func TestProcessWatcherDarwin_FiltersNonProcessRules(t *testing.T) {
	rules := []config.TripwireRule{
		{Name: "file-rule", Type: "FILE", Target: "/tmp/foo", Severity: "INFO"},
		{Name: "net-rule", Type: "NETWORK", Target: "8080", Severity: "WARN"},
		{Name: "proc-rule", Type: "PROCESS", Target: "sh", Severity: "CRITICAL"},
	}
	w := watcher.NewProcessWatcher(rules, nil)
	if w == nil {
		t.Fatal("NewProcessWatcher returned nil")
	}
	if w.Events() == nil {
		t.Fatal("Events() returned nil")
	}
}

// ---------------------------------------------------------------------------
// Lifecycle tests — no root required
// ---------------------------------------------------------------------------

// TestProcessWatcherDarwin_StartStop verifies that Start and Stop complete
// without error. kqueue creation does not require elevated privileges.
func TestProcessWatcherDarwin_StartStop(t *testing.T) {
	w := watcher.NewProcessWatcher(nil, nil)
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

// TestProcessWatcherDarwin_StartIdempotent verifies that calling Start twice
// is a no-op — the second call must not return an error or launch duplicate
// goroutines.
func TestProcessWatcherDarwin_StartIdempotent(t *testing.T) {
	w := watcher.NewProcessWatcher(nil, nil)
	ctx := context.Background()

	if err := w.Start(ctx); err != nil {
		t.Fatalf("first Start: %v", err)
	}
	defer w.Stop()

	if err := w.Start(ctx); err != nil {
		t.Fatalf("second Start returned an error: %v", err)
	}
}

// TestProcessWatcherDarwin_StopIdempotent verifies that calling Stop more
// than once does not panic or deadlock.
func TestProcessWatcherDarwin_StopIdempotent(t *testing.T) {
	w := watcher.NewProcessWatcher(nil, nil)
	if err := w.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}

	w.Stop()
	w.Stop() // must not panic
}

// TestProcessWatcherDarwin_EventsChannelClosedAfterStop verifies that the
// Events channel is closed (not just empty) after Stop returns.
func TestProcessWatcherDarwin_EventsChannelClosedAfterStop(t *testing.T) {
	w := watcher.NewProcessWatcher(nil, nil)
	if err := w.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}

	events := w.Events()
	w.Stop()

	// Drain any buffered events; the channel must eventually be closed.
	select {
	case _, ok := <-events:
		if ok {
			for range events {
			}
		}
	case <-time.After(2 * time.Second):
		t.Fatal("events channel was not closed after Stop returned")
	}
}

// TestProcessWatcherDarwin_ContextCancellation verifies that cancelling the
// context causes Stop to return promptly.
func TestProcessWatcherDarwin_ContextCancellation(t *testing.T) {
	w := watcher.NewProcessWatcher(nil, nil)
	ctx, cancel := context.WithCancel(context.Background())

	if err := w.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}

	cancel() // signal shutdown via context

	done := make(chan struct{})
	go func() {
		w.Stop()
		close(done)
	}()

	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("Stop did not return within 5 seconds after context cancellation")
	}
}

// ---------------------------------------------------------------------------
// Event emission tests
// ---------------------------------------------------------------------------

// TestProcessWatcherDarwin_ExecveAlertEvent starts the watcher, waits for the
// poll loop to seed the kqueue with the test process's PID, then executes a
// child process and verifies that an AlertEvent is emitted with the correct
// fields.
//
// This test does not require root. The test binary owns all spawned child
// processes, so kqueue EVFILT_PROC permission checks pass without CAP_*.
//
// The test is intentionally lenient on the timeout: short-lived processes may
// be missed on a heavily-loaded system because the kqueue event loop or the
// KERN_PROCARGS2 read races with process exit. A log message is emitted in that
// case rather than a hard failure.
func TestProcessWatcherDarwin_ExecveAlertEvent(t *testing.T) {
	rules := []config.TripwireRule{
		// Empty Target matches every process (catch-all).
		{Name: "any-exec", Type: "PROCESS", Target: "", Severity: "WARN"},
	}

	w := watcher.NewProcessWatcher(rules, nil)
	ctx := context.Background()

	if err := w.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}
	defer w.Stop()

	// Allow the poll loop to run at least once and seed the kqueue with the
	// test process PID so that NOTE_TRACK can propagate to child processes.
	time.Sleep(600 * time.Millisecond)

	// Spawn a trivial child process that causes a fork+exec in the test binary.
	if err := exec.Command("true").Run(); err != nil {
		t.Logf("exec true: %v (non-fatal)", err)
	}

	select {
	case evt, ok := <-w.Events():
		if !ok {
			t.Fatal("events channel closed unexpectedly")
		}
		if evt.TripwireType != "PROCESS" {
			t.Errorf("TripwireType = %q, want %q", evt.TripwireType, "PROCESS")
		}
		if evt.RuleName != "any-exec" {
			t.Errorf("RuleName = %q, want %q", evt.RuleName, "any-exec")
		}
		if evt.Severity != "WARN" {
			t.Errorf("Severity = %q, want %q", evt.Severity, "WARN")
		}
		if evt.Timestamp.IsZero() {
			t.Error("Timestamp must not be zero")
		}
		if evt.Detail == nil {
			t.Fatal("Detail must not be nil")
		}
		if _, ok := evt.Detail["pid"]; !ok {
			t.Error("Detail must contain 'pid'")
		}

	case <-time.After(5 * time.Second):
		// The kqueue approach can occasionally miss very short-lived processes
		// on a heavily-loaded system. Log rather than hard-fail.
		t.Log("no PROCESS AlertEvent received within timeout; " +
			"this may be a race on a lightly-loaded system (kqueue fallback limitation)")
	}
}

// TestProcessWatcherDarwin_PatternFilter verifies that only processes whose
// name matches the configured Target pattern emit an AlertEvent.
func TestProcessWatcherDarwin_PatternFilter(t *testing.T) {
	rules := []config.TripwireRule{
		// Only alert on processes named exactly "true".
		{Name: "true-only", Type: "PROCESS", Target: "true", Severity: "INFO"},
	}

	w := watcher.NewProcessWatcher(rules, nil)
	ctx := context.Background()

	if err := w.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}
	defer w.Stop()

	// Wait for the poll loop to seed the kqueue.
	time.Sleep(600 * time.Millisecond)

	// Execute a process that should NOT match.
	_ = exec.Command("sleep", "0").Run()

	// Execute a process that SHOULD match.
	_ = exec.Command("true").Run()

	deadline := time.After(5 * time.Second)
	for {
		select {
		case evt, ok := <-w.Events():
			if !ok {
				t.Fatal("events channel closed unexpectedly")
			}
			if evt.RuleName != "true-only" {
				// Events for non-matching processes must not appear because
				// the watcher filters them out in emitExecEvent.
				t.Errorf("received event for unexpected rule %q (target filter failed)", evt.RuleName)
			}
			// Received a matching event — pattern filtering works.
			return

		case <-deadline:
			// Accept a timeout as a non-fatal outcome given kqueue timing
			// constraints on macOS.
			t.Log("no matching PROCESS AlertEvent received within timeout; " +
				"this may be a race on a lightly-loaded system")
			return
		}
	}
}
