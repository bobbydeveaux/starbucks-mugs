// Package watcher contains the TripWire process watcher, which traces execve
// syscalls using a kernel-level mechanism and implements the agent.Watcher
// interface.
//
// Platform support:
//
//   - Linux: NETLINK_CONNECTOR process connector (kernel-driven, zero-polling).
//     The companion eBPF C program in bpf/execve.c documents the equivalent
//     BPF tracepoint implementation for environments with BPF compiler tooling.
//   - macOS/Darwin: kqueue EVFILT_PROC with NOTE_EXEC + periodic process-list
//     poll (fallback; per-PID subscription, no system-wide subscription).
//   - Other: a stub that returns an error on Start.
//
// ProcessWatcher is safe for concurrent use.
package watcher

import (
	"log/slog"
	"path/filepath"
	"sync"
	"time"

	"github.com/tripwire/agent/internal/agent"
	"github.com/tripwire/agent/internal/config"
)

// ProcessWatcher monitors process execve events and emits AlertEvents for any
// execve that matches a configured PROCESS rule. On Linux it uses the
// NETLINK_CONNECTOR kernel process connector to receive PROC_EVENT_EXEC
// notifications with zero polling overhead. See bpf/execve.c for the
// equivalent eBPF tracepoint implementation.
//
// Start requires CAP_NET_ADMIN (or root) on Linux.
type ProcessWatcher struct {
	rules  []config.TripwireRule // filtered to Type == "PROCESS"
	logger *slog.Logger

	events   chan agent.AlertEvent
	mu       sync.Mutex
	cancel   func() // non-nil while running; platform files set this
	stopOnce sync.Once
	wg       sync.WaitGroup
}

// NewProcessWatcher creates a ProcessWatcher from the PROCESS-type rules in
// rules. Non-PROCESS rules are silently ignored. If logger is nil,
// slog.Default() is used. The returned watcher is not yet started; call Start
// to begin monitoring.
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
		rules:  procRules,
		logger: logger,
		events: make(chan agent.AlertEvent, 64),
	}
}

// Events returns a read-only channel from which callers receive AlertEvents.
// The channel is closed when the watcher stops (after Stop returns).
func (w *ProcessWatcher) Events() <-chan agent.AlertEvent {
	return w.events
}

// matchingRule returns the first ProcessRule whose Target pattern matches
// procName. The match is attempted against the base name first, then against
// the full path. Returns nil when no rule matches.
//
// An empty Target in a rule is treated as "*" (matches every process).
func (w *ProcessWatcher) matchingRule(procName string) *config.TripwireRule {
	base := filepath.Base(procName)
	for i := range w.rules {
		r := &w.rules[i]
		pat := r.Target
		if pat == "" {
			return r // empty pattern matches everything
		}
		if ok, _ := filepath.Match(pat, base); ok {
			return r
		}
		if ok, _ := filepath.Match(pat, procName); ok {
			return r
		}
	}
	return nil
}

// emit delivers an AlertEvent to the events channel without blocking. If the
// buffer is full the event is dropped and a warning is logged.
func (w *ProcessWatcher) emit(evt agent.AlertEvent) {
	select {
	case w.events <- evt:
	default:
		w.logger.Warn("process watcher: event channel full, dropping event",
			slog.String("rule", evt.RuleName),
			slog.Time("ts", evt.Timestamp),
		)
	}
}

// emitExecEvent constructs an AlertEvent for the given process and, if it
// matches a rule, delivers it via emit. Called by the platform-specific loop.
func (w *ProcessWatcher) emitExecEvent(pid int, comm, exe, cmdline string) {
	// Try matching against exe first (full path), then comm (short name).
	rule := w.matchingRule(exe)
	if rule == nil {
		rule = w.matchingRule(comm)
	}
	if rule == nil {
		// No configured rule matches this process.
		return
	}

	detail := map[string]any{
		"pid":  pid,
		"comm": comm,
		"exe":  exe,
	}
	if cmdline != "" {
		detail["cmdline"] = cmdline
	}

	w.emit(agent.AlertEvent{
		TripwireType: "PROCESS",
		RuleName:     rule.Name,
		Severity:     rule.Severity,
		Timestamp:    time.Now().UTC(),
		Detail:       detail,
	})

	w.logger.Info("process watcher: execve alert",
		slog.String("rule", rule.Name),
		slog.Int("pid", pid),
		slog.String("exe", exe),
		slog.String("comm", comm),
	)
}
