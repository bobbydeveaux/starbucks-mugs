// Package watcher provides filesystem monitoring components that implement
// the agent.Watcher interface.
//
//go:build linux

package watcher

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"syscall"
	"time"
	"unsafe"

	"github.com/tripwire/agent/internal/agent"
	"github.com/tripwire/agent/internal/config"
)

// Linux inotify event flag constants (kernel ABI — never change).
// These match the values in <sys/inotify.h>.
const (
	inCreate    uint32 = 0x100        // IN_CREATE: file/dir created in watched dir
	inClosew    uint32 = 0x8          // IN_CLOSE_WRITE: writable file closed
	inDelete    uint32 = 0x200        // IN_DELETE: file/dir deleted from watched dir
	inMovedFrom uint32 = 0x40         // IN_MOVED_FROM: file moved out of watched dir
	inMovedTo   uint32 = 0x80         // IN_MOVED_TO: file moved into watched dir
	inMoveSelf  uint32 = 0x800        // IN_MOVE_SELF: watched file itself was moved
	inIsDir     uint32 = 0x40000000   // IN_ISDIR: subject of event is a directory
	inQOverflow uint32 = 0x4000       // IN_Q_OVERFLOW: event queue overflowed
)

// inotify flag for InotifyInit1: close-on-exec.
// Equivalent to O_CLOEXEC (0x80000) used as an inotify init flag.
const inotifyCloexec = 0x80000 // IN_CLOEXEC

// dirMask is the inotify event mask applied to directory-target watches.
const dirMask uint32 = inCreate | inClosew | inDelete | inMovedFrom | inMovedTo

// fileMask is the inotify event mask applied to single-file-target watches.
const fileMask uint32 = inClosew | inDelete | inMoveSelf

// inotifyEventSize is the fixed size of the inotify_event header (excl. name).
var inotifyEventSize = int(unsafe.Sizeof(syscall.InotifyEvent{}))

// watchTarget holds the metadata for a single inotify watch descriptor.
type watchTarget struct {
	rule  config.TripwireRule
	isDir bool
}

// InotifyWatcher monitors filesystem paths using the Linux inotify API.
// Unlike the polling-based FileWatcher, it receives kernel-level notifications
// with sub-millisecond latency — far within the 5-second alert SLA.
//
// It implements the agent.Watcher interface and provides an additional Ready()
// channel (matching the FileWatcher convention) that is closed once all initial
// inotify watches have been registered.
//
// Limitation: paths that do not exist when Start is called cannot be watched
// until they appear. Use FileWatcher when you need to monitor paths that may
// be created after the agent starts.
type InotifyWatcher struct {
	rules  []config.TripwireRule
	logger *slog.Logger

	// inotifyFd is the file descriptor returned by InotifyInit1.
	inotifyFd int
	// pipeR/pipeW form a self-pipe: Stop() writes a byte to pipeW, which
	// unblocks the poll(2) call in run() waiting on pipeR.
	pipeR int
	pipeW int

	mu      sync.Mutex
	targets map[int]watchTarget // watch descriptor → target metadata

	events   chan agent.AlertEvent
	ready    chan struct{}
	stopOnce sync.Once
	wg       sync.WaitGroup
}

// NewInotifyWatcher creates an InotifyWatcher for the FILE-type rules in
// rules. Non-FILE rules are silently ignored. Returns an error if the inotify
// kernel interface is unavailable (extremely rare on Linux ≥ 2.6.36).
func NewInotifyWatcher(rules []config.TripwireRule, logger *slog.Logger) (*InotifyWatcher, error) {
	ifd, err := syscall.InotifyInit1(inotifyCloexec)
	if err != nil {
		return nil, fmt.Errorf("inotify watcher: InotifyInit1: %w", err)
	}

	var pipeFds [2]int
	if err := syscall.Pipe2(pipeFds[:], syscall.O_CLOEXEC); err != nil {
		syscall.Close(ifd)
		return nil, fmt.Errorf("inotify watcher: pipe2: %w", err)
	}

	var fileRules []config.TripwireRule
	for _, r := range rules {
		if r.Type == "FILE" {
			fileRules = append(fileRules, r)
		}
	}

	return &InotifyWatcher{
		rules:     fileRules,
		logger:    logger,
		inotifyFd: ifd,
		pipeR:     pipeFds[0],
		pipeW:     pipeFds[1],
		targets:   make(map[int]watchTarget),
		events:    make(chan agent.AlertEvent, 64),
		ready:     make(chan struct{}),
	}, nil
}

// Start registers inotify watches for all configured paths and begins
// monitoring in a background goroutine. Returns immediately. It is safe to
// call Start only once.
func (w *InotifyWatcher) Start(_ context.Context) error {
	w.wg.Add(1)
	go w.run()
	return nil
}

// Stop signals the watcher to cease monitoring and blocks until the background
// goroutine exits. The Events channel is closed after Stop returns. It is safe
// to call Stop multiple times (idempotent).
func (w *InotifyWatcher) Stop() {
	w.stopOnce.Do(func() {
		// Write one byte to the self-pipe to unblock poll(2) in run().
		syscall.Write(w.pipeW, []byte{0}) //nolint:errcheck
		w.wg.Wait()
		syscall.Close(w.pipeW)
		syscall.Close(w.pipeR)
		syscall.Close(w.inotifyFd)
		close(w.events)
	})
}

// Events returns the read-only channel on which AlertEvents are delivered.
// The channel is closed when Stop returns.
func (w *InotifyWatcher) Events() <-chan agent.AlertEvent {
	return w.events
}

// Ready returns a channel that is closed once the initial inotify watches have
// been registered. Waiting on Ready() before triggering filesystem operations
// in tests eliminates races where an event might be missed.
func (w *InotifyWatcher) Ready() <-chan struct{} {
	return w.ready
}

// run is the background goroutine that reads inotify events via poll(2).
func (w *InotifyWatcher) run() {
	defer w.wg.Done()

	w.registerWatches()
	close(w.ready)

	// Buffer large enough for many events. Each event is
	// SizeofInotifyEvent (16 bytes) + up to NAME_MAX+1 (256) bytes for
	// the filename field.
	const bufSize = 4096 * (16 + 256)
	buf := make([]byte, bufSize)

	// Use poll(2) to multiplex between inotify events (inotifyFd) and the
	// shutdown signal (pipeR). Timeout of -1 means block indefinitely.
	pollFds := []syscall.PollFd{
		{Fd: int32(w.inotifyFd), Events: syscall.POLLIN},
		{Fd: int32(w.pipeR), Events: syscall.POLLIN},
	}

	for {
		_, err := syscall.Poll(pollFds, -1)
		if err != nil {
			if err == syscall.EINTR {
				continue // signal interrupted the syscall; retry
			}
			w.logger.Warn("inotify watcher: poll error", slog.Any("error", err))
			return
		}

		// Shutdown signal received via self-pipe.
		if pollFds[1].Revents&syscall.POLLIN != 0 {
			return
		}

		if pollFds[0].Revents&syscall.POLLIN == 0 {
			continue
		}

		n, err := syscall.Read(w.inotifyFd, buf)
		if err != nil {
			w.logger.Warn("inotify watcher: read error", slog.Any("error", err))
			return
		}

		w.parseAndDispatch(buf[:n])
	}
}

// registerWatches calls InotifyAddWatch for each configured FILE rule target.
// Paths that do not exist at startup are logged at debug level and skipped;
// they will not be monitored unless the watcher is restarted after they appear.
func (w *InotifyWatcher) registerWatches() {
	w.mu.Lock()
	defer w.mu.Unlock()

	for _, r := range w.rules {
		info, err := os.Stat(r.Target)
		if err != nil {
			w.logger.Debug("inotify watcher: target not accessible at startup; skipping",
				slog.String("path", r.Target),
				slog.Any("error", err))
			continue
		}

		isDir := info.IsDir()
		mask := dirMask
		if !isDir {
			mask = fileMask
		}

		wd, err := syscall.InotifyAddWatch(w.inotifyFd, r.Target, mask)
		if err != nil {
			w.logger.Warn("inotify watcher: InotifyAddWatch failed",
				slog.String("path", r.Target),
				slog.Any("error", err))
			continue
		}

		rule := r // capture loop variable
		w.targets[wd] = watchTarget{rule: rule, isDir: isDir}
		w.logger.Info("inotify watcher: watching path",
			slog.String("path", r.Target),
			slog.Bool("is_dir", isDir))
	}
}

// parseAndDispatch processes a raw inotify event buffer, extracting each event
// and dispatching AlertEvents accordingly.
//
// The binary layout of each inotify_event on disk is:
//
//	struct inotify_event {
//	    int32_t  wd;      // 4 bytes — watch descriptor
//	    uint32_t mask;    // 4 bytes — event mask
//	    uint32_t cookie;  // 4 bytes — rename correlation cookie
//	    uint32_t len;     // 4 bytes — length of name field (incl. null padding)
//	    char     name[];  // len bytes, NUL-terminated + null-padded to 4-byte boundary
//	}
func (w *InotifyWatcher) parseAndDispatch(buf []byte) {
	evSize := inotifyEventSize
	for offset := 0; offset+evSize <= len(buf); {
		// Safe: buf is a Go-managed byte slice; InotifyEvent has a fixed,
		// kernel-guaranteed layout; bounds are checked above.
		ev := (*syscall.InotifyEvent)(unsafe.Pointer(&buf[offset]))
		offset += evSize

		var name string
		if ev.Len > 0 {
			if offset+int(ev.Len) > len(buf) {
				break // truncated event; stop parsing
			}
			nameBytes := buf[offset : offset+int(ev.Len)]
			// The name field is NUL-terminated and may have additional NUL
			// padding to align to a 4-byte boundary.
			name = strings.TrimRight(string(nameBytes), "\x00")
			offset += int(ev.Len)
		}

		w.dispatchEvent(int(ev.Wd), ev.Mask, name)
	}
}

// dispatchEvent translates a single inotify event into an AlertEvent and sends
// it on the events channel. Events that do not match a configured rule, or
// that refer to directories within a watched directory (we are non-recursive),
// are silently ignored.
func (w *InotifyWatcher) dispatchEvent(wd int, mask uint32, name string) {
	// IN_Q_OVERFLOW is delivered with wd == -1 when the kernel dropped events.
	if mask&inQOverflow != 0 {
		w.logger.Warn("inotify watcher: kernel event queue overflowed; some events may be lost")
		return
	}

	w.mu.Lock()
	target, ok := w.targets[wd]
	w.mu.Unlock()

	if !ok {
		return
	}

	// Suppress directory-entry events within directory watches: we do not
	// track sub-directory creation/deletion (non-recursive, matching
	// FileWatcher behaviour).
	if mask&inIsDir != 0 {
		return
	}

	// Build the full path to the affected file.
	var path string
	if target.isDir && name != "" {
		path = filepath.Join(target.rule.Target, name)
	} else {
		path = target.rule.Target
	}

	// Map inotify event flags to one of our three logical operations.
	// The switch priority matches the expected event ordering: for a new
	// file, IN_CREATE fires before IN_CLOSE_WRITE, so the caller sees
	// "create" first.
	var operation string
	switch {
	case mask&inCreate != 0:
		operation = "create"
	case mask&inMovedTo != 0:
		operation = "create"
	case mask&inClosew != 0:
		operation = "write"
	case mask&inDelete != 0:
		operation = "delete"
	case mask&inMovedFrom != 0:
		operation = "delete"
	case mask&inMoveSelf != 0:
		operation = "delete"
	default:
		return // unrecognised flag; ignore
	}

	evt := agent.AlertEvent{
		TripwireType: "FILE",
		RuleName:     target.rule.Name,
		Severity:     target.rule.Severity,
		Timestamp:    time.Now().UTC(),
		Detail: map[string]any{
			"path":      path,
			"operation": operation,
		},
	}

	select {
	case w.events <- evt:
		w.logger.Info("inotify watcher: alert emitted",
			slog.String("rule", target.rule.Name),
			slog.String("path", path),
			slog.String("operation", operation))
	default:
		w.logger.Warn("inotify watcher: event channel full, dropping alert",
			slog.String("path", path))
	}
}
