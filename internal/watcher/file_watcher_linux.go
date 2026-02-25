// Package watcher contains platform-specific filesystem watcher implementations.
//
//go:build linux

package watcher

import (
	"bytes"
	"context"
	"fmt"
	"log/slog"
	"path/filepath"
	"sync"
	"syscall"
	"time"
	"unsafe"

	"github.com/tripwire/agent/internal/agent"
	"github.com/tripwire/agent/internal/config"
)

// inotifyMask is the set of inotify watch events the InotifyWatcher subscribes
// to on each target path.
//
//   - IN_ACCESS:     a file was read — useful for detecting unauthorised reads
//   - IN_MODIFY:     file content was changed
//   - IN_CLOSE_WRITE: a writable file was closed — catches buffered writes
//   - IN_CREATE:     a file was created in the watched directory
//   - IN_MOVED_TO:   a file was moved into the watched directory
//   - IN_DELETE:     a file was deleted from the watched directory
//   - IN_MOVED_FROM: a file was moved out of the watched directory
const inotifyMask uint32 = syscall.IN_ACCESS |
	syscall.IN_MODIFY |
	syscall.IN_CLOSE_WRITE |
	syscall.IN_CREATE |
	syscall.IN_MOVED_TO |
	syscall.IN_DELETE |
	syscall.IN_MOVED_FROM

// inotifyEventHeaderSize is the fixed-width portion of a raw inotify_event
// structure. The variable-length Name field (of length InotifyEvent.Len)
// follows immediately in the kernel-provided buffer.
const inotifyEventHeaderSize = int(unsafe.Sizeof(syscall.InotifyEvent{}))

// InotifyWatcher monitors filesystem paths using the Linux inotify subsystem.
// It implements [agent.Watcher] and is safe for concurrent use.
//
// Unlike the polling-based FileWatcher, InotifyWatcher registers kernel watch
// descriptors and receives event notifications immediately when a watched path
// changes, resulting in sub-millisecond detection latency.
//
// inotify does not expose the PID or UID of the process that triggered a
// change. The AlertEvent Detail map entries "pid" (set to -1) and "username"
// (set to "unknown") reflect this kernel-level limitation.
type InotifyWatcher struct {
	rules  []config.TripwireRule
	logger *slog.Logger

	fd  int           // inotify file descriptor
	wds map[int32]int // watch descriptor → index into rules

	events   chan agent.AlertEvent
	done     chan struct{}
	ready    chan struct{}
	wg       sync.WaitGroup
	stopOnce sync.Once
}

// NewInotifyWatcher creates an InotifyWatcher that monitors the target paths
// of all FILE-type rules in rules. Non-FILE rules are silently ignored. An
// error is returned if the underlying inotify instance cannot be initialised.
func NewInotifyWatcher(rules []config.TripwireRule, logger *slog.Logger) (*InotifyWatcher, error) {
	fd, err := syscall.InotifyInit1(syscall.IN_NONBLOCK | syscall.IN_CLOEXEC)
	if err != nil {
		return nil, fmt.Errorf("inotify: init: %w", err)
	}

	var fileRules []config.TripwireRule
	for _, r := range rules {
		if r.Type == "FILE" {
			fileRules = append(fileRules, r)
		}
	}

	return &InotifyWatcher{
		rules:  fileRules,
		logger: logger,
		fd:     fd,
		wds:    make(map[int32]int),
		events: make(chan agent.AlertEvent, 64),
		done:   make(chan struct{}),
		ready:  make(chan struct{}),
	}, nil
}

// Start adds inotify watches for all configured FILE rule targets and launches
// the background event-reading goroutine. It returns immediately. Use Ready()
// to wait for full initialisation before triggering filesystem operations.
func (iw *InotifyWatcher) Start(_ context.Context) error {
	for i := range iw.rules {
		r := &iw.rules[i]
		wd, err := syscall.InotifyAddWatch(iw.fd, r.Target, inotifyMask)
		if err != nil {
			iw.logger.Warn("inotify: cannot add watch",
				slog.String("path", r.Target),
				slog.Any("error", err),
			)
			continue
		}
		iw.wds[int32(wd)] = i
	}

	iw.wg.Add(1)
	go iw.run()
	return nil
}

// Stop signals the watcher to cease monitoring and blocks until the background
// goroutine exits. The Events channel is closed after Stop returns. It is safe
// to call Stop multiple times (idempotent).
func (iw *InotifyWatcher) Stop() {
	iw.stopOnce.Do(func() {
		close(iw.done)
		iw.wg.Wait()
		// Close the inotify fd only after the goroutine exits to avoid a
		// race between the goroutine's Poll/Read calls and the Close.
		_ = syscall.Close(iw.fd)
		close(iw.events)
	})
}

// Events returns the read-only channel on which AlertEvents are delivered.
// The channel is closed when Stop returns.
func (iw *InotifyWatcher) Events() <-chan agent.AlertEvent {
	return iw.events
}

// Ready returns a channel that is closed once the watcher is fully initialised
// (all inotify watches registered and the read loop started). Waiting on this
// channel before triggering filesystem operations eliminates races in tests.
func (iw *InotifyWatcher) Ready() <-chan struct{} {
	return iw.ready
}

// run is the background goroutine that polls the inotify file descriptor for
// events and dispatches them to the events channel.
func (iw *InotifyWatcher) run() {
	defer iw.wg.Done()

	// Signal readiness before entering the read loop so that callers waiting
	// on Ready() do not race with the first event.
	close(iw.ready)

	buf := make([]byte, 4096)
	pfd := []syscall.PollFd{{Fd: int32(iw.fd), Events: syscall.POLLIN}}

	for {
		// Check for stop before blocking in Poll.
		select {
		case <-iw.done:
			return
		default:
		}

		// Poll with a 100 ms timeout so that the done channel is checked
		// frequently without busy-waiting.
		n, err := syscall.Poll(pfd, 100)
		if err != nil {
			if err == syscall.EINTR {
				continue // interrupted by a signal; retry
			}
			select {
			case <-iw.done:
				return
			default:
			}
			iw.logger.Error("inotify: poll error", slog.Any("error", err))
			return
		}
		if n == 0 {
			continue // timeout; loop back to check done channel
		}

		nr, err := syscall.Read(iw.fd, buf)
		if err != nil {
			select {
			case <-iw.done:
				return
			default:
			}
			if err == syscall.EAGAIN || err == syscall.EWOULDBLOCK {
				continue
			}
			iw.logger.Error("inotify: read error", slog.Any("error", err))
			return
		}
		if nr == 0 {
			continue
		}

		iw.parseEvents(buf[:nr])
	}
}

// parseEvents decodes a buffer containing one or more consecutive raw inotify
// events and emits an AlertEvent for each trackable change.
func (iw *InotifyWatcher) parseEvents(buf []byte) {
	for offset := 0; offset < len(buf); {
		if offset+inotifyEventHeaderSize > len(buf) {
			break
		}

		// The kernel guarantees that inotify events are aligned to the size
		// of the largest member (uint32), so the unsafe cast is safe here.
		raw := (*syscall.InotifyEvent)(unsafe.Pointer(&buf[offset]))
		offset += inotifyEventHeaderSize

		// Extract the variable-length null-terminated name field, if any.
		var name string
		if raw.Len > 0 {
			end := offset + int(raw.Len)
			if end > len(buf) {
				break
			}
			nameBytes := buf[offset:end]
			// Strip trailing null bytes; the kernel pads to a 4-byte boundary.
			if i := bytes.IndexByte(nameBytes, 0); i >= 0 {
				nameBytes = nameBytes[:i]
			}
			name = string(nameBytes)
			offset = end
		}

		ruleIdx, ok := iw.wds[raw.Wd]
		if !ok {
			continue
		}
		rule := &iw.rules[ruleIdx]

		operation := inotifyMaskToOperation(raw.Mask)
		if operation == "" {
			continue
		}

		path := rule.Target
		if name != "" {
			path = filepath.Join(rule.Target, name)
		}

		iw.emit(path, operation, rule)
	}
}

// inotifyMaskToOperation maps an inotify event bitmask to a human-readable
// operation string. Returns an empty string for masks that do not correspond
// to a tracked event type.
func inotifyMaskToOperation(mask uint32) string {
	switch {
	case mask&syscall.IN_CREATE != 0, mask&syscall.IN_MOVED_TO != 0:
		return "create"
	case mask&syscall.IN_CLOSE_WRITE != 0, mask&syscall.IN_MODIFY != 0:
		return "write"
	case mask&syscall.IN_ACCESS != 0:
		return "access"
	case mask&syscall.IN_DELETE != 0, mask&syscall.IN_MOVED_FROM != 0:
		return "delete"
	default:
		return ""
	}
}

// emit constructs and dispatches an AlertEvent for the given path, operation,
// and triggering rule. If the events channel is full the event is dropped with
// a warning log rather than blocking the caller.
func (iw *InotifyWatcher) emit(path, operation string, rule *config.TripwireRule) {
	evt := agent.AlertEvent{
		TripwireType: "FILE",
		RuleName:     rule.Name,
		Severity:     rule.Severity,
		Timestamp:    time.Now().UTC(),
		Detail: map[string]any{
			"path":      path,
			"operation": operation,
			// inotify does not expose the PID or UID of the process that
			// triggered the change; sentinel values are used instead.
			"pid":      -1,
			"username": "unknown",
		},
	}

	select {
	case iw.events <- evt:
		iw.logger.Info("inotify: alert emitted",
			slog.String("rule", rule.Name),
			slog.String("path", path),
			slog.String("operation", operation),
		)
	default:
		iw.logger.Warn("inotify: event channel full, dropping event",
			slog.String("path", path),
			slog.String("operation", operation),
		)
	}
}
