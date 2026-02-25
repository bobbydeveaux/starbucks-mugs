// Package watcher defines the Watcher interface and common event types for
// filesystem monitoring. Platform-specific implementations (file_watcher_linux.go,
// file_watcher_darwin.go) satisfy the Watcher interface and are selected at
// compile time via build tags.
//
// Usage:
//
//	cfg := watcher.WatcherConfig{Paths: []string{"/etc/passwd"}, BufferSize: 64}
//	w, err := watcher.NewWatcher(cfg)
//	if err != nil {
//	    log.Fatal(err)
//	}
//	if err := w.Watch(cfg.Paths); err != nil {
//	    log.Fatal(err)
//	}
//	for evt := range w.Events() {
//	    fmt.Printf("file %s accessed by PID %d (%s)\n", evt.FilePath, evt.PID, evt.Username)
//	}
package watcher

import "time"

// EventType describes the kind of file access captured by the watcher.
type EventType string

const (
	// EventRead indicates that a file was opened for reading.
	EventRead EventType = "read"
	// EventWrite indicates that a file was opened for writing or was modified.
	EventWrite EventType = "write"
)

// FileEvent is a single filesystem access event emitted by a Watcher.
// Each event corresponds to one observed access on a monitored path.
type FileEvent struct {
	// FilePath is the absolute path of the file that was accessed.
	FilePath string
	// PID is the OS process ID of the process that performed the access.
	// A value of 0 indicates the PID could not be determined.
	PID int
	// UID is the numeric user ID of the process that performed the access.
	// A value of -1 indicates the UID could not be determined.
	UID int
	// Username is the human-readable username resolved from UID.
	// It is empty when the UID could not be resolved to a username.
	Username string
	// EventType is one of EventRead or EventWrite.
	EventType EventType
	// Timestamp is the time at which the event was observed by the watcher.
	Timestamp time.Time
}

// Watcher is the common interface implemented by all filesystem watcher
// components. Implementations must be safe for concurrent use.
//
// Build-tag conventions for platform-specific implementations:
//
//	//go:build linux   → file_watcher_linux.go  (inotify)
//	//go:build darwin  → file_watcher_darwin.go (FSEvents or kqueue)
//
// Each platform file must implement newPlatformWatcher, which is called by
// NewWatcher to construct the platform-specific concrete type.
type Watcher interface {
	// Watch begins monitoring the given file or directory paths and sends
	// FileEvents on the channel returned by Events. It returns an error if
	// any path cannot be watched (e.g. path does not exist or permission
	// is denied). Watch may be called only once per Watcher instance.
	Watch(paths []string) error

	// Stop ceases monitoring and releases all resources held by the watcher,
	// including closing the Events channel. It blocks until all internal
	// goroutines have exited. It returns an error if any resource could not
	// be cleanly released. Stop is idempotent: subsequent calls are no-ops
	// and return nil.
	Stop() error

	// Events returns a read-only channel on which FileEvents are delivered.
	// The channel is closed when Stop returns. Callers should drain this
	// channel concurrently with Watch to avoid blocking the watcher.
	Events() <-chan FileEvent
}
