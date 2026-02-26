package watcher

import (
	"context"
	"fmt"
	"log/slog"
	"path/filepath"
	"sync"
	"time"

	"github.com/tripwire/agent/internal/agent"
	"github.com/tripwire/agent/internal/config"
)

// platformWatcherFunc is the signature of the platform-specific file watching
// function. It must send FileEvents to events until ctx is cancelled or an
// error occurs, then return. It must NOT close the events channel.
type platformWatcherFunc func(ctx context.Context, paths []string, events chan<- FileEvent) error

// FileWatcher implements agent.Watcher for file system monitoring. It wraps a
// platform-specific watching backend and adds goroutine lifecycle management
// with automatic restart on error.
type FileWatcher struct {
	rule            config.TripwireRule
	logger          *slog.Logger
	events          chan agent.AlertEvent
	cancel          context.CancelFunc
	done            chan struct{}
	mu              sync.Mutex
	started         bool
	platformWatcher platformWatcherFunc
}

// NewFileWatcher creates a FileWatcher for the given TripwireRule. The watcher
// is idle until Start is called.
func NewFileWatcher(rule config.TripwireRule, logger *slog.Logger) *FileWatcher {
	return &FileWatcher{
		rule:            rule,
		logger:          logger,
		events:          make(chan agent.AlertEvent, 64),
		platformWatcher: startPlatformWatcher,
	}
}

// Start begins monitoring the paths configured in the rule. It launches a
// background goroutine and returns immediately. If the path glob matches
// nothing, the parent directory is watched and the watcher waits for the
// file(s) to be created.
//
// Returns an error if the rule target is an invalid glob or if Start has
// already been called on this instance.
func (fw *FileWatcher) Start(ctx context.Context) error {
	fw.mu.Lock()
	defer fw.mu.Unlock()

	if fw.started {
		return fmt.Errorf("file watcher %q: already started", fw.rule.Name)
	}

	paths, err := fw.resolvePaths()
	if err != nil {
		return err
	}

	watchCtx, cancel := context.WithCancel(ctx)
	fw.cancel = cancel
	fw.done = make(chan struct{})
	fw.started = true

	go fw.watchLoop(watchCtx, paths)
	return nil
}

// resolvePaths expands the rule's Target glob into a list of existing paths.
// If no paths match, the parent directory is returned so that the watcher can
// detect file creation.
func (fw *FileWatcher) resolvePaths() ([]string, error) {
	paths, err := filepath.Glob(fw.rule.Target)
	if err != nil {
		return nil, fmt.Errorf("file watcher %q: invalid glob %q: %w", fw.rule.Name, fw.rule.Target, err)
	}

	if len(paths) == 0 {
		// The target doesn't exist yet — watch the parent directory so we
		// can detect creation events.
		dir := filepath.Dir(fw.rule.Target)
		fw.logger.Info("file watcher: glob matches nothing, watching parent directory",
			slog.String("rule", fw.rule.Name),
			slog.String("glob", fw.rule.Target),
			slog.String("dir", dir),
		)
		paths = []string{dir}
	}

	return paths, nil
}

// watchLoop is the background goroutine. It runs the platform watcher in a
// loop, restarting with exponential backoff whenever an error occurs. It exits
// cleanly when ctx is cancelled.
func (fw *FileWatcher) watchLoop(ctx context.Context, paths []string) {
	// Signal the events channel and done channel on exit so downstream
	// consumers and Stop() callers can unblock.
	defer func() {
		close(fw.events)
		close(fw.done)
	}()

	backoff := time.Second
	const maxBackoff = 30 * time.Second

	for {
		// Check for cancellation before (re-)starting.
		select {
		case <-ctx.Done():
			return
		default:
		}

		watchErr := fw.runWatcher(ctx, paths)
		if watchErr == nil {
			// Clean exit (context cancelled or platform watcher finished without error).
			return
		}

		// Platform watcher returned an error; restart after backoff.
		fw.logger.Warn("file watcher error, restarting",
			slog.String("rule", fw.rule.Name),
			slog.Any("error", watchErr),
			slog.Duration("backoff", backoff),
		)

		select {
		case <-time.After(backoff):
			backoff = min(backoff*2, maxBackoff)
		case <-ctx.Done():
			return
		}
	}
}

// runWatcher starts the platform-specific watcher in a goroutine and
// forwards FileEvents to the agent alert pipeline until the platform watcher
// exits or ctx is cancelled. Returns nil on clean shutdown, non-nil on error.
func (fw *FileWatcher) runWatcher(ctx context.Context, paths []string) error {
	fileEvents := make(chan FileEvent, 64)
	errCh := make(chan error, 1)

	watchCtx, watchCancel := context.WithCancel(ctx)
	defer watchCancel()

	go func() {
		errCh <- fw.platformWatcher(watchCtx, paths, fileEvents)
	}()

	for {
		select {
		case <-ctx.Done():
			// Outer context cancelled; signal the platform watcher and wait.
			watchCancel()
			<-errCh
			return nil

		case fe := <-fileEvents:
			fw.emitAlert(fe)

		case err := <-errCh:
			// Platform watcher finished. Drain any buffered events first.
			for {
				select {
				case fe := <-fileEvents:
					fw.emitAlert(fe)
				default:
					return err
				}
			}
		}
	}
}

// emitAlert converts a FileEvent into an agent.AlertEvent and forwards it to
// the event channel. If the channel buffer is full the event is dropped and
// a warning is logged.
func (fw *FileWatcher) emitAlert(fe FileEvent) {
	detail := map[string]any{
		"path":       fe.FilePath,
		"event_type": eventTypeName(fe.EventType),
	}
	if fe.PID != 0 {
		detail["pid"] = fe.PID
	}
	if fe.UID != 0 {
		detail["uid"] = fe.UID
	}
	if fe.Username != "" {
		detail["username"] = fe.Username
	}

	evt := agent.AlertEvent{
		TripwireType: "FILE",
		RuleName:     fw.rule.Name,
		Severity:     fw.rule.Severity,
		Timestamp:    fe.Timestamp,
		Detail:       detail,
	}

	select {
	case fw.events <- evt:
	default:
		fw.logger.Warn("file watcher: event buffer full, dropping event",
			slog.String("rule", fw.rule.Name),
			slog.String("path", fe.FilePath),
		)
	}
}

// Stop signals the watcher to stop monitoring and blocks until all internal
// goroutines have exited. It is safe to call Stop multiple times and before
// Start has been called.
func (fw *FileWatcher) Stop() {
	fw.mu.Lock()
	started := fw.started
	fw.mu.Unlock()

	if !started {
		return
	}

	fw.cancel()
	<-fw.done
}

// Events returns the read-only channel on which alert events are delivered.
// The channel is closed when the watcher stops.
func (fw *FileWatcher) Events() <-chan agent.AlertEvent {
	return fw.events
}

// eventTypeName returns a human-readable string for an EventType.
func eventTypeName(et EventType) string {
	switch et {
	case EventRead:
		return "read"
	case EventWrite:
		return "write"
	case EventCreate:
		return "create"
	case EventDelete:
		return "delete"
	default:
		return "unknown"
	}
}
