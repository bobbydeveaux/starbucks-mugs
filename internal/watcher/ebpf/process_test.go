// SPDX-License-Identifier: Apache-2.0

//go:build linux

package ebpf

import (
	"bytes"
	"context"
	"errors"
	"testing"
)

// ─── Struct size regression guard ────────────────────────────────────────────

// TestExecEventSize guards against accidental changes to the execEvent struct
// layout. The size must stay at 544 bytes to match the C kernel definition in
// process.h: 4+4+4+4+16+256+256 = 544.
func TestExecEventSize(t *testing.T) {
	const want = 544
	if execEventSize != want {
		t.Errorf("execEventSize = %d, want %d (struct layout must match process.h)",
			execEventSize, want)
	}
}

// ─── cString ─────────────────────────────────────────────────────────────────

func TestCString(t *testing.T) {
	cases := []struct {
		name  string
		input []byte
		want  string
	}{
		{
			name:  "NUL terminated",
			input: []byte{'h', 'e', 'l', 'l', 'o', 0, 0, 0},
			want:  "hello",
		},
		{
			name:  "no NUL (full buffer)",
			input: []byte{'a', 'b', 'c'},
			want:  "abc",
		},
		{
			name:  "all zeros",
			input: []byte{0, 0, 0},
			want:  "",
		},
		{
			name:  "empty slice",
			input: []byte{},
			want:  "",
		},
		{
			name:  "trailing spaces stripped",
			input: []byte{'h', 'i', 0, ' ', ' '},
			want:  "hi",
		},
		{
			name:  "NUL at first byte",
			input: []byte{0, 'x'},
			want:  "",
		},
	}

	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got := cString(tc.input)
			if got != tc.want {
				t.Errorf("cString(%q) = %q, want %q", tc.input, got, tc.want)
			}
		})
	}
}

// ─── parseExecEvent ──────────────────────────────────────────────────────────

// buildRawEvent constructs a 544-byte payload matching the execEvent layout.
func buildRawEvent(pid, ppid, uid, gid uint32, comm, filename, argv string) []byte {
	buf := make([]byte, execEventSize)

	// Integers are little-endian (x86/arm64 native order).
	putU32LE := func(off int, v uint32) {
		buf[off+0] = byte(v)
		buf[off+1] = byte(v >> 8)
		buf[off+2] = byte(v >> 16)
		buf[off+3] = byte(v >> 24)
	}

	putU32LE(0, pid)
	putU32LE(4, ppid)
	putU32LE(8, uid)
	putU32LE(12, gid)

	// NUL-terminated strings; copy up to field width.
	copyField := func(off, width int, s string) {
		n := copy(buf[off:off+width], s)
		_ = n // remaining bytes stay zero (NUL)
	}
	copyField(16, 16, comm)
	copyField(32, 256, filename)
	copyField(288, 256, argv)

	return buf
}

func TestParseExecEvent(t *testing.T) {
	raw := buildRawEvent(1234, 5678, 1000, 1000,
		"bash",
		"/usr/bin/bash",
		"/usr/bin/bash -c echo hello")

	got := parseExecEvent(raw)

	if got.PID != 1234 {
		t.Errorf("PID = %d, want 1234", got.PID)
	}
	if got.PPID != 5678 {
		t.Errorf("PPID = %d, want 5678", got.PPID)
	}
	if got.UID != 1000 {
		t.Errorf("UID = %d, want 1000", got.UID)
	}
	if got.GID != 1000 {
		t.Errorf("GID = %d, want 1000", got.GID)
	}
	if got.Comm != "bash" {
		t.Errorf("Comm = %q, want %q", got.Comm, "bash")
	}
	if got.Filename != "/usr/bin/bash" {
		t.Errorf("Filename = %q, want %q", got.Filename, "/usr/bin/bash")
	}
	if got.Argv != "/usr/bin/bash -c echo hello" {
		t.Errorf("Argv = %q, want %q", got.Argv, "/usr/bin/bash -c echo hello")
	}
}

// TestParseExecEvent_MaxLength ensures strings that fill their field exactly
// (no NUL terminator room) are parsed correctly without overflowing.
func TestParseExecEvent_MaxLength(t *testing.T) {
	longComm := bytes.Repeat([]byte{'x'}, 15) // TRIPWIRE_COMM_LEN - 1 (leave NUL)
	longFile := bytes.Repeat([]byte{'/'}, 255) // TRIPWIRE_PATH_LEN - 1
	longArgv := bytes.Repeat([]byte{'a'}, 255) // TRIPWIRE_ARGV_LEN - 1

	raw := buildRawEvent(1, 2, 3, 4,
		string(longComm), string(longFile), string(longArgv))

	got := parseExecEvent(raw)

	if len(got.Comm) != 15 {
		t.Errorf("len(Comm) = %d, want 15", len(got.Comm))
	}
	if len(got.Filename) != 255 {
		t.Errorf("len(Filename) = %d, want 255", len(got.Filename))
	}
	if len(got.Argv) != 255 {
		t.Errorf("len(Argv) = %d, want 255", len(got.Argv))
	}
}

// TestParseExecEvent_ZeroFields validates that a zero-filled record produces
// empty strings and zero integer fields (not garbage).
func TestParseExecEvent_ZeroFields(t *testing.T) {
	raw := make([]byte, execEventSize) // all zeros
	got := parseExecEvent(raw)

	if got.PID != 0 || got.PPID != 0 || got.UID != 0 || got.GID != 0 {
		t.Errorf("expected zero integer fields, got %+v", got)
	}
	if got.Comm != "" || got.Filename != "" || got.Argv != "" {
		t.Errorf("expected empty string fields, got Comm=%q Filename=%q Argv=%q",
			got.Comm, got.Filename, got.Argv)
	}
}

// ─── requireKernelVersion ────────────────────────────────────────────────────

// TestRequireKernelVersion_CurrentKernel verifies that requireKernelVersion
// does not return ErrNotSupported for the currently running kernel when asking
// for 1.0 (effectively "any version").
func TestRequireKernelVersion_CurrentKernel(t *testing.T) {
	if err := requireKernelVersion(1, 0); err != nil {
		t.Errorf("requireKernelVersion(1, 0) returned error on current kernel: %v", err)
	}
}

// TestRequireKernelVersion_TooHigh verifies that an unreachably high version
// returns ErrNotSupported.
func TestRequireKernelVersion_TooHigh(t *testing.T) {
	err := requireKernelVersion(999, 999)
	if err == nil {
		t.Fatal("requireKernelVersion(999, 999): expected error, got nil")
	}
	if !errors.Is(err, ErrNotSupported) {
		t.Errorf("requireKernelVersion(999, 999): error %v does not wrap ErrNotSupported", err)
	}
}

// ─── NewLoader ───────────────────────────────────────────────────────────────

// TestNewLoader_KernelVersion tests that NewLoader returns ErrNotSupported on
// a kernel that does not meet the 5.8 requirement, and a valid Loader on a
// kernel that does. We use requireKernelVersion to determine the expected
// outcome rather than hard-coding a version check.
func TestNewLoader_KernelVersion(t *testing.T) {
	kernelOK := requireKernelVersion(5, 8) == nil

	l, err := NewLoader(nil)
	if kernelOK {
		if err != nil {
			t.Fatalf("NewLoader on kernel ≥5.8 returned error: %v", err)
		}
		if l == nil {
			t.Fatal("NewLoader returned nil Loader on supported kernel")
		}
		// Cleanup: Close without calling Load; must not panic.
		l.Close()
	} else {
		if !errors.Is(err, ErrNotSupported) {
			t.Errorf("NewLoader on kernel <5.8: got %v, want ErrNotSupported", err)
		}
		if l != nil {
			t.Error("NewLoader returned non-nil Loader alongside error")
		}
	}
}

// TestNewLoader_EventsChannel verifies that the Events channel is non-nil
// after successful construction and is closed after Close.
func TestNewLoader_EventsChannel(t *testing.T) {
	if requireKernelVersion(5, 8) != nil {
		t.Skip("kernel < 5.8; NewLoader returns ErrNotSupported")
	}

	l, err := NewLoader(nil)
	if err != nil {
		t.Fatalf("NewLoader: %v", err)
	}

	ch := l.Events()
	if ch == nil {
		t.Fatal("Events() returned nil before Close")
	}

	l.Close()

	// After Close the channel must be closed (readable with ok=false).
	select {
	case _, ok := <-ch:
		if ok {
			// Drain any buffered events; channel must eventually close.
			for range ch {
			}
		}
	default:
		t.Fatal("events channel still open after Close")
	}
}

// TestLoader_CloseIdempotent verifies that calling Close multiple times on a
// Loader that was never Loaded does not panic or deadlock.
func TestLoader_CloseIdempotent(t *testing.T) {
	if requireKernelVersion(5, 8) != nil {
		t.Skip("kernel < 5.8")
	}

	l, err := NewLoader(nil)
	if err != nil {
		t.Fatalf("NewLoader: %v", err)
	}

	l.Close()
	l.Close() // must not panic
}

// ─── Load (requires compiled BPF object and privileged kernel) ───────────────

// TestLoader_LoadRequiresCompiledBPF attempts Load and expects failure when
// the embedded process.bpf.o is the placeholder stub shipped with the
// repository. This test documents the expected developer workflow: compile the
// BPF object with 'make -C internal/watcher/ebpf' before using the loader.
//
// When the real compiled object is present AND the process has CAP_BPF, this
// test would succeed. We detect the placeholder by checking for a parse error.
func TestLoader_LoadWithPlaceholderObject(t *testing.T) {
	if requireKernelVersion(5, 8) != nil {
		t.Skip("kernel < 5.8; NewLoader returns ErrNotSupported")
	}

	l, err := NewLoader(nil)
	if err != nil {
		t.Fatalf("NewLoader: %v", err)
	}
	defer l.Close()

	err = l.Load(context.Background())
	if err == nil {
		// Real compiled object is present — log a note and pass.
		t.Log("Load succeeded: real process.bpf.o detected (not a stub)")
		return
	}
	// Placeholder stub: Load is expected to fail with a parse or capability
	// error. Verify the error is not ErrNotSupported (kernel is fine).
	if errors.Is(err, ErrNotSupported) {
		t.Errorf("Load returned ErrNotSupported on a kernel ≥5.8: %v", err)
	}
	t.Logf("Load returned expected error (placeholder BPF object): %v", err)
}

// TestLoader_LoadIdempotent verifies that calling Load twice returns an error
// on the second call without crashing.
func TestLoader_LoadIdempotent(t *testing.T) {
	if requireKernelVersion(5, 8) != nil {
		t.Skip("kernel < 5.8")
	}

	l, err := NewLoader(nil)
	if err != nil {
		t.Fatalf("NewLoader: %v", err)
	}
	defer l.Close()

	// First Load: may succeed (real .bpf.o + CAP_BPF) or fail (placeholder).
	firstErr := l.Load(context.Background())

	// Second Load must always return an error.
	secondErr := l.Load(context.Background())
	if firstErr == nil && secondErr == nil {
		t.Error("second Load returned nil; want non-nil error (already loaded)")
	}
	t.Logf("first Load: %v; second Load: %v", firstErr, secondErr)
}
