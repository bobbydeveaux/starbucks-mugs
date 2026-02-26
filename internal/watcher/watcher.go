// Package watcher provides platform-specific file system watching for the
// TripWire agent. It implements the agent.Watcher interface so that file
// events are forwarded to the central alert pipeline.
package watcher

import "time"

// EventType classifies the kind of file system event detected.
type EventType uint32

const (
	// EventRead indicates the file was read/accessed.
	EventRead EventType = iota + 1
	// EventWrite indicates the file was written or modified.
	EventWrite
	// EventCreate indicates a file was created.
	EventCreate
	// EventDelete indicates a file was deleted.
	EventDelete
)

// FileEvent carries the details of a single file system event detected by
// the platform-specific watcher.
type FileEvent struct {
	// FilePath is the absolute path of the file that triggered the event.
	FilePath string
	// PID is the process ID that caused the event. May be 0 when the kernel
	// does not provide this information (e.g. inotify on Linux).
	PID int
	// UID is the user ID associated with the event. May be 0 when unknown.
	UID int
	// Username is the human-readable name resolved from UID. May be empty.
	Username string
	// EventType classifies the type of file system event.
	EventType EventType
	// Timestamp is when the event was observed by the watcher.
	Timestamp time.Time
}
