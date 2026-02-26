// Stub implementation of ProcessWatcher for platforms other than Linux and
// macOS/Darwin.
//
// On Linux the real implementation in process_watcher_linux.go is compiled
// (NETLINK_CONNECTOR / PROC_EVENT_EXEC). On Darwin the kqueue-based fallback
// in process_watcher_darwin.go is compiled (EVFILT_PROC / NOTE_EXEC + poll).
// This file provides the Start and Stop methods for all remaining operating
// systems (Windows, FreeBSD, etc.) where neither mechanism is available.
//
//go:build !linux && !darwin

package watcher

import (
	"context"
	"fmt"
	"runtime"
)

// Start always returns an error on unsupported platforms because neither the
// Linux NETLINK_CONNECTOR mechanism nor the macOS kqueue EVFILT_PROC fallback
// is available. To add support for another OS, create
// process_watcher_<goos>.go with a platform-specific implementation of Start,
// Stop, and any required helpers.
func (w *ProcessWatcher) Start(_ context.Context) error {
	return fmt.Errorf(
		"process watcher: execve tracing is only supported on Linux "+
			"(NETLINK_CONNECTOR) and macOS (kqueue/EVFILT_PROC); "+
			"current platform: %s",
		runtime.GOOS,
	)
}

// Stop is a no-op on unsupported platforms. It closes the Events channel
// exactly once so that callers ranging over Events() terminate cleanly.
func (w *ProcessWatcher) Stop() {
	w.stopOnce.Do(func() {
		close(w.events)
	})
}
