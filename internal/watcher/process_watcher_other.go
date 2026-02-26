// Stub implementation of ProcessWatcher for non-Linux platforms.
//
// On Linux the real implementation in process_watcher_linux.go is compiled;
// this file provides the Start and Stop methods required to satisfy the
// agent.Watcher interface on macOS, Windows, and other operating systems.
//
//go:build !linux

package watcher

import (
	"context"
	"fmt"
	"runtime"
)

// Start always returns an error on non-Linux platforms because the kernel
// process-event connector is a Linux-specific interface. To add support for
// another OS, create process_watcher_<goos>.go with a platform-specific
// implementation of Start, Stop, and any required helpers.
func (w *ProcessWatcher) Start(_ context.Context) error {
	return fmt.Errorf(
		"process watcher: PROC_EVENT_EXEC / eBPF execve tracing is only "+
			"supported on Linux (current platform: %s)",
		runtime.GOOS,
	)
}

// Stop is a no-op on non-Linux platforms. It closes the Events channel exactly
// once so that callers ranging over Events() terminate cleanly.
func (w *ProcessWatcher) Stop() {
	w.stopOnce.Do(func() {
		close(w.events)
	})
}
