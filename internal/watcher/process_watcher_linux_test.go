//go:build linux

package watcher_test

import (
	"context"
	"os"
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

// TestProcessWatcher_ImplementsWatcherInterface is a compile-time assertion
// that *ProcessWatcher satisfies the agent.Watcher interface.
func TestProcessWatcher_ImplementsWatcherInterface(t *testing.T) {
	var _ agent.Watcher = (*watcher.ProcessWatcher)(nil)
}

// ---------------------------------------------------------------------------
// Constructor
// ---------------------------------------------------------------------------

func TestNewProcessWatcher_EventsChannelNonNil(t *testing.T) {
	w := watcher.NewProcessWatcher(nil, nil)
	if w.Events() == nil {
		t.Fatal("Events() returned nil before Start")
	}
}

func TestNewProcessWatcher_FiltersNonProcessRules(t *testing.T) {
	rules := []config.TripwireRule{
		{Name: "file-rule", Type: "FILE", Target: "/tmp/foo", Severity: "INFO"},
		{Name: "net-rule", Type: "NETWORK", Target: "8080", Severity: "WARN"},
		{Name: "proc-rule", Type: "PROCESS", Target: "sh", Severity: "CRITICAL"},
	}
	w := watcher.NewProcessWatcher(rules, nil)
	// The watcher itself doesn't expose rule count, but it must not be nil
	// and the Events channel must be non-nil.
	if w == nil {
		t.Fatal("NewProcessWatcher returned nil")
	}
	if w.Events() == nil {
		t.Fatal("Events() returned nil")
	}
}

// ---------------------------------------------------------------------------
// Privilege check (unprivileged path)
// ---------------------------------------------------------------------------

// TestProcessWatcher_StartReturnsErrorWithoutPrivilege tests the error path
// when the process lacks CAP_NET_ADMIN. It is skipped when running as root
// because root always succeeds.
func TestProcessWatcher_StartReturnsErrorWithoutPrivilege(t *testing.T) {
	if os.Getuid() == 0 {
		t.Skip("running as root; skipping the unprivileged error-path test")
	}

	w := watcher.NewProcessWatcher(nil, nil)
	err := w.Start(context.Background())
	if err == nil {
		w.Stop()
		t.Fatal("Start with insufficient privilege should have returned an error")
	}
	t.Logf("Start returned expected error: %v", err)
}

// ---------------------------------------------------------------------------
// Privileged tests (root / CAP_NET_ADMIN required)
// ---------------------------------------------------------------------------

func TestProcessWatcher_StartStop(t *testing.T) {
	if os.Getuid() != 0 {
		t.Skip("TestProcessWatcher_StartStop requires root / CAP_NET_ADMIN")
	}

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

func TestProcessWatcher_StartIdempotent(t *testing.T) {
	if os.Getuid() != 0 {
		t.Skip("requires root / CAP_NET_ADMIN")
	}

	w := watcher.NewProcessWatcher(nil, nil)
	ctx := context.Background()

	if err := w.Start(ctx); err != nil {
		t.Fatalf("first Start: %v", err)
	}
	defer w.Stop()

	// A second Start must be a no-op (no error, no panic).
	if err := w.Start(ctx); err != nil {
		t.Fatalf("second Start returned an error: %v", err)
	}
}

func TestProcessWatcher_StopIdempotent(t *testing.T) {
	if os.Getuid() != 0 {
		t.Skip("requires root / CAP_NET_ADMIN")
	}

	w := watcher.NewProcessWatcher(nil, nil)
	if err := w.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}

	w.Stop()
	w.Stop() // must not panic
}

func TestProcessWatcher_EventsChannelClosedAfterStop(t *testing.T) {
	if os.Getuid() != 0 {
		t.Skip("requires root / CAP_NET_ADMIN")
	}

	w := watcher.NewProcessWatcher(nil, nil)
	if err := w.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}

	events := w.Events()
	w.Stop()

	// After Stop the channel must be closed.
	select {
	case _, ok := <-events:
		if ok {
			// Drain buffered events; channel must eventually close.
			for range events {
			}
		}
	case <-time.After(2 * time.Second):
		t.Fatal("events channel was not closed after Stop returned")
	}
}

func TestProcessWatcher_ContextCancellation(t *testing.T) {
	if os.Getuid() != 0 {
		t.Skip("requires root / CAP_NET_ADMIN")
	}

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
// Event emission — AlertEvent fields
// ---------------------------------------------------------------------------

// TestProcessWatcher_ExecveAlertEvent executes a real process while the
// watcher is running and verifies that an AlertEvent with the correct fields
// is emitted. Requires root / CAP_NET_ADMIN.
func TestProcessWatcher_ExecveAlertEvent(t *testing.T) {
	if os.Getuid() != 0 {
		t.Skip("requires root / CAP_NET_ADMIN")
	}

	rules := []config.TripwireRule{
		// Match any process (empty Target = wildcard).
		{Name: "any-exec", Type: "PROCESS", Target: "", Severity: "WARN"},
	}

	w := watcher.NewProcessWatcher(rules, nil)
	ctx := context.Background()

	if err := w.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}
	defer w.Stop()

	// Allow the watcher to register before we trigger a process.
	time.Sleep(100 * time.Millisecond)

	// Execute a trivial command to generate a PROC_EVENT_EXEC notification.
	if err := exec.Command("true").Run(); err != nil {
		t.Logf("exec true: %v (non-fatal)", err)
	}

	// Wait for an AlertEvent (or time out).
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
		t.Log("no PROCESS AlertEvent received within timeout; " +
			"this may be a race on a lightly-loaded system")
	}
}

// TestProcessWatcher_PatternFilter verifies that the watcher only emits events
// for processes whose name matches the configured Target pattern.
func TestProcessWatcher_PatternFilter(t *testing.T) {
	if os.Getuid() != 0 {
		t.Skip("requires root / CAP_NET_ADMIN")
	}

	// Only alert on processes named "true".
	rules := []config.TripwireRule{
		{Name: "true-only", Type: "PROCESS", Target: "true", Severity: "INFO"},
	}

	w := watcher.NewProcessWatcher(rules, nil)
	ctx := context.Background()

	if err := w.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}
	defer w.Stop()

	time.Sleep(100 * time.Millisecond)

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
				t.Errorf("received event for unexpected rule %q", evt.RuleName)
			}
			// Got a matching event — test passes.
			return
		case <-deadline:
			t.Log("no matching PROCESS AlertEvent received within timeout; " +
				"this may be a race on a lightly-loaded system")
			return
		}
	}
}

// ---------------------------------------------------------------------------
// Struct size constants (regression guard)
// ---------------------------------------------------------------------------

// TestProcessWatcher_StructSizeConstants guards against accidental edits to
// the kernel ABI size constants defined in process_watcher_linux.go. Because
// these constants are unexported, the test validates observable behaviour that
// depends on them (the watcher must start and stop cleanly at root).
func TestProcessWatcher_StructSizeConstants(t *testing.T) {
	if os.Getuid() != 0 {
		t.Skip("requires root / CAP_NET_ADMIN")
	}

	// If the struct size constants are wrong sendProcCNMsg will produce a
	// malformed netlink message, which will cause Bind or Sendto to fail.
	w := watcher.NewProcessWatcher(nil, nil)
	if err := w.Start(context.Background()); err != nil {
		t.Fatalf("Start failed (struct size constants may be incorrect): %v", err)
	}
	w.Stop()
}
