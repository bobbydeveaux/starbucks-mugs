// Package watcher contains internal unit tests for ProcessWatcher.
// These tests run in package watcher (not watcher_test) so they can access
// unexported fields and interfaces.
package watcher

import (
	"context"
	"errors"
	"log/slog"
	"os"
	"testing"
	"time"

	"github.com/tripwire/agent/internal/config"
)

// noopLogger returns a *slog.Logger that discards all log output. Defined here
// (rather than inherited from file_test.go) because this file belongs to the
// internal package watcher, not the external package watcher_test.
func noopLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelError + 10}))
}

// ---------------------------------------------------------------------------
// Interface compliance (compile-time)
// ---------------------------------------------------------------------------

// TestProcessWatcher_ImplementsWatcherInterface verifies at compile-time that
// *ProcessWatcher satisfies the Watcher interface.
func TestProcessWatcher_ImplementsWatcherInterface(t *testing.T) {
	var _ Watcher = (*ProcessWatcher)(nil)
}

// ---------------------------------------------------------------------------
// Constructor
// ---------------------------------------------------------------------------

// TestNewProcessWatcher_FiltersNonProcessRules verifies that rules with types
// other than "PROCESS" are silently ignored.
func TestNewProcessWatcher_FiltersNonProcessRules(t *testing.T) {
	rules := []config.TripwireRule{
		{Name: "file-rule", Type: "FILE", Target: "/etc/passwd", Severity: "WARN"},
		{Name: "net-rule", Type: "NETWORK", Target: "8080", Severity: "INFO"},
		{Name: "proc-rule", Type: "PROCESS", Target: "bash", Severity: "CRITICAL"},
	}

	pw := NewProcessWatcher(rules, nil)
	if pw == nil {
		t.Fatal("NewProcessWatcher returned nil")
	}
	if pw.Events() == nil {
		t.Fatal("Events() returned nil before Start")
	}
	if pw.Ready() == nil {
		t.Fatal("Ready() returned nil before Start")
	}
	// Should have filtered to only the PROCESS rule.
	if len(pw.rules) != 1 {
		t.Errorf("expected 1 PROCESS rule, got %d", len(pw.rules))
	}
}

// TestNewProcessWatcher_NilLogger verifies that passing nil for the logger does
// not panic.
func TestNewProcessWatcher_NilLogger(t *testing.T) {
	rules := []config.TripwireRule{procRule("r", "bash", "INFO")}
	pw := NewProcessWatcher(rules, nil)
	if pw == nil {
		t.Fatal("NewProcessWatcher(nil logger) returned nil")
	}
}

// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------

// TestProcessWatcher_StartStop verifies that Start and Stop complete without
// error and that the Events channel is closed after Stop returns.
func TestProcessWatcher_StartStop(t *testing.T) {
	pw := newTestWatcher(t, "bash", "WARN",
		&stubBackend{blockUntilDone: true})

	if err := pw.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}

	done := make(chan struct{})
	go func() {
		pw.Stop()
		close(done)
	}()

	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("Stop did not return within 5 seconds")
	}
}

// TestProcessWatcher_StopIsIdempotent verifies that calling Stop more than once
// does not panic or deadlock.
func TestProcessWatcher_StopIsIdempotent(t *testing.T) {
	pw := newTestWatcher(t, "bash", "INFO",
		&stubBackend{blockUntilDone: true})

	if err := pw.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}

	pw.Stop()
	pw.Stop() // must not panic
}

// TestProcessWatcher_EventsChannelClosedAfterStop verifies that the Events
// channel is closed (not merely empty) after Stop returns.
func TestProcessWatcher_EventsChannelClosedAfterStop(t *testing.T) {
	pw := newTestWatcher(t, "bash", "INFO",
		&stubBackend{blockUntilDone: true})

	if err := pw.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}

	events := pw.Events()
	pw.Stop()

	select {
	case _, ok := <-events:
		if ok {
			// A buffered event is fine — drain until closed.
			for range events {
			}
		}
	case <-time.After(2 * time.Second):
		t.Fatal("events channel was not closed within 2 seconds after Stop")
	}
}

// TestProcessWatcher_ReadyChannelClosedAfterStart verifies that the Ready
// channel is closed shortly after Start is called.
func TestProcessWatcher_ReadyChannelClosedAfterStart(t *testing.T) {
	pw := newTestWatcher(t, "bash", "INFO",
		&stubBackend{blockUntilDone: true})

	if err := pw.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}
	defer pw.Stop()

	select {
	case <-pw.Ready():
		// success
	case <-time.After(2 * time.Second):
		t.Fatal("Ready() channel was not closed within 2 seconds of Start")
	}
}

// TestProcessWatcher_StopBeforeStart verifies that calling Stop before Start
// does not panic or deadlock.
func TestProcessWatcher_StopBeforeStart(t *testing.T) {
	pw := newTestWatcher(t, "bash", "INFO",
		&stubBackend{blockUntilDone: true})
	pw.Stop() // must not panic or hang
}

// ---------------------------------------------------------------------------
// Event matching and dispatch
// ---------------------------------------------------------------------------

// TestProcessWatcher_EmitsAlertEventOnMatch verifies that a ProcessEvent whose
// Command matches a configured rule is converted into a correctly-formed
// AlertEvent with the expected fields.
func TestProcessWatcher_EmitsAlertEventOnMatch(t *testing.T) {
	pw := newTestWatcher(t, "bash", "CRITICAL",
		&stubBackend{
			events: []ProcessEvent{
				{PID: 1234, PPID: 1000, UID: 0, Username: "root", Command: "bash", CmdLine: "bash -i"},
			},
			blockUntilDone: true,
		})

	if err := pw.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}
	defer pw.Stop()

	<-pw.Ready()

	evt, ok := waitForAlert(t, pw.Events(), 3*time.Second)
	if !ok {
		t.Fatal("no AlertEvent received within 3 seconds")
	}

	assertAlertField(t, "TripwireType", evt.TripwireType, "PROCESS")
	assertAlertField(t, "RuleName", evt.RuleName, "bash-watch")
	assertAlertField(t, "Severity", evt.Severity, "CRITICAL")

	if evt.Timestamp.IsZero() {
		t.Error("Timestamp must not be zero")
	}
	if evt.Detail == nil {
		t.Fatal("Detail must not be nil")
	}

	assertDetailField(t, evt.Detail, "pid", 1234)
	assertDetailField(t, evt.Detail, "ppid", 1000)
	assertDetailField(t, evt.Detail, "uid", 0)
	assertDetailField(t, evt.Detail, "command", "bash")
	assertDetailField(t, evt.Detail, "cmdline", "bash -i")
	assertDetailField(t, evt.Detail, "username", "root")
}

// TestProcessWatcher_DropsNonMatchingEvents verifies that process events whose
// Command does not match any configured rule are silently dropped.
func TestProcessWatcher_DropsNonMatchingEvents(t *testing.T) {
	pw := newTestWatcher(t, "bash", "CRITICAL",
		&stubBackend{
			events: []ProcessEvent{
				{PID: 5678, PPID: 1000, UID: 1001, Command: "python3"},
			},
			blockUntilDone: true,
		})

	if err := pw.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}
	defer pw.Stop()

	<-pw.Ready()

	_, ok := waitForAlert(t, pw.Events(), 500*time.Millisecond)
	if ok {
		t.Error("received unexpected AlertEvent for non-matching process")
	}
}

// TestProcessWatcher_MatchesByBasename verifies that a rule target of "bash"
// matches a process command of "/bin/bash" (basename matching).
func TestProcessWatcher_MatchesByBasename(t *testing.T) {
	pw := newTestWatcher(t, "bash", "WARN",
		&stubBackend{
			events: []ProcessEvent{
				{PID: 42, PPID: 1, UID: 0, Command: "/bin/bash"},
			},
			blockUntilDone: true,
		})

	if err := pw.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}
	defer pw.Stop()

	<-pw.Ready()

	evt, ok := waitForAlert(t, pw.Events(), 3*time.Second)
	if !ok {
		t.Fatal("no AlertEvent for full-path command matching basename rule")
	}
	assertAlertField(t, "RuleName", evt.RuleName, "bash-watch")
}

// TestProcessWatcher_MultipleRulesCanMatch verifies that a single process event
// triggers alerts for all matching rules, not just the first.
func TestProcessWatcher_MultipleRulesCanMatch(t *testing.T) {
	rules := []config.TripwireRule{
		procRule("rule-a", "nc", "WARN"),
		procRule("rule-b", "nc", "CRITICAL"),
	}
	pw := newTestWatcherWithRules(t, rules,
		&stubBackend{
			events: []ProcessEvent{
				{PID: 99, PPID: 1, UID: 0, Command: "nc"},
			},
			blockUntilDone: true,
		})

	if err := pw.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}
	defer pw.Stop()

	<-pw.Ready()

	seen := map[string]bool{}
	deadline := time.After(3 * time.Second)
	for len(seen) < 2 {
		select {
		case evt, ok := <-pw.Events():
			if !ok {
				goto done
			}
			seen[evt.RuleName] = true
		case <-deadline:
			goto done
		}
	}
done:

	if !seen["rule-a"] {
		t.Error("expected AlertEvent for rule-a, none received")
	}
	if !seen["rule-b"] {
		t.Error("expected AlertEvent for rule-b, none received")
	}
}

// TestProcessWatcher_EmptyRuleList verifies that a ProcessWatcher with no
// PROCESS rules starts and stops cleanly and emits no events.
func TestProcessWatcher_EmptyRuleList(t *testing.T) {
	// Non-PROCESS rules only — filtered to empty list.
	rules := []config.TripwireRule{
		{Name: "file-rule", Type: "FILE", Target: "/etc/passwd", Severity: "WARN"},
	}
	pw := newTestWatcherWithRules(t, rules,
		&stubBackend{
			events: []ProcessEvent{
				{PID: 1, PPID: 0, UID: 0, Command: "init"},
			},
			blockUntilDone: true,
		})

	if err := pw.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}
	defer pw.Stop()

	<-pw.Ready()

	_, ok := waitForAlert(t, pw.Events(), 300*time.Millisecond)
	if ok {
		t.Error("received unexpected AlertEvent with empty PROCESS rule list")
	}
}

// TestProcessWatcher_NoCmdlineInDetail verifies that when CmdLine is empty the
// "cmdline" key is absent from Detail (not present with an empty value).
func TestProcessWatcher_NoCmdlineInDetail(t *testing.T) {
	pw := newTestWatcher(t, "bash", "INFO",
		&stubBackend{
			events: []ProcessEvent{
				{PID: 10, PPID: 1, UID: 0, Command: "bash"}, // CmdLine intentionally empty
			},
			blockUntilDone: true,
		})

	if err := pw.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}
	defer pw.Stop()

	<-pw.Ready()

	evt, ok := waitForAlert(t, pw.Events(), 3*time.Second)
	if !ok {
		t.Fatal("no AlertEvent received")
	}

	if _, present := evt.Detail["cmdline"]; present {
		t.Error("Detail[cmdline] must be absent when CmdLine is empty")
	}
}

// TestProcessWatcher_BackendErrorDoesNotPanic verifies that a backend error
// does not panic the watcher and that Stop returns promptly.
func TestProcessWatcher_BackendErrorDoesNotPanic(t *testing.T) {
	pw := newTestWatcher(t, "bash", "INFO",
		&stubBackend{returnErr: errors.New("simulated backend failure")})

	if err := pw.Start(context.Background()); err != nil {
		t.Fatalf("Start: %v", err)
	}

	done := make(chan struct{})
	go func() {
		pw.Stop()
		close(done)
	}()

	select {
	case <-done:
	case <-time.After(5 * time.Second):
		t.Fatal("Stop did not return within 5 seconds after backend error")
	}
}

// ---------------------------------------------------------------------------
// matchProcessName unit tests
// ---------------------------------------------------------------------------

func TestMatchProcessName(t *testing.T) {
	tests := []struct {
		target      string
		processName string
		want        bool
	}{
		{"bash", "bash", true},
		{"bash", "/bin/bash", true},
		{"/bin/bash", "bash", true},
		{"/bin/bash", "/bin/bash", true},
		{"bash", "python3", false},
		{"nc", "ncat", false},
		{"sshd", "/usr/sbin/sshd", true},
	}
	for _, tc := range tests {
		got := matchProcessName(tc.target, tc.processName)
		if got != tc.want {
			t.Errorf("matchProcessName(%q, %q) = %v, want %v",
				tc.target, tc.processName, got, tc.want)
		}
	}
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// procRule is a convenience constructor for a PROCESS-type TripwireRule.
func procRule(name, target, severity string) config.TripwireRule {
	return config.TripwireRule{
		Name:     name,
		Type:     "PROCESS",
		Target:   target,
		Severity: severity,
	}
}

// newTestWatcher creates a ProcessWatcher for a single "bash-watch" rule with
// the given target and severity, using the provided backend.
func newTestWatcher(t *testing.T, target, severity string, b processBackend) *ProcessWatcher {
	t.Helper()
	return newTestWatcherWithRules(t,
		[]config.TripwireRule{procRule("bash-watch", target, severity)},
		b,
	)
}

// newTestWatcherWithRules creates a ProcessWatcher with the given rules and
// backend, bypassing newProcessBackend for deterministic tests.
func newTestWatcherWithRules(t *testing.T, rules []config.TripwireRule, b processBackend) *ProcessWatcher {
	t.Helper()

	// Filter to PROCESS rules only (mirrors NewProcessWatcher).
	var procRules []config.TripwireRule
	for _, r := range rules {
		if r.Type == "PROCESS" {
			procRules = append(procRules, r)
		}
	}

	return &ProcessWatcher{
		rules:   procRules,
		logger:  noopLogger(),
		events:  make(chan AlertEvent, 64),
		done:    make(chan struct{}),
		ready:   make(chan struct{}),
		backend: b,
	}
}

// waitForAlert reads one AlertEvent from ch within timeout. Returns the event
// and true on success, or zero value and false on timeout.
func waitForAlert(t *testing.T, ch <-chan AlertEvent, timeout time.Duration) (AlertEvent, bool) {
	t.Helper()
	select {
	case evt, ok := <-ch:
		if !ok {
			return AlertEvent{}, false
		}
		return evt, true
	case <-time.After(timeout):
		return AlertEvent{}, false
	}
}

// assertAlertField is a generic helper to check a string AlertEvent field.
func assertAlertField(t *testing.T, name, got, want string) {
	t.Helper()
	if got != want {
		t.Errorf("%s = %q, want %q", name, got, want)
	}
}

// assertDetailField checks that evt.Detail[key] equals want.
func assertDetailField(t *testing.T, detail map[string]any, key string, want any) {
	t.Helper()
	got, ok := detail[key]
	if !ok {
		t.Errorf("Detail[%q] is absent, want %v", key, want)
		return
	}
	if got != want {
		t.Errorf("Detail[%q] = %v (%T), want %v (%T)", key, got, got, want, want)
	}
}

// ---------------------------------------------------------------------------
// stubBackend — mock processBackend for testing
// ---------------------------------------------------------------------------

// stubBackend is a controllable processBackend. It sends the configured events
// once, then either blocks until done is closed (blockUntilDone == true) or
// immediately returns an error (returnErr != nil).
type stubBackend struct {
	events         []ProcessEvent
	blockUntilDone bool
	returnErr      error
}

// run implements processBackend.
func (s *stubBackend) run(done <-chan struct{}, events chan<- ProcessEvent) error {
	if s.returnErr != nil {
		return s.returnErr
	}

	for _, pe := range s.events {
		select {
		case <-done:
			return nil
		case events <- pe:
		}
	}

	if s.blockUntilDone {
		<-done
	}
	return nil
}
