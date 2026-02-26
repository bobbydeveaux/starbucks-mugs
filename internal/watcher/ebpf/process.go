// SPDX-License-Identifier: Apache-2.0
//
// internal/watcher/ebpf/process.go — eBPF Go userspace loader and event pump.
//
// This file is the companion to internal/watcher/ebpf/process.bpf.c. It:
//   1. Embeds the pre-compiled BPF object (process.bpf.o).
//   2. Checks that the running kernel is ≥ 5.8 (BPF ring buffer was added in
//      5.8; earlier kernels are not supported).
//   3. Loads the BPF collection, attaches it to the execve/execveat tracepoints.
//   4. Reads raw ring-buffer records in a goroutine and converts them to typed
//      ExecEvent values that are delivered on a buffered channel.
//
// Build the BPF object before using this package:
//
//	apt-get install -y clang llvm libbpf-dev linux-headers-$(uname -r)
//	bpftool btf dump file /sys/kernel/btf/vmlinux format c \
//	    > internal/watcher/ebpf/vmlinux.h
//	make -C internal/watcher/ebpf
//
// The placeholder process.bpf.o checked into the repository causes
// LoadCollectionSpecFromReader to return an error on any attempt to Load()
// before the real object is compiled. Callers should treat this as equivalent
// to ErrNotSupported and fall back to the NETLINK_CONNECTOR implementation.
//
//go:generate make -C . process.bpf.o

//go:build linux

package ebpf

import (
	"bytes"
	"context"
	_ "embed"
	"encoding/binary"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"strings"
	"sync"
	"time"
	"unsafe"

	ciliumebpf "github.com/cilium/ebpf"
	"github.com/cilium/ebpf/link"
	"github.com/cilium/ebpf/ringbuf"
)

// processObjBytes holds the compiled BPF object embedded at build time.
// Replace internal/watcher/ebpf/process.bpf.o with the output of
// 'make -C internal/watcher/ebpf' before shipping.
//
//go:embed process.bpf.o
var processObjBytes []byte

// ErrNotSupported is returned by NewLoader when the running kernel does not
// meet the minimum requirements for eBPF-based execve tracing:
//   - Linux ≥ 5.8 (BPF_MAP_TYPE_RINGBUF, introduced in 5.8)
//   - CONFIG_BPF_SYSCALL=y, CONFIG_DEBUG_INFO_BTF=y
//   - CAP_BPF or CAP_SYS_ADMIN
var ErrNotSupported = errors.New("ebpf: kernel ≥ 5.8 required for eBPF execve tracing")

// execEvent is the Go mirror of the C struct exec_event defined in process.h.
// Field order, sizes, and alignment MUST match the kernel ABI exactly so that
// encoding/binary can deserialise ring-buffer payloads without unsafe casts.
//
//	Total size: 4+4+4+4+16+256+256 = 544 bytes.
type execEvent struct {
	PID      uint32
	PPID     uint32
	UID      uint32
	GID      uint32
	Comm     [16]byte
	Filename [256]byte
	Argv     [256]byte
}

// execEventSize is the expected on-wire size of execEvent. Used to validate
// ring-buffer records and in tests as a regression guard.
const execEventSize = int(unsafe.Sizeof(execEvent{})) // 544

// ExecEvent is the parsed, human-readable form of a kernel execve ring-buffer
// record. String fields are NUL-stripped and trimmed of trailing spaces.
type ExecEvent struct {
	// PID is the tgid of the process that called execve/execveat.
	PID uint32
	// PPID is the tgid of the calling process's parent.
	PPID uint32
	// UID is the real user ID of the calling process.
	UID uint32
	// GID is the real group ID of the calling process.
	GID uint32
	// Comm is the short task-name (≤ 15 bytes) at the time of execve.
	Comm string
	// Filename is the path argument supplied to execve/execveat.
	Filename string
	// Argv is the space-joined argument list (argv[0..N]), truncated at
	// TRIPWIRE_ARGV_LEN (256) bytes by the BPF program.
	Argv string
}

// Loader loads the compiled eBPF object into the kernel, attaches it to the
// execve and execveat tracepoints, and pumps kernel events to the Events
// channel.
//
// Lifecycle:
//
//  1. Create with NewLoader; the constructor checks the kernel version.
//  2. Call Load(ctx) to attach the BPF programs and start the event goroutine.
//  3. Read typed ExecEvents from Events().
//  4. Call Close() to detach, free all kernel objects, and close the channel.
//
// Loader is safe for concurrent use after Load returns.
type Loader struct {
	events chan ExecEvent
	logger *slog.Logger

	mu       sync.Mutex
	coll     *ciliumebpf.Collection
	links    []link.Link
	rd       *ringbuf.Reader
	stopOnce sync.Once
	wg       sync.WaitGroup
}

// NewLoader creates a new Loader after verifying that the running kernel
// supports eBPF ring buffers (Linux ≥ 5.8). It returns ErrNotSupported when
// the kernel is too old.
//
// The caller must call Close() when done, even if Load is never called.
func NewLoader(logger *slog.Logger) (*Loader, error) {
	if logger == nil {
		logger = slog.Default()
	}
	if err := requireKernelVersion(5, 8); err != nil {
		return nil, err
	}
	return &Loader{
		events: make(chan ExecEvent, 1024),
		logger: logger,
	}, nil
}

// Load parses the embedded BPF object, loads all programs and maps into the
// kernel, attaches the programs to the execve and execveat tracepoints, and
// starts the ring-buffer event pump in a background goroutine.
//
// The context controls the lifetime of the event pump: cancelling ctx causes
// the goroutine to exit within one second (the ring-buffer read deadline).
// Load must be called at most once; subsequent calls return an error.
//
// Privilege: loading BPF programs requires CAP_BPF (Linux ≥ 5.8) or
// CAP_SYS_ADMIN on older kernels.
func (l *Loader) Load(ctx context.Context) error {
	l.mu.Lock()
	defer l.mu.Unlock()

	if l.coll != nil {
		return errors.New("ebpf loader: already loaded")
	}

	// Parse the embedded BPF ELF object.
	spec, err := ciliumebpf.LoadCollectionSpecFromReader(bytes.NewReader(processObjBytes))
	if err != nil {
		return fmt.Errorf("ebpf loader: parse BPF object: %w "+
			"(compile with 'make -C internal/watcher/ebpf')", err)
	}

	// Load (verify + JIT-compile) all programs and create all maps.
	coll, err := ciliumebpf.NewCollection(spec)
	if err != nil {
		var ve *ciliumebpf.VerifierError
		if errors.As(err, &ve) {
			return fmt.Errorf("%w: BPF verifier: %v", ErrNotSupported, ve)
		}
		return fmt.Errorf("ebpf loader: load BPF collection: %w", err)
	}
	l.coll = coll

	// Attach to sys_enter_execve.
	lnExecve, err := link.Tracepoint(
		"syscalls", "sys_enter_execve",
		coll.Programs["trace_execve"], nil,
	)
	if err != nil {
		coll.Close()
		return fmt.Errorf("ebpf loader: attach execve tracepoint: %w", err)
	}
	l.links = append(l.links, lnExecve)

	// Attach to sys_enter_execveat.
	lnExecveat, err := link.Tracepoint(
		"syscalls", "sys_enter_execveat",
		coll.Programs["trace_execveat"], nil,
	)
	if err != nil {
		lnExecve.Close()
		coll.Close()
		return fmt.Errorf("ebpf loader: attach execveat tracepoint: %w", err)
	}
	l.links = append(l.links, lnExecveat)

	// Open the ring-buffer reader for the execve_events map.
	rd, err := ringbuf.NewReader(coll.Maps["execve_events"])
	if err != nil {
		lnExecve.Close()
		lnExecveat.Close()
		coll.Close()
		return fmt.Errorf("ebpf loader: open ring buffer: %w", err)
	}
	l.rd = rd

	l.wg.Add(1)
	go l.readLoop(ctx)

	l.logger.Info("ebpf loader: execve tracing active",
		slog.String("mechanism", "BPF ring buffer / tracepoint"),
	)
	return nil
}

// Events returns the read-only channel on which ExecEvents are delivered.
// The channel is closed when Close is called and the background goroutine
// has exited. Callers should range over this channel until it is closed.
func (l *Loader) Events() <-chan ExecEvent {
	return l.events
}

// Close detaches the BPF programs, waits for the event-pump goroutine to
// exit, frees all kernel objects (maps, programs, links), and closes the
// Events channel. Close is safe to call multiple times (idempotent) and may
// be called concurrently with Load and Events.
func (l *Loader) Close() {
	l.stopOnce.Do(func() {
		l.mu.Lock()
		rd := l.rd
		links := l.links
		coll := l.coll
		l.mu.Unlock()

		// Closing the ring-buffer reader unblocks any pending rd.Read()
		// call in the goroutine, causing it to return ringbuf.ErrClosed
		// and exit cleanly.
		if rd != nil {
			_ = rd.Close()
		}

		// Wait for the event-pump goroutine to exit before releasing
		// kernel objects to prevent use-after-free.
		l.wg.Wait()

		// Detach tracepoints first, then free the collection.
		for _, ln := range links {
			_ = ln.Close()
		}
		if coll != nil {
			coll.Close()
		}

		close(l.events)
		l.logger.Info("ebpf loader: stopped")
	})
}

// ─── Event pump ──────────────────────────────────────────────────────────────

// readLoop runs in the goroutine started by Load. It reads raw ring-buffer
// records, converts them to ExecEvent values, and sends them on the events
// channel. It exits when:
//   - Close() is called (rd.Read() returns ringbuf.ErrClosed), or
//   - ctx is cancelled (detected via the 1-second read deadline).
func (l *Loader) readLoop(ctx context.Context) {
	defer l.wg.Done()

	for {
		// Set a short read deadline so we can detect context cancellation
		// without blocking indefinitely when the ring buffer is quiet.
		l.rd.SetDeadline(time.Now().Add(time.Second))

		rec, err := l.rd.Read()
		if err != nil {
			if errors.Is(err, ringbuf.ErrClosed) {
				return // Close() was called
			}
			if errors.Is(err, os.ErrDeadlineExceeded) {
				select {
				case <-ctx.Done():
					return
				default:
					continue // deadline expired; loop for another second
				}
			}
			l.logger.Warn("ebpf loader: ring buffer read error",
				slog.Any("error", err),
			)
			return
		}

		if len(rec.RawSample) < execEventSize {
			l.logger.Warn("ebpf loader: short ring-buffer record",
				slog.Int("got", len(rec.RawSample)),
				slog.Int("want", execEventSize),
			)
			continue
		}

		evt := parseExecEvent(rec.RawSample)
		select {
		case l.events <- evt:
		default:
			l.logger.Warn("ebpf loader: event channel full, dropping execve event",
				slog.String("filename", evt.Filename),
				slog.Uint64("pid", uint64(evt.PID)),
			)
		}
	}
}

// ─── Parsing helpers ─────────────────────────────────────────────────────────

// parseExecEvent deserialises the raw ring-buffer bytes into an ExecEvent.
// The byte layout is determined by the C struct exec_event in process.h:
//
//	PID(4) PPID(4) UID(4) GID(4) Comm(16) Filename(256) Argv(256) = 544 B
//
// All integer fields are in the native byte order of the kernel (little-endian
// on x86/arm64). Only the first execEventSize bytes of b are consumed.
func parseExecEvent(b []byte) ExecEvent {
	var raw execEvent
	r := bytes.NewReader(b[:execEventSize])
	// encoding/binary.Read handles each field in declaration order.
	// For uint32 fields it applies the given byte order; for [n]byte fields
	// it copies bytes directly (no byte-order conversion).
	if err := binary.Read(r, binary.LittleEndian, &raw); err != nil {
		// Should not happen: we already validated len(b) >= execEventSize.
		return ExecEvent{}
	}
	return ExecEvent{
		PID:      raw.PID,
		PPID:     raw.PPID,
		UID:      raw.UID,
		GID:      raw.GID,
		Comm:     cString(raw.Comm[:]),
		Filename: cString(raw.Filename[:]),
		Argv:     cString(raw.Argv[:]),
	}
}

// cString converts a NUL-terminated C string (stored in a byte slice) to a
// Go string, stripping the NUL byte and any trailing spaces.
func cString(b []byte) string {
	if i := bytes.IndexByte(b, 0); i >= 0 {
		b = b[:i]
	}
	return strings.TrimRight(string(b), " ")
}

// ─── Kernel version check ────────────────────────────────────────────────────

// requireKernelVersion reads the kernel release string from
// /proc/sys/kernel/osrelease and returns ErrNotSupported if the running
// kernel is older than major.minor.
func requireKernelVersion(major, minor int) error {
	b, err := os.ReadFile("/proc/sys/kernel/osrelease")
	if err != nil {
		return fmt.Errorf("ebpf: read kernel version: %w", err)
	}

	release := strings.TrimSpace(string(b))

	var maj, min int
	if _, err := fmt.Sscanf(release, "%d.%d", &maj, &min); err != nil {
		return fmt.Errorf("ebpf: parse kernel release %q: %w", release, err)
	}

	if maj < major || (maj == major && min < minor) {
		return fmt.Errorf("%w: running kernel %d.%d < required %d.%d",
			ErrNotSupported, maj, min, major, minor)
	}
	return nil
}
