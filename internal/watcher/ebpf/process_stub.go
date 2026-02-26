// SPDX-License-Identifier: Apache-2.0
//
// process_stub.go — non-Linux stub for the ebpf package.
//
// On non-Linux platforms every exported symbol is available but NewLoader
// always returns ErrNotSupported. This allows callers to import the package
// unconditionally and branch on errors rather than using build tags.

//go:build !linux

package ebpf

import (
	"context"
	"errors"
	"log/slog"
)

// ErrNotSupported is returned on non-Linux platforms. On Linux it is returned
// when the kernel is older than 5.8.
var ErrNotSupported = errors.New("ebpf: eBPF execve tracing is only supported on Linux ≥ 5.8")

// ExecEvent is the parsed form of a kernel execve ring-buffer record.
// On non-Linux platforms this type is defined for API compatibility only;
// no events are ever emitted.
type ExecEvent struct {
	PID      uint32
	PPID     uint32
	UID      uint32
	GID      uint32
	Comm     string
	Filename string
	Argv     string
}

// Loader is a no-op stub on non-Linux platforms.
type Loader struct{}

// NewLoader always returns ErrNotSupported on non-Linux platforms.
func NewLoader(_ *slog.Logger) (*Loader, error) {
	return nil, ErrNotSupported
}

// Load always returns ErrNotSupported on non-Linux platforms.
func (l *Loader) Load(_ context.Context) error {
	return ErrNotSupported
}

// Events returns a nil channel on non-Linux platforms.
func (l *Loader) Events() <-chan ExecEvent {
	return nil
}

// Close is a no-op on non-Linux platforms.
func (l *Loader) Close() {}
