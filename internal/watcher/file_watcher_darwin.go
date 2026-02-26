// Package watcher contains platform-specific filesystem watcher implementations.
//
//go:build darwin

package watcher

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"sync"
	"syscall"
	"time"

	"github.com/tripwire/agent/internal/agent"
	"github.com/tripwire/agent/internal/config"
)

// kqueueFflags is the set of vnode events the KqueueWatcher subscribes to on
// file targets:
//
//   - NOTE_WRITE:  file data was modified
//   - NOTE_EXTEND: file size increased
//   - NOTE_ATTRIB: file metadata (e.g. permissions, timestamps) changed
//   - NOTE_DELETE: file was deleted
//   - NOTE_RENAME: file was renamed or moved away
const kqueueFileFflags uint32 = syscall.NOTE_WRITE |
	syscall.NOTE_EXTEND |
	syscall.NOTE_ATTRIB |
	syscall.NOTE_DELETE |
	syscall.NOTE_RENAME

// kqueueDirFflags is the set of vnode events subscribed to on directory
// targets. NOTE_WRITE fires whenever the directory contents change (file
// created or deleted). A snapshot diff then determines what changed.
const kqueueDirFflags uint32 = syscall.NOTE_WRITE |
	syscall.NOTE_DELETE |
	syscall.NOTE_RENAME

// kqueueEntry records metadata for a single kqueue-watched file descriptor.
type kqueueEntry struct {
	fd      int
	target  string // original rule Target path
	ruleIdx int    // index into KqueueWatcher.rules
	isDir   bool

	// snapshot is non-nil only for directory targets. It holds the
	// filename → fileState map from the most recent directory scan and is
	// used to diff against the current state when NOTE_WRITE fires.
	snapshot map[string]fileState
}

// KqueueWatcher monitors filesystem paths using the macOS kqueue subsystem.
// It implements [agent.Watcher] and is safe for concurrent use.
//
// For file targets, KqueueWatcher registers EVFILT_VNODE kevent filters and
// receives immediate notifications on write, delete, rename, and attribute
// changes. For directory targets, it receives NOTE_WRITE on the directory fd
// and performs a snapshot diff to determine which child files changed.
//
// kqueue does not expose the PID or UID of the process that triggered a
// change. The AlertEvent Detail map entries "pid" (set to -1) and "username"
// (set to "unknown") reflect this limitation.
type KqueueWatcher struct {
	rules  []config.TripwireRule
	logger *slog.Logger

	kqfd    int              // kqueue file descriptor
	entries []*kqueueEntry   // ordered list of watched paths
	fdMap   map[int]*kqueueEntry // watched fd → entry (for O(1) lookup)

	events   chan agent.AlertEvent
	done     chan struct{}
	ready    chan struct{}
	wg       sync.WaitGroup
	stopOnce sync.Once
}

// NewKqueueWatcher creates a KqueueWatcher that monitors the target paths of
// all FILE-type rules in rules. Non-FILE rules are silently ignored. An error
// is returned if a kqueue instance cannot be created.
func NewKqueueWatcher(rules []config.TripwireRule, logger *slog.Logger) (*KqueueWatcher, error) {
	kqfd, err := syscall.Kqueue()
	if err != nil {
		return nil, fmt.Errorf("kqueue: create: %w", err)
	}

	var fileRules []config.TripwireRule
	for _, r := range rules {
		if r.Type == "FILE" {
			fileRules = append(fileRules, r)
		}
	}

	return &KqueueWatcher{
		rules:   fileRules,
		logger:  logger,
		kqfd:    kqfd,
		fdMap:   make(map[int]*kqueueEntry),
		events:  make(chan agent.AlertEvent, 64),
		done:    make(chan struct{}),
		ready:   make(chan struct{}),
	}, nil
}

// Start opens file descriptors for all configured FILE rule targets, registers
// kqueue EVFILT_VNODE filters, and launches the background event loop. It
// returns immediately. Use Ready() to wait for full initialisation.
func (kw *KqueueWatcher) Start(_ context.Context) error {
	changes := make([]syscall.Kevent_t, 0, len(kw.rules))

	for i := range kw.rules {
		r := &kw.rules[i]

		fd, err := syscall.Open(r.Target, syscall.O_RDONLY|syscall.O_NONBLOCK|syscall.O_CLOEXEC, 0)
		if err != nil {
			kw.logger.Warn("kqueue: cannot open watch target",
				slog.String("path", r.Target),
				slog.Any("error", err),
			)
			continue
		}

		info, err := os.Stat(r.Target)
		if err != nil {
			_ = syscall.Close(fd)
			continue
		}
		isDir := info.IsDir()

		fflags := kqueueFileFflags
		if isDir {
			fflags = kqueueDirFflags
		}

		entry := &kqueueEntry{
			fd:      fd,
			target:  r.Target,
			ruleIdx: i,
			isDir:   isDir,
		}
		if isDir {
			entry.snapshot = kw.scanDir(r.Target)
		}

		kw.entries = append(kw.entries, entry)
		kw.fdMap[fd] = entry

		// Prepare the changelist entry to register this fd with kqueue.
		changes = append(changes, syscall.Kevent_t{
			Ident:  uint64(fd),
			Filter: syscall.EVFILT_VNODE,
			Flags:  syscall.EV_ADD | syscall.EV_ENABLE | syscall.EV_CLEAR,
			Fflags: fflags,
		})
	}

	// Submit all watch registrations in a single Kevent call.
	if len(changes) > 0 {
		_, err := syscall.Kevent(kw.kqfd, changes, nil, nil)
		if err != nil {
			kw.logger.Warn("kqueue: error registering watches", slog.Any("error", err))
		}
	}

	kw.wg.Add(1)
	go kw.run()
	return nil
}

// Stop signals the watcher to cease monitoring and blocks until the background
// goroutine exits. The Events channel is closed after Stop returns. It is safe
// to call Stop multiple times (idempotent).
func (kw *KqueueWatcher) Stop() {
	kw.stopOnce.Do(func() {
		close(kw.done)
		kw.wg.Wait()
		// Close the kqueue fd and all watched fds after the goroutine exits.
		_ = syscall.Close(kw.kqfd)
		for _, e := range kw.entries {
			_ = syscall.Close(e.fd)
		}
		close(kw.events)
	})
}

// Events returns the read-only channel on which AlertEvents are delivered.
// The channel is closed when Stop returns.
func (kw *KqueueWatcher) Events() <-chan agent.AlertEvent {
	return kw.events
}

// Ready returns a channel that is closed once the watcher is fully initialised
// (all kqueue filters registered and the event loop started). Waiting on this
// channel before triggering filesystem operations eliminates races in tests.
func (kw *KqueueWatcher) Ready() <-chan struct{} {
	return kw.ready
}

// run is the background goroutine that waits for kqueue events and dispatches
// AlertEvents for each detected filesystem change.
func (kw *KqueueWatcher) run() {
	defer kw.wg.Done()
	close(kw.ready)

	events := make([]syscall.Kevent_t, 16)
	// 100 ms timeout — balances responsiveness with CPU efficiency.
	timeout := syscall.Timespec{Nsec: 100_000_000}

	for {
		select {
		case <-kw.done:
			return
		default:
		}

		n, err := syscall.Kevent(kw.kqfd, nil, events, &timeout)
		if err != nil {
			if err == syscall.EINTR {
				continue
			}
			select {
			case <-kw.done:
				return
			default:
			}
			kw.logger.Error("kqueue: Kevent error", slog.Any("error", err))
			return
		}

		for i := 0; i < n; i++ {
			kw.handleKevent(events[i])
		}
	}
}

// handleKevent dispatches a single kqueue event to the appropriate handler
// based on whether the target is a file or a directory.
func (kw *KqueueWatcher) handleKevent(ev syscall.Kevent_t) {
	entry, ok := kw.fdMap[int(ev.Ident)]
	if !ok {
		return
	}
	rule := &kw.rules[entry.ruleIdx]

	if entry.isDir {
		kw.handleDirEvent(ev, entry, rule)
	} else {
		kw.handleFileEvent(ev, entry, rule)
	}
}

// handleFileEvent processes a kqueue event on a file (non-directory) target.
func (kw *KqueueWatcher) handleFileEvent(ev syscall.Kevent_t, entry *kqueueEntry, rule *config.TripwireRule) {
	var operation string
	switch {
	case ev.Fflags&syscall.NOTE_DELETE != 0, ev.Fflags&syscall.NOTE_RENAME != 0:
		operation = "delete"
	case ev.Fflags&syscall.NOTE_WRITE != 0,
		ev.Fflags&syscall.NOTE_EXTEND != 0,
		ev.Fflags&syscall.NOTE_ATTRIB != 0:
		operation = "write"
	default:
		return
	}
	kw.emit(entry.target, operation, rule)
}

// handleDirEvent processes a kqueue event on a directory target. For
// NOTE_WRITE, it scans the current directory contents and diffs against the
// previous snapshot to emit per-file create/write/delete events.
func (kw *KqueueWatcher) handleDirEvent(ev syscall.Kevent_t, entry *kqueueEntry, rule *config.TripwireRule) {
	switch {
	case ev.Fflags&syscall.NOTE_DELETE != 0, ev.Fflags&syscall.NOTE_RENAME != 0:
		// Directory itself was removed or renamed. Emit a delete event for
		// the directory target and clear the snapshot.
		kw.emit(entry.target, "delete", rule)
		entry.snapshot = nil
		return
	case ev.Fflags&syscall.NOTE_WRITE != 0:
		// Directory contents changed — perform a snapshot diff.
		current := kw.scanDir(entry.target)
		prev := entry.snapshot
		if prev == nil {
			prev = make(map[string]fileState)
		}
		entry.snapshot = current
		kw.diffDirSnapshots(prev, current, entry.target, rule)
	}
}

// diffDirSnapshots compares two directory snapshots and emits AlertEvents for
// each detected create, write, or delete.
func (kw *KqueueWatcher) diffDirSnapshots(old, current map[string]fileState, dirPath string, rule *config.TripwireRule) {
	// Detect created and modified files.
	for name, cur := range current {
		prev, existed := old[name]
		if !existed {
			kw.emit(filepath.Join(dirPath, name), "create", rule)
		} else if cur.modTime != prev.modTime || cur.size != prev.size {
			kw.emit(filepath.Join(dirPath, name), "write", rule)
		}
	}
	// Detect deleted files.
	for name := range old {
		if _, ok := current[name]; !ok {
			kw.emit(filepath.Join(dirPath, name), "delete", rule)
		}
	}
}

// scanDir returns a filename → fileState map for all immediate (non-directory)
// children of dirPath. Errors and missing paths are handled gracefully.
func (kw *KqueueWatcher) scanDir(dirPath string) map[string]fileState {
	result := make(map[string]fileState)
	entries, err := os.ReadDir(dirPath)
	if err != nil {
		kw.logger.Warn("kqueue: cannot read directory",
			slog.String("path", dirPath),
			slog.Any("error", err),
		)
		return result
	}
	for _, e := range entries {
		if e.IsDir() {
			continue // non-recursive: skip sub-directories
		}
		fi, err := e.Info()
		if err != nil {
			continue
		}
		result[e.Name()] = fileState{
			mode:    fi.Mode(),
			size:    fi.Size(),
			modTime: fi.ModTime(),
		}
	}
	return result
}

// emit constructs and dispatches an AlertEvent for the given path, operation,
// and triggering rule. If the events channel is full the event is dropped with
// a warning log rather than blocking the caller.
func (kw *KqueueWatcher) emit(path, operation string, rule *config.TripwireRule) {
	evt := agent.AlertEvent{
		TripwireType: "FILE",
		RuleName:     rule.Name,
		Severity:     rule.Severity,
		Timestamp:    time.Now().UTC(),
		Detail: map[string]any{
			"path":      path,
			"operation": operation,
			// kqueue does not expose the PID or UID of the triggering process;
			// sentinel values are used instead.
			"pid":      -1,
			"username": "unknown",
		},
	}

	select {
	case kw.events <- evt:
		kw.logger.Info("kqueue: alert emitted",
			slog.String("rule", rule.Name),
			slog.String("path", path),
			slog.String("operation", operation),
		)
	default:
		kw.logger.Warn("kqueue: event channel full, dropping event",
			slog.String("path", path),
			slog.String("operation", operation),
		)
	}
}
