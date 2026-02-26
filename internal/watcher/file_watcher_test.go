package watcher

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

// --------------------------------------------------------------------------
// Test helpers
// --------------------------------------------------------------------------

func noopLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{
		Level: slog.LevelError + 10, // suppress all output
	}))
}

func fileRule(target, name string) config.TripwireRule {
	return config.TripwireRule{
		Name:     name,
		Type:     "FILE",
		Target:   target,
		Severity: "WARN",
	}
}

// receiveEvent waits up to timeout for a single AlertEvent from the channel.
func receiveEvent(ch <-chan agent.AlertEvent, timeout time.Duration) (agent.AlertEvent, bool) {
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

// --------------------------------------------------------------------------
// Tests
// --------------------------------------------------------------------------

// TestFileWatcher_StartStop verifies that Start returns without error and
// Stop exits cleanly, closing the events channel.
func TestFileWatcher_StartStop(t *testing.T) {
	dir := t.TempDir()
	rule := fileRule(filepath.Join(dir, "canary.txt"), "start-stop")

	fw := NewFileWatcher(rule, noopLogger())

	ctx := context.Background()
	if err := fw.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}

	fw.Stop()

	// Events channel must be closed after Stop.
	select {
	case _, ok := <-fw.Events():
		if ok {
			t.Error("events channel should be closed after Stop")
		}
	case <-time.After(time.Second):
		t.Error("events channel was not closed within 1s after Stop")
	}
}

// TestFileWatcher_StopBeforeStart verifies that calling Stop before Start
// does not panic or deadlock.
func TestFileWatcher_StopBeforeStart(t *testing.T) {
	dir := t.TempDir()
	fw := NewFileWatcher(fileRule(filepath.Join(dir, "x.txt"), "no-start"), noopLogger())
	fw.Stop() // must not panic or hang
}

// TestFileWatcher_StartTwiceReturnsError verifies that a second Start call
// returns an error rather than starting a second goroutine.
func TestFileWatcher_StartTwiceReturnsError(t *testing.T) {
	dir := t.TempDir()
	fw := NewFileWatcher(fileRule(filepath.Join(dir, "x.txt"), "twice"), noopLogger())

	ctx := context.Background()
	if err := fw.Start(ctx); err != nil {
		t.Fatalf("first Start: %v", err)
	}
	defer fw.Stop()

	if err := fw.Start(ctx); err == nil {
		t.Error("second Start should return error, got nil")
	}
}

// TestFileWatcher_EventDelivery is the end-to-end test: write to a watched
// file and expect an alert event within 5 seconds.
func TestFileWatcher_EventDelivery(t *testing.T) {
	dir := t.TempDir()
	target := filepath.Join(dir, "watched.txt")

	// Create the file before starting the watcher so it is watched directly.
	if err := os.WriteFile(target, []byte("init"), 0o644); err != nil {
		t.Fatalf("create watched file: %v", err)
	}

	rule := fileRule(target, "event-delivery")
	fw := NewFileWatcher(rule, noopLogger())

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := fw.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}
	defer fw.Stop()

	// Give the watcher time to set up its internal watches.
	time.Sleep(100 * time.Millisecond)

	// Trigger a write event.
	if err := os.WriteFile(target, []byte("trigger"), 0o644); err != nil {
		t.Fatalf("write to watched file: %v", err)
	}

	evt, ok := receiveEvent(fw.Events(), 5*time.Second)
	if !ok {
		t.Fatal("no alert event received within 5 seconds of writing the watched file")
	}

	// Verify mandatory alert fields.
	if evt.TripwireType != "FILE" {
		t.Errorf("TripwireType = %q, want %q", evt.TripwireType, "FILE")
	}
	if evt.RuleName != rule.Name {
		t.Errorf("RuleName = %q, want %q", evt.RuleName, rule.Name)
	}
	if evt.Severity != rule.Severity {
		t.Errorf("Severity = %q, want %q", evt.Severity, rule.Severity)
	}
	if evt.Timestamp.IsZero() {
		t.Error("Timestamp must be non-zero")
	}
	if evt.Detail == nil {
		t.Error("Detail must be non-nil")
	}
	if _, ok := evt.Detail["path"]; !ok {
		t.Error("Detail must contain 'path' field")
	}
	if _, ok := evt.Detail["event_type"]; !ok {
		t.Error("Detail must contain 'event_type' field")
	}
}

// TestFileWatcher_EventDelivery_GlobTarget verifies that when the rule target
// uses a directory path (no specific file), creation events inside that
// directory are captured.
func TestFileWatcher_EventDelivery_GlobTarget(t *testing.T) {
	dir := t.TempDir()

	// Target is the directory; no specific file initially.
	rule := fileRule(dir, "dir-watch")
	fw := NewFileWatcher(rule, noopLogger())

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := fw.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}
	defer fw.Stop()

	time.Sleep(100 * time.Millisecond)

	// Create a new file inside the watched directory.
	newFile := filepath.Join(dir, "new.txt")
	if err := os.WriteFile(newFile, []byte("hello"), 0o644); err != nil {
		t.Fatalf("create file: %v", err)
	}

	_, ok := receiveEvent(fw.Events(), 5*time.Second)
	if !ok {
		t.Fatal("no alert event received within 5 seconds of creating a file in watched directory")
	}
}

// TestFileWatcher_RestartOnError verifies that the FileWatcher recovers from
// a platform watcher error and continues to deliver events.
func TestFileWatcher_RestartOnError(t *testing.T) {
	dir := t.TempDir()
	target := filepath.Join(dir, "restart.txt")

	if err := os.WriteFile(target, []byte("init"), 0o644); err != nil {
		t.Fatalf("create file: %v", err)
	}

	rule := fileRule(target, "restart-test")
	fw := NewFileWatcher(rule, noopLogger())

	// Inject a fake platform watcher: fails on the first call, works on
	// subsequent calls by blocking until ctx is cancelled (clean exit).
	callCount := 0
	fw.platformWatcher = func(ctx context.Context, paths []string, events chan<- FileEvent) error {
		callCount++
		if callCount == 1 {
			// Simulate an error on the first attempt.
			return errors.New("simulated platform watcher failure")
		}
		// Second+ attempts: emit one synthetic event then block for clean shutdown.
		select {
		case events <- FileEvent{
			FilePath:  paths[0],
			EventType: EventWrite,
			Timestamp: time.Now(),
		}:
		default:
		}
		<-ctx.Done()
		return nil
	}

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := fw.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}
	defer fw.Stop()

	// The watcher should restart after the error and deliver the event from
	// the second call. Allow a generous window to account for backoff.
	evt, ok := receiveEvent(fw.Events(), 5*time.Second)
	if !ok {
		t.Fatalf("no event received after watcher restart (callCount=%d)", callCount)
	}

	if callCount < 2 {
		t.Errorf("expected at least 2 platform watcher calls (restart), got %d", callCount)
	}

	if evt.TripwireType != "FILE" {
		t.Errorf("TripwireType = %q, want FILE", evt.TripwireType)
	}
}

// TestFileWatcher_ContextCancellationStopsWatcher verifies that cancelling
// the context passed to Start causes the watcher to stop without calling
// Stop explicitly.
func TestFileWatcher_ContextCancellationStopsWatcher(t *testing.T) {
	dir := t.TempDir()
	rule := fileRule(filepath.Join(dir, "ctx.txt"), "ctx-cancel")
	fw := NewFileWatcher(rule, noopLogger())

	ctx, cancel := context.WithCancel(context.Background())

	if err := fw.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}

	cancel() // Cancel the outer context.

	// The events channel should close within a reasonable window.
	select {
	case _, ok := <-fw.Events():
		if ok {
			// Received a real event — drain until closed.
			for ok {
				_, ok = <-fw.Events()
			}
		}
	case <-time.After(3 * time.Second):
		t.Error("events channel not closed within 3s of context cancellation")
	}
}

// TestFileWatcher_InterfaceCompliance is a compile-time check that
// *FileWatcher satisfies agent.Watcher.
func TestFileWatcher_InterfaceCompliance(t *testing.T) {
	var _ agent.Watcher = (*FileWatcher)(nil)
}

// TestFileWatcher_InvalidGlobReturnsError verifies that a syntactically
// invalid glob in the rule Target causes Start to return an error.
func TestFileWatcher_InvalidGlobReturnsError(t *testing.T) {
	rule := fileRule("[invalid", "bad-glob")
	fw := NewFileWatcher(rule, noopLogger())

	err := fw.Start(context.Background())
	if err == nil {
		fw.Stop()
		t.Fatal("expected error for invalid glob, got nil")
	}
	t.Logf("Start returned expected error: %v", err)
}
