// Package watcher defines the common abstractions for TripWire watcher
// components. The Watcher interface is the contract that all filesystem,
// network, and process watcher implementations must satisfy. AlertEvent is
// the event type emitted on detected policy violations.
//
// Placing these types in the watcher package rather than the agent package
// keeps the dependency direction clean: concrete watcher implementations
// (FileWatcher, NetworkWatcher, ...) depend only on this package, while the
// agent orchestrator depends on the watcher package for the shared contract.
package watcher

import (
	"context"
	"time"
)

// AlertEvent is a generic event emitted by a Watcher when a monitored
// resource changes in a way that violates a configured tripwire rule.
type AlertEvent struct {
	// TripwireType is one of "FILE", "NETWORK", or "PROCESS".
	TripwireType string
	// RuleName is the name of the rule that triggered this event.
	RuleName string
	// Severity is one of "INFO", "WARN", or "CRITICAL".
	Severity string
	// Timestamp is when the event occurred on the agent host.
	Timestamp time.Time
	// Detail holds type-specific metadata (file path, port, pid, etc.).
	Detail map[string]any
}

// Watcher is the common interface implemented by file, network, and process
// watcher components. Implementations must be safe for concurrent use.
//
// Implementations should document whether Start may be called more than once
// and the exact semantics of Stop (blocking vs. non-blocking).
type Watcher interface {
	// Start begins monitoring and sends events to the channel returned by
	// Events. It returns an error if initialisation fails. Start must be
	// called before Events is consumed.
	Start(ctx context.Context) error
	// Stop signals the watcher to cease monitoring and release resources.
	// It blocks until all internal goroutines have exited and the Events
	// channel has been closed.
	Stop()
	// Events returns a read-only channel from which callers receive
	// AlertEvents. The channel is closed when the watcher stops.
	Events() <-chan AlertEvent
}
