// This file provides the platform-agnostic base implementation of the Watcher
// interface and the shared configuration type used by all file watcher variants.
//
// Build-tag conventions for platform-specific implementations:
//
//	file_watcher_linux.go  (//go:build linux)  — inotify-based implementation
//	file_watcher_darwin.go (//go:build darwin) — FSEvents/kqueue-based implementation
//
// Platform-specific files register a constructor via init():
//
//	func init() { platformFactory = newInotifyWatcher }  // Linux example
//
// When no platform registration has occurred, NewWatcher falls back to the
// baseWatcher, which satisfies the interface but delivers no filesystem events.
// This allows the package to build and link cleanly on every supported OS.
package watcher

import (
	"sync"
)

// defaultBufferSize is the default capacity of the FileEvent channel returned
// by baseWatcher.Events(). A capacity of 64 prevents the watcher from blocking
// the kernel/OS callback when the consumer is momentarily behind.
const defaultBufferSize = 64

// WatcherConfig holds the shared configuration used when constructing a
// platform-specific file watcher. It is passed to NewWatcher and forwarded
// to the registered platform factory.
type WatcherConfig struct {
	// Paths is the initial list of file or directory paths to monitor.
	// An empty slice is valid; paths can be supplied later via Watch.
	Paths []string

	// BufferSize is the capacity of the FileEvent channel returned by
	// Events(). A value of 0 or negative uses defaultBufferSize (64).
	// Increase this for high-traffic directories where the consumer may
	// lag behind the watcher.
	BufferSize int
}

// platformFactory is the registered platform-specific constructor. It is set
// by platform-specific files (file_watcher_linux.go, file_watcher_darwin.go)
// in their init() function. When nil, NewWatcher falls back to the baseWatcher.
//
// Constructor signature that platform files must use:
//
//	func newPlatformImpl(cfg WatcherConfig) (Watcher, error)
var platformFactory func(cfg WatcherConfig) (Watcher, error)

// NewWatcher constructs a Watcher from cfg. On Linux it returns an
// inotify-backed watcher (when file_watcher_linux.go is compiled in);
// on macOS it returns an FSEvents/kqueue-backed watcher (when
// file_watcher_darwin.go is compiled in). On unsupported platforms, or
// when no platform implementation has been registered, it returns a no-op
// baseWatcher that satisfies the interface but delivers no events.
//
// If cfg.Paths is non-empty, Watch is called automatically with those paths
// before NewWatcher returns; any error from that call is returned here.
func NewWatcher(cfg WatcherConfig) (Watcher, error) {
	if cfg.BufferSize <= 0 {
		cfg.BufferSize = defaultBufferSize
	}

	var (
		w   Watcher
		err error
	)

	if platformFactory != nil {
		w, err = platformFactory(cfg)
	} else {
		w = newBaseWatcher(cfg.BufferSize)
	}

	if err != nil {
		return nil, err
	}

	if len(cfg.Paths) > 0 {
		if err := w.Watch(cfg.Paths); err != nil {
			_ = w.Stop()
			return nil, err
		}
	}

	return w, nil
}

// ---------------------------------------------------------------------------
// baseWatcher — fallback / unsupported-platform implementation
// ---------------------------------------------------------------------------

// baseWatcher is the no-op fallback implementation of Watcher used when no
// platform-specific factory has been registered. It satisfies the interface
// contract: Watch and Stop succeed without error, Events returns a channel
// that is closed when Stop is called. No events are ever delivered.
//
// Platform-specific files replace this behaviour by registering a factory
// via the platformFactory variable in their init() function.
type baseWatcher struct {
	events   chan FileEvent
	stopOnce sync.Once
}

// newBaseWatcher constructs a baseWatcher with a buffered FileEvent channel.
func newBaseWatcher(bufSize int) *baseWatcher {
	return &baseWatcher{
		events: make(chan FileEvent, bufSize),
	}
}

// Watch is a no-op on the base implementation. Platform-specific constructors
// registered via platformFactory replace this with kernel-level watch logic.
func (w *baseWatcher) Watch(_ []string) error {
	return nil
}

// Stop closes the Events channel. It is idempotent and safe to call multiple
// times.
func (w *baseWatcher) Stop() error {
	w.stopOnce.Do(func() {
		close(w.events)
	})
	return nil
}

// Events returns the read-only FileEvent channel. The channel is closed when
// Stop returns.
func (w *baseWatcher) Events() <-chan FileEvent {
	return w.events
}
