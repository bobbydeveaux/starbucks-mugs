//go:build linux

package watcher

import (
	"context"
	"fmt"
	"path/filepath"
	"strings"
	"syscall"
	"time"
	"unsafe"
)

// startPlatformWatcher is the Linux implementation backed by inotify. It
// opens an inotify file descriptor in non-blocking mode, registers watches for
// each path, and polls for events until ctx is cancelled or a read error
// occurs. Events are sent to the events channel; the channel is NOT closed by
// this function.
//
// When watching a specific file the inotify watch is placed on that file.
// When watching a directory all file events within the directory are reported
// with the full path.
func startPlatformWatcher(ctx context.Context, paths []string, events chan<- FileEvent) error {
	// Create an inotify instance with non-blocking I/O and close-on-exec.
	fd, err := syscall.InotifyInit1(syscall.IN_CLOEXEC | syscall.IN_NONBLOCK)
	if err != nil {
		return fmt.Errorf("inotify_init1: %w", err)
	}
	defer func() { _ = syscall.Close(fd) }()

	// Events to watch: access, modification, close-after-write, create, delete,
	// and renames (moved-from / moved-to).
	const mask = syscall.IN_ACCESS |
		syscall.IN_MODIFY |
		syscall.IN_CLOSE_WRITE |
		syscall.IN_CREATE |
		syscall.IN_DELETE |
		syscall.IN_MOVED_FROM |
		syscall.IN_MOVED_TO

	// Map from inotify watch descriptor to the path being watched.
	wdPaths := make(map[int32]string)

	for _, p := range paths {
		wd, err := syscall.InotifyAddWatch(fd, p, mask)
		if err != nil {
			return fmt.Errorf("inotify_add_watch %q: %w", p, err)
		}
		wdPaths[int32(wd)] = p
	}

	// Read buffer large enough for several events. Each event is at least
	// SizeofInotifyEvent bytes plus up to NAME_MAX bytes for the filename.
	buf := make([]byte, 16*(syscall.SizeofInotifyEvent+syscall.NAME_MAX+1))

	for {
		// Check for cancellation before blocking.
		select {
		case <-ctx.Done():
			return nil
		default:
		}

		n, err := syscall.Read(fd, buf)
		if err != nil {
			if err == syscall.EAGAIN {
				// No events available; sleep briefly so we stay responsive
				// to context cancellation without busy-looping.
				select {
				case <-ctx.Done():
					return nil
				case <-time.After(50 * time.Millisecond):
				}
				continue
			}
			return fmt.Errorf("inotify read: %w", err)
		}

		if err := parseInotifyEvents(buf[:n], wdPaths, events); err != nil {
			return err
		}
	}
}

// parseInotifyEvents decodes the raw bytes returned by a Read on the inotify
// fd and delivers a FileEvent for each recognisable event.
func parseInotifyEvents(buf []byte, wdPaths map[int32]string, events chan<- FileEvent) error {
	var offset uint32
	for offset <= uint32(len(buf))-uint32(syscall.SizeofInotifyEvent) {
		raw := (*syscall.InotifyEvent)(unsafe.Pointer(&buf[offset]))
		offset += uint32(syscall.SizeofInotifyEvent)

		var name string
		if raw.Len > 0 {
			// The filename follows the fixed header. Trim padding null bytes.
			end := offset + raw.Len
			if end > uint32(len(buf)) {
				break
			}
			name = strings.TrimRight(string(buf[offset:end]), "\x00")
			offset += raw.Len
		}

		watchedPath, ok := wdPaths[raw.Wd]
		if !ok {
			continue
		}

		filePath := watchedPath
		if name != "" {
			filePath = filepath.Join(watchedPath, name)
		}

		et := inotifyMaskToEventType(raw.Mask)
		if et == 0 {
			continue
		}

		fe := FileEvent{
			FilePath:  filePath,
			EventType: et,
			Timestamp: time.Now(),
		}

		select {
		case events <- fe:
		default:
			// Drop rather than block; the FileWatcher logs dropped events.
		}
	}
	return nil
}

// inotifyMaskToEventType converts an inotify event mask into the canonical
// EventType. Returns 0 for masks that do not map to a supported event type.
func inotifyMaskToEventType(mask uint32) EventType {
	switch {
	case mask&syscall.IN_ACCESS != 0:
		return EventRead
	case mask&(syscall.IN_MODIFY|syscall.IN_CLOSE_WRITE) != 0:
		return EventWrite
	case mask&(syscall.IN_CREATE|syscall.IN_MOVED_TO) != 0:
		return EventCreate
	case mask&(syscall.IN_DELETE|syscall.IN_MOVED_FROM) != 0:
		return EventDelete
	default:
		return 0
	}
}
