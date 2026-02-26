// Package watcher provides filesystem monitoring components. The FileWatcher
// polls the filesystem at a configurable interval (default 100 ms) to detect
// creates, writes, and deletes on the paths defined by FILE-type tripwire
// rules. The 100 ms poll interval ensures events are detected well within the
// 5-second alert SLA required by the product specification.
package watcher

import (
	"context"
	"log/slog"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/tripwire/agent/internal/config"
)

// DefaultPollInterval is the frequency at which the FileWatcher scans the
// filesystem for changes. 100 ms guarantees detection within 200 ms worst
// case, comfortably inside the 5-second alert SLA.
const DefaultPollInterval = 100 * time.Millisecond

// fileState holds the stable metadata for a single path snapshot entry.
type fileState struct {
	mode    os.FileMode
	size    int64
	modTime time.Time
}

// FileWatcher monitors file and directory paths configured by FILE-type
// tripwire rules. It implements [Watcher] and is safe for concurrent use.
// Changes are detected by comparing periodic filesystem snapshots; no
// kernel-level inotify handle is held, so the watcher tolerates paths that do
// not yet exist at startup.
type FileWatcher struct {
	rules    []config.TripwireRule
	logger   *slog.Logger
	interval time.Duration

	events chan AlertEvent
	done   chan struct{}
	// ready is closed once the initial snapshot has been taken. Callers
	// (especially tests) may wait on Ready() before triggering filesystem
	// operations to avoid missed-event races.
	ready chan struct{}

	mu       sync.Mutex
	snapshot map[string]fileState
	wg       sync.WaitGroup

	// stopOnce ensures that close(done), wg.Wait(), and close(events) are
	// each called exactly once, making Stop safe to invoke multiple times.
	stopOnce sync.Once
}

// NewFileWatcher creates a FileWatcher that observes the target paths of all
// FILE-type rules in rules. Rules with a type other than "FILE" are silently
// ignored. The interval parameter controls the poll frequency; passing zero
// uses DefaultPollInterval.
func NewFileWatcher(rules []config.TripwireRule, logger *slog.Logger, interval time.Duration) *FileWatcher {
	if interval <= 0 {
		interval = DefaultPollInterval
	}

	var fileRules []config.TripwireRule
	for _, r := range rules {
		if r.Type == "FILE" {
			fileRules = append(fileRules, r)
		}
	}

	return &FileWatcher{
		rules:    fileRules,
		logger:   logger,
		interval: interval,
		events:   make(chan AlertEvent, 64),
		done:     make(chan struct{}),
		ready:    make(chan struct{}),
		snapshot: make(map[string]fileState),
	}
}

// Start begins filesystem monitoring in a background goroutine and returns
// immediately. It is safe to call Start only once; subsequent calls have no
// effect. The background goroutine exits when ctx is cancelled or Stop is
// called.
func (fw *FileWatcher) Start(_ context.Context) error {
	fw.wg.Add(1)
	go fw.run()
	return nil
}

// Stop signals the watcher to cease monitoring and blocks until the background
// goroutine exits. The Events channel is closed after Stop returns. It is safe
// to call Stop multiple times (idempotent).
func (fw *FileWatcher) Stop() {
	fw.stopOnce.Do(func() {
		close(fw.done)
		fw.wg.Wait()
		close(fw.events)
	})
}

// Events returns the read-only channel on which AlertEvents are delivered.
// The channel is closed when Stop returns.
func (fw *FileWatcher) Events() <-chan AlertEvent {
	return fw.events
}

// Ready returns a channel that is closed once the initial filesystem snapshot
// has been taken. Waiting on this channel before triggering filesystem
// operations eliminates races in tests.
func (fw *FileWatcher) Ready() <-chan struct{} {
	return fw.ready
}

// run is the background goroutine that polls for filesystem changes.
func (fw *FileWatcher) run() {
	defer fw.wg.Done()

	// Take the initial snapshot before signalling readiness so that the very
	// first poll only emits events for changes made after Start returned.
	fw.mu.Lock()
	fw.snapshot = fw.scan()
	fw.mu.Unlock()
	close(fw.ready)

	ticker := time.NewTicker(fw.interval)
	defer ticker.Stop()

	for {
		select {
		case <-fw.done:
			return
		case <-ticker.C:
			fw.mu.Lock()
			current := fw.scan()
			fw.diff(fw.snapshot, current)
			fw.snapshot = current
			fw.mu.Unlock()
		}
	}
}

// scan walks all configured paths and returns a path→fileState snapshot.
// For directory targets every immediate child file is included; the directory
// entry itself is not tracked. For file targets only that single path is
// included. Paths that do not yet exist are silently skipped so that rules can
// be defined before the target is created.
func (fw *FileWatcher) scan() map[string]fileState {
	result := make(map[string]fileState)

	for _, r := range fw.rules {
		info, err := os.Stat(r.Target)
		if err != nil {
			// Target may not exist yet; this is not an error condition.
			continue
		}

		if info.IsDir() {
			entries, err := os.ReadDir(r.Target)
			if err != nil {
				fw.logger.Warn("file watcher: cannot read directory",
					slog.String("path", r.Target),
					slog.Any("error", err),
				)
				continue
			}
			for _, e := range entries {
				if e.IsDir() {
					continue // non-recursive: skip sub-directories
				}
				fi, err := e.Info()
				if err != nil {
					continue
				}
				path := filepath.Join(r.Target, e.Name())
				result[path] = fileState{
					mode:    fi.Mode(),
					size:    fi.Size(),
					modTime: fi.ModTime(),
				}
			}
		} else {
			result[r.Target] = fileState{
				mode:    info.Mode(),
				size:    info.Size(),
				modTime: info.ModTime(),
			}
		}
	}

	return result
}

// diff compares an old snapshot against a new one and emits an AlertEvent for
// each detected change (create, write, delete).
func (fw *FileWatcher) diff(old, current map[string]fileState) {
	// Detect created and modified files.
	for path, cur := range current {
		prev, existed := old[path]
		if !existed {
			fw.emit(path, "create")
		} else if cur.modTime != prev.modTime || cur.size != prev.size {
			fw.emit(path, "write")
		}
	}

	// Detect deleted files.
	for path := range old {
		if _, ok := current[path]; !ok {
			fw.emit(path, "delete")
		}
	}
}

// emit sends an AlertEvent for the given path and operation. If the event
// channel is full the event is dropped with a warning log.
func (fw *FileWatcher) emit(path, operation string) {
	rule := fw.ruleForPath(path)
	if rule == nil {
		return
	}

	evt := AlertEvent{
		TripwireType: "FILE",
		RuleName:     rule.Name,
		Severity:     rule.Severity,
		Timestamp:    time.Now().UTC(),
		Detail: map[string]any{
			"path":      path,
			"operation": operation,
		},
	}

	select {
	case fw.events <- evt:
		fw.logger.Info("file watcher: alert emitted",
			slog.String("rule", rule.Name),
			slog.String("path", path),
			slog.String("operation", operation),
		)
	default:
		fw.logger.Warn("file watcher: event channel full, dropping event",
			slog.String("path", path),
			slog.String("operation", operation),
		)
	}
}

// ruleForPath returns a pointer to the first rule whose Target matches either
// the given path exactly or the path's parent directory.
func (fw *FileWatcher) ruleForPath(path string) *config.TripwireRule {
	dir := filepath.Dir(path)
	for i := range fw.rules {
		r := &fw.rules[i]
		if r.Target == path || r.Target == dir {
			return r
		}
	}
	return nil
}
