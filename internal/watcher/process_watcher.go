// Package watcher contains the concrete watcher implementations for the
// TripWire agent: file, network, and process monitors.
package watcher

import (
	"context"
	"log/slog"
	"os/user"
	"path/filepath"
	"strconv"
	"sync"
	"time"

	"github.com/tripwire/agent/internal/config"
)

// ProcessEvent carries information about a newly detected process execution.
// It is produced by the platform-specific process backend and consumed by
// ProcessWatcher to produce AlertEvents.
type ProcessEvent struct {
	// PID is the process identifier of the new process.
	PID int
	// PPID is the parent process identifier.
	PPID int
	// UID is the numeric user ID that owns the process.
	UID int
	// Username is the human-readable name resolved from UID. Empty when
	// the user database lookup fails.
	Username string
	// Command is the process name or executable basename (e.g. "bash").
	Command string
	// CmdLine is the full command-line string (space-joined argv). May be
	// empty if the platform backend cannot retrieve it.
	CmdLine string
}

// processBackend is the platform-specific interface for detecting new process
// executions. Each platform provides a concrete implementation via
// newProcessBackend. Implementations send ProcessEvents to the provided
// channel until done is closed, then return. They must NOT close the events
// channel.
type processBackend interface {
	// run monitors process executions and sends events until done is closed.
	// Returns nil on clean shutdown or a non-nil error on unrecoverable
	// failure.
	run(done <-chan struct{}, events chan<- ProcessEvent) error
}

// ProcessWatcher monitors process execution events and emits AlertEvents when
// a process matching a configured PROCESS-type rule is started.
//
// It attempts to use an eBPF backend first (Linux >= 5.8). When eBPF is
// unavailable it falls back to a platform-specific polling backend: /proc
// scanning on Linux and sysctl-based process enumeration on macOS.
//
// ProcessWatcher implements the Watcher interface and is safe for concurrent
// use. Start may be called only once; Stop is idempotent.
type ProcessWatcher struct {
	rules  []config.TripwireRule
	logger *slog.Logger

	events   chan AlertEvent
	done     chan struct{}
	ready    chan struct{}
	stopOnce sync.Once
	wg       sync.WaitGroup

	// backend is injected at construction time and can be replaced in tests.
	backend processBackend
}

// NewProcessWatcher creates a ProcessWatcher for the PROCESS-type rules in
// rules. Non-PROCESS rules are silently ignored. A nil logger defaults to
// slog.Default().
func NewProcessWatcher(rules []config.TripwireRule, logger *slog.Logger) *ProcessWatcher {
	if logger == nil {
		logger = slog.Default()
	}

	var procRules []config.TripwireRule
	for _, r := range rules {
		if r.Type == "PROCESS" {
			procRules = append(procRules, r)
		}
	}

	return &ProcessWatcher{
		rules:   procRules,
		logger:  logger,
		events:  make(chan AlertEvent, 64),
		done:    make(chan struct{}),
		ready:   make(chan struct{}),
		backend: newProcessBackend(logger),
	}
}

// Start begins process monitoring in a background goroutine and returns
// immediately. It is safe to call Start only once; the behaviour on subsequent
// calls is undefined.
func (pw *ProcessWatcher) Start(_ context.Context) error {
	pw.wg.Add(1)
	go pw.run()
	return nil
}

// Stop signals the watcher to cease monitoring and blocks until the background
// goroutine exits. The Events channel is closed after Stop returns. It is safe
// to call Stop multiple times (idempotent).
func (pw *ProcessWatcher) Stop() {
	pw.stopOnce.Do(func() {
		close(pw.done)
		pw.wg.Wait()
		close(pw.events)
	})
}

// Events returns the read-only channel on which AlertEvents are delivered.
// The channel is closed when Stop returns.
func (pw *ProcessWatcher) Events() <-chan AlertEvent {
	return pw.events
}

// Ready returns a channel that is closed once the initial process snapshot
// has been taken and the watcher is actively monitoring. Waiting on this
// channel before triggering processes in tests eliminates races.
func (pw *ProcessWatcher) Ready() <-chan struct{} {
	return pw.ready
}

// run is the background goroutine that mediates between the platform backend
// and the alert event pipeline.
func (pw *ProcessWatcher) run() {
	defer pw.wg.Done()

	procEvents := make(chan ProcessEvent, 64)

	// Launch the platform backend in its own goroutine.
	pw.wg.Add(1)
	go func() {
		defer pw.wg.Done()
		defer close(procEvents)
		if err := pw.backend.run(pw.done, procEvents); err != nil {
			pw.logger.Warn("process watcher: backend error",
				slog.Any("error", err))
		}
	}()

	// Signal readiness now that the backend goroutine is running.
	close(pw.ready)

	for {
		select {
		case <-pw.done:
			return
		case pe, ok := <-procEvents:
			if !ok {
				return
			}
			pw.dispatch(pe)
		}
	}
}

// dispatch checks whether pe matches any configured PROCESS rule and emits an
// AlertEvent for each match. Non-matching executions are silently dropped.
func (pw *ProcessWatcher) dispatch(pe ProcessEvent) {
	for i := range pw.rules {
		r := &pw.rules[i]
		if matchProcessName(r.Target, pe.Command) {
			pw.emit(pe, r)
		}
	}
}

// matchProcessName reports whether processName matches the rule target. The
// comparison uses the basename of both strings so that a rule target of "bash"
// matches "/bin/bash" and vice versa.
func matchProcessName(target, processName string) bool {
	if target == processName {
		return true
	}
	return filepath.Base(target) == filepath.Base(processName)
}

// emit sends an AlertEvent for the given process execution to the events
// channel. If the channel buffer is full the event is dropped with a warning
// log rather than blocking the caller.
func (pw *ProcessWatcher) emit(pe ProcessEvent, rule *config.TripwireRule) {
	detail := map[string]any{
		"pid":     pe.PID,
		"ppid":    pe.PPID,
		"uid":     pe.UID,
		"command": pe.Command,
	}
	if pe.CmdLine != "" {
		detail["cmdline"] = pe.CmdLine
	}
	if pe.Username != "" {
		detail["username"] = pe.Username
	}

	evt := AlertEvent{
		TripwireType: "PROCESS",
		RuleName:     rule.Name,
		Severity:     rule.Severity,
		Timestamp:    time.Now().UTC(),
		Detail:       detail,
	}

	select {
	case pw.events <- evt:
		pw.logger.Info("process watcher: alert emitted",
			slog.String("rule", rule.Name),
			slog.String("command", pe.Command),
			slog.Int("pid", pe.PID),
		)
	default:
		pw.logger.Warn("process watcher: event channel full, dropping alert",
			slog.String("command", pe.Command),
			slog.Int("pid", pe.PID),
		)
	}
}

// resolveUsername converts a numeric UID to a username via the OS user
// database. Returns empty string on lookup failure.
func resolveUsername(uid int) string {
	u, err := user.LookupId(strconv.Itoa(uid))
	if err != nil {
		return ""
	}
	return u.Username
}
