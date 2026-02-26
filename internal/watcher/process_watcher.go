// Package watcher contains the concrete watcher implementations for the
// TripWire agent: file, network, and process monitors.
//
// Platform support:
//
//   - Linux: NETLINK_CONNECTOR process connector (kernel-driven, zero-polling).
//     The companion eBPF C program in internal/watcher/ebpf/process.bpf.c
//     documents the equivalent BPF tracepoint implementation.
//   - macOS: kqueue EVFILT_PROC / NOTE_EXEC with periodic ps(1) scan fallback.
//   - Other: ps(1) polling at a fixed interval.
//
// ProcessWatcher is safe for concurrent use.
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

// backendStarter is an optional interface that processBackend implementations
// may satisfy to perform privileged initialisation (e.g. opening a raw socket)
// before the monitoring goroutine is launched. If the backend implements this
// interface, Start calls start first and returns any error immediately —
// preventing the background goroutine from launching on failure.
type backendStarter interface {
	start(ctx context.Context) error
}

// ProcessWatcher monitors process execution events and emits AlertEvents when
// a process matching a configured PROCESS-type rule is started.
//
// It uses the best available kernel interface for the current platform
// (NETLINK_CONNECTOR on Linux, kqueue on macOS, ps(1) polling elsewhere).
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
// immediately. If the backend implements backendStarter, its start method is
// called first; any error is returned without launching the goroutine.
// It is safe to call Start only once; subsequent calls have undefined behaviour.
func (pw *ProcessWatcher) Start(ctx context.Context) error {
	// Allow the backend to perform privileged initialisation (e.g. opening a
	// NETLINK_CONNECTOR socket on Linux) and surface errors before launching
	// the background goroutine.
	if s, ok := pw.backend.(backendStarter); ok {
		if err := s.start(ctx); err != nil {
			return err
		}
	}
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

// matchProcessName reports whether processName matches the rule target.
//
// Matching rules (in order):
//  1. Empty target matches every process (catch-all wildcard).
//  2. Exact string equality: target == processName.
//  3. Basename equality: filepath.Base(target) == filepath.Base(processName).
//  4. Glob pattern against basename: filepath.Match(target, basename).
//  5. Glob pattern against full path: filepath.Match(target, processName).
func matchProcessName(target, processName string) bool {
	if target == "" {
		return true // empty target is a catch-all wildcard
	}
	if target == processName {
		return true
	}
	base := filepath.Base(processName)
	if filepath.Base(target) == base {
		return true
	}
	if ok, _ := filepath.Match(target, base); ok {
		return true
	}
	if ok, _ := filepath.Match(target, processName); ok {
		return true
	}
	return false
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
