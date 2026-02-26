// Package watcher provides filesystem monitoring components that implement
// the agent.Watcher interface.
//
// This file provides a stub InotifyWatcher for non-Linux platforms. On Linux,
// the real implementation in inotify_linux.go is compiled instead.
//
//go:build !linux

package watcher

import (
	"context"
	"fmt"
	"log/slog"

	"github.com/tripwire/agent/internal/agent"
	"github.com/tripwire/agent/internal/config"
)

// InotifyWatcher is the platform stub for non-Linux operating systems.
// On these platforms, NewInotifyWatcher always returns an error because
// the Linux inotify API is not available. Use FileWatcher instead — it
// provides cross-platform polling-based monitoring with identical semantics.
type InotifyWatcher struct{}

// NewInotifyWatcher always returns an error on non-Linux platforms.
// Use NewFileWatcher for cross-platform file monitoring.
func NewInotifyWatcher(_ []config.TripwireRule, _ *slog.Logger) (*InotifyWatcher, error) {
	return nil, fmt.Errorf("inotify watcher: not supported on this platform; use FileWatcher for cross-platform polling")
}

// Start returns an error; InotifyWatcher is not supported on this platform.
func (w *InotifyWatcher) Start(_ context.Context) error {
	return fmt.Errorf("inotify watcher: not supported on this platform")
}

// Stop is a no-op on non-Linux platforms.
func (w *InotifyWatcher) Stop() {}

// Events returns nil; InotifyWatcher is not supported on this platform.
func (w *InotifyWatcher) Events() <-chan agent.AlertEvent { return nil }

// Ready returns nil; InotifyWatcher is not supported on this platform.
func (w *InotifyWatcher) Ready() <-chan struct{} { return nil }
