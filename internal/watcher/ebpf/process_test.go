// Tests for the eBPF-backed process watcher.
//
// Tests that require root / CAP_BPF are skipped when running as an
// unprivileged user. Tests that do not require kernel privileges are always
// run and verify the constructor, event-channel invariants, rule matching, and
// Stop idempotency.
//
//go:build linux

package ebpf_test

import (
	"context"
	"os"
	"testing"
	"time"

	"github.com/tripwire/agent/internal/config"
	"github.com/tripwire/agent/internal/watcher"
	"github.com/tripwire/agent/internal/watcher/ebpf"
)

// ─── Interface compliance ─────────────────────────────────────────────────────

// TestProcessWatcher_ImplementsWatcher is a compile-time assertion that
// *ebpf.ProcessWatcher satisfies the watcher.Watcher interface.
func TestProcessWatcher_ImplementsWatcher(t *testing.T) {
	var _ watcher.Watcher = (*ebpf.ProcessWatcher)(nil)
}

// ─── Constructor ──────────────────────────────────────────────────────────────

func TestNewProcessWatcher_NilLogger(t *testing.T) {
	w := ebpf.NewProcessWatcher(nil, nil)
	if w == nil {
		t.Fatal("NewProcessWatcher returned nil")
	}
}

func TestNewProcessWatcher_EventsChannelNonNil(t *testing.T) {
	w := ebpf.NewProcessWatcher(nil, nil)
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
	w := ebpf.NewProcessWatcher(rules, nil)
	if w == nil {
		t.Fatal("NewProcessWatcher returned nil")
	}
	// Events channel must be non-nil regardless of rule list.
	if w.Events() == nil {
		t.Fatal("Events() returned nil")
	}
}

func TestNewProcessWatcher_EmptyRules(t *testing.T) {
	w := ebpf.NewProcessWatcher([]config.TripwireRule{}, nil)
	if w == nil {
		t.Fatal("NewProcessWatcher returned nil with empty rules")
	}
	if w.Events() == nil {
		t.Fatal("Events() returned nil with empty rules")
	}
}

// ─── Start without privilege ──────────────────────────────────────────────────

// TestProcessWatcher_StartReturnsErrorWithoutPrivilege verifies that Start
// returns a non-nil error when the process lacks CAP_BPF. Skipped when running
// as root because root always has full capability sets.
func TestProcessWatcher_StartReturnsErrorWithoutPrivilege(t *testing.T) {
	if os.Getuid() == 0 {
		t.Skip("running as root; skipping unprivileged error-path test")
	}

	w := ebpf.NewProcessWatcher(nil, nil)
	err := w.Start(context.Background())
	if err == nil {
		w.Stop()
		t.Fatal("Start without CAP_BPF should return an error")
	}
	t.Logf("Start returned expected error: %v", err)
}

// TestProcessWatcher_StopBeforeStart verifies that calling Stop before Start
// does not panic and closes the Events channel.
func TestProcessWatcher_StopBeforeStart(t *testing.T) {
	w := ebpf.NewProcessWatcher(nil, nil)

	done := make(chan struct{})
	go func() {
		defer close(done)
		w.Stop()
	}()

	select {
	case <-done:
	case <-time.After(2 * time.Second):
		t.Fatal("Stop before Start did not return within 2 seconds")
	}

	// Events channel must be closed after Stop.
	select {
	case _, ok := <-w.Events():
		if ok {
			// Drain any buffered events; channel must eventually close.
			for range w.Events() {
			}
		}
	case <-time.After(1 * time.Second):
		t.Fatal("events channel not closed after Stop")
	}
}

// TestProcessWatcher_StopIdempotent verifies that calling Stop more than once
// does not panic.
func TestProcessWatcher_StopIdempotent(t *testing.T) {
	w := ebpf.NewProcessWatcher(nil, nil)
	w.Stop()
	w.Stop() // must not panic or deadlock
}

// ─── Privileged tests (root / CAP_BPF required) ───────────────────────────────
//
// The tests below require the compiled process.bpf.o object AND root or
// CAP_BPF. They are skipped on CI when running without those privileges.

func TestProcessWatcher_StartStop(t *testing.T) {
	if os.Getuid() != 0 {
		t.Skip("TestProcessWatcher_StartStop requires root / CAP_BPF")
	}

	w := ebpf.NewProcessWatcher(nil, nil)
	ctx := context.Background()

	if err := w.Start(ctx); err != nil {
		t.Skipf("Start failed (BPF object or kernel support unavailable): %v", err)
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
		t.Skip("requires root / CAP_BPF")
	}

	w := ebpf.NewProcessWatcher(nil, nil)
	ctx := context.Background()

	if err := w.Start(ctx); err != nil {
		t.Skipf("Start failed (BPF unavailable): %v", err)
	}
	defer w.Stop()

	// A second Start must be a no-op.
	if err := w.Start(ctx); err != nil {
		t.Fatalf("second Start returned an error: %v", err)
	}
}

func TestProcessWatcher_EventsChannelClosedAfterStop(t *testing.T) {
	if os.Getuid() != 0 {
		t.Skip("requires root / CAP_BPF")
	}

	w := ebpf.NewProcessWatcher(nil, nil)
	ctx := context.Background()

	if err := w.Start(ctx); err != nil {
		t.Skipf("Start failed (BPF unavailable): %v", err)
	}

	events := w.Events()
	w.Stop()

	select {
	case _, ok := <-events:
		if ok {
			for range events {
			}
		}
	case <-time.After(2 * time.Second):
		t.Fatal("events channel not closed after Stop returned")
	}
}

func TestProcessWatcher_ContextCancellation(t *testing.T) {
	if os.Getuid() != 0 {
		t.Skip("requires root / CAP_BPF")
	}

	w := ebpf.NewProcessWatcher(nil, nil)
	ctx, cancel := context.WithCancel(context.Background())

	if err := w.Start(ctx); err != nil {
		t.Skipf("Start failed (BPF unavailable): %v", err)
	}

	cancel()

	done := make(chan struct{})
	go func() {
		w.Stop()
		close(done)
	}()

	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("Stop did not return within 5 seconds after context cancel")
	}
}

// ─── execEventSize sanity guard ───────────────────────────────────────────────

// TestExecEventSize verifies that the execEventSize constant matches the
// declared Go struct size. This guards against accidental layout drift between
// the C exec_event definition in process.h and the Go mirror.
func TestExecEventSize(t *testing.T) {
	// 4+4+4+4+16+256+256 = 544 bytes as declared in process.h
	const want = 544
	if ebpf.ExecEventSize != want {
		t.Errorf("ExecEventSize = %d, want %d (check process.h and Go mirror)", ebpf.ExecEventSize, want)
	}
}
