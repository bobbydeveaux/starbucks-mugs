// Package ebpf implements a Go eBPF loader and userspace event consumer for
// TripWire execve tracing.
//
// The companion eBPF kernel program (process.bpf.c) attaches to the
// sys_enter_execve and sys_enter_execveat tracepoints and writes exec_event
// records to a BPF ring buffer.  This package loads that pre-compiled program,
// reads events from the ring buffer, and converts them into AlertEvents that
// satisfy the watcher.Watcher interface.
//
// # Kernel requirements
//
//   - Linux ≥ 5.8 (BPF ring buffer: BPF_MAP_TYPE_RINGBUF)
//   - CAP_BPF (Linux ≥ 5.8) or CAP_SYS_ADMIN (older kernels)
//   - CONFIG_BPF_SYSCALL=y, CONFIG_DEBUG_INFO_BTF=y (for CO-RE)
//
// # Build variants
//
// Standard build — no embedded BPF object (Start returns an informative error):
//
//	go build ./internal/watcher/ebpf/...
//
// Embedded build — bundles the compiled BPF object into the binary:
//
//	make -C internal/watcher/ebpf   # compile process.bpf.c → process.bpf.o
//	go build -tags bpf_embedded ./internal/watcher/ebpf/...
//
// When built with -tags bpf_embedded, the BPF object is embedded at link time
// and no runtime file access is needed.
//
//go:build linux

package ebpf

import (
	"bytes"
	"context"
	"encoding/binary"
	"fmt"
	"log/slog"
	"path/filepath"
	"sync"
	"time"

	"github.com/tripwire/agent/internal/config"
	"github.com/tripwire/agent/internal/watcher"
)

// bpfObjectBytes holds the pre-compiled eBPF program object.
//
// In a standard build this is nil; Start() returns a descriptive error.
// When built with -tags bpf_embedded (after running make in the ebpf
// directory), bpfobject_embed_linux.go sets this variable via //go:embed.
var bpfObjectBytes []byte

// ─── Kernel struct mirror ─────────────────────────────────────────────────────

// execEvent mirrors the C exec_event struct defined in process.h.
//
// Layout (total 544 bytes, matching the C definition exactly):
//
//	PID      uint32    4 B  — tgid (matches getpid(2))
//	PPID     uint32    4 B  — parent tgid
//	UID      uint32    4 B  — real UID
//	GID      uint32    4 B  — real GID
//	Comm     [16]byte  16 B — short task name (TASK_COMM_LEN)
//	Filename [256]byte 256 B — execve filename argument
//	Argv     [256]byte 256 B — space-joined argv[0..N]
type execEvent struct {
	PID      uint32
	PPID     uint32
	UID      uint32
	GID      uint32
	Comm     [16]byte
	Filename [256]byte
	Argv     [256]byte
}

// ExecEventSize is the expected on-wire size of an exec_event ring-buffer
// record (544 bytes). It is validated at readLoop time against the raw sample
// length and exported so that tests can guard against layout drift between the
// C exec_event struct (process.h) and the Go mirror (execEvent).
const ExecEventSize = 4 + 4 + 4 + 4 + 16 + 256 + 256

// execEventSize is the internal alias used within this package.
const execEventSize = ExecEventSize

// ─── ProcessWatcher ───────────────────────────────────────────────────────────

// ProcessWatcher loads the eBPF execve-tracing program and delivers
// AlertEvents for exec events that match configured PROCESS rules.
//
// It implements [watcher.Watcher] and is safe for concurrent use.
//
// Unlike the NETLINK_CONNECTOR-based ProcessWatcher in the parent watcher
// package, this implementation captures argv, UID, GID, and PPID directly
// in the kernel, avoiding the TOCTOU window between the exec event and the
// subsequent /proc reads.
//
// Requires either the -tags bpf_embedded build or a bpfObjPath passed to
// SetBPFObject before calling Start.
type ProcessWatcher struct {
	rules     []config.TripwireRule
	logger    *slog.Logger
	objBytes  []byte // BPF object bytes; falls back to package-level bpfObjectBytes

	events   chan watcher.AlertEvent
	mu       sync.Mutex
	cancel   func()
	stopOnce sync.Once
	wg       sync.WaitGroup
}

// NewProcessWatcher creates an eBPF-backed ProcessWatcher from the provided
// rules. Non-PROCESS rules are silently ignored. If logger is nil,
// slog.Default() is used. The returned watcher is not yet started; call Start
// to begin monitoring.
//
// When built with -tags bpf_embedded the BPF object is used automatically.
// Otherwise, call SetBPFObject to provide the compiled BPF object bytes before
// calling Start.
func NewProcessWatcher(rules []config.TripwireRule, logger *slog.Logger) *ProcessWatcher {
	if logger == nil {
		logger = slog.Default()
	}

	var procRules []config.TripwireRule
	for _, r := range rules {
		if r.Type == "PROCESS" {
			procRules = append(procRules, r)
		}
	}

	return &ProcessWatcher{
		rules:  procRules,
		logger: logger,
		events: make(chan watcher.AlertEvent, 64),
	}
}

// SetBPFObject supplies the compiled BPF object bytes to use when Start is
// called. This is typically used in tests or when the binary is not built with
// -tags bpf_embedded. The bytes must represent a valid 64-bit little-endian BPF
// ELF object compiled from process.bpf.c.
//
// SetBPFObject must be called before Start.
func (w *ProcessWatcher) SetBPFObject(obj []byte) {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.objBytes = obj
}

// Events returns a read-only channel from which callers receive AlertEvents.
// The channel is closed when the watcher stops (after Stop returns).
func (w *ProcessWatcher) Events() <-chan watcher.AlertEvent {
	return w.events
}

// Start loads the eBPF object into the kernel, attaches the execve and
// execveat tracepoints, and begins delivering AlertEvents for exec calls that
// match any configured PROCESS rule. It returns immediately after launching
// the background ring-buffer reader loop.
//
// Requires CAP_BPF (Linux ≥ 5.8) or CAP_SYS_ADMIN; returns a descriptive
// error otherwise. Also requires Linux ≥ 5.8 for BPF_MAP_TYPE_RINGBUF.
//
// Calling Start on an already-running watcher is a no-op (returns nil).
func (w *ProcessWatcher) Start(ctx context.Context) error {
	w.mu.Lock()
	defer w.mu.Unlock()

	if w.cancel != nil {
		return nil // already running
	}

	// Resolve BPF object bytes: instance-level override → package-level embed.
	objBytes := w.objBytes
	if len(objBytes) == 0 {
		objBytes = bpfObjectBytes
	}
	if len(objBytes) == 0 {
		return fmt.Errorf("ebpf process watcher: no BPF object available; " +
			"either build with -tags bpf_embedded (after running " +
			"\"make -C internal/watcher/ebpf\") or call SetBPFObject before Start")
	}

	obj, err := loadBPFObject(bytes.NewReader(objBytes))
	if err != nil {
		return fmt.Errorf("ebpf process watcher: load BPF object: %w", err)
	}

	ctx, cancel := context.WithCancel(ctx)
	w.cancel = cancel

	w.wg.Add(1)
	go w.readLoop(ctx, obj)

	w.logger.Info("ebpf process watcher started",
		slog.Int("rules", len(w.rules)),
		slog.String("mechanism", "eBPF/tracepoint+ringbuf"),
	)
	return nil
}

// Stop signals the watcher to cease monitoring, waits for the background loop
// to exit, and closes the Events channel. Stop is safe to call multiple times
// (idempotent).
func (w *ProcessWatcher) Stop() {
	w.stopOnce.Do(func() {
		w.mu.Lock()
		cancel := w.cancel
		w.cancel = nil
		w.mu.Unlock()

		if cancel != nil {
			cancel()
		}
		w.wg.Wait()

		close(w.events)
		w.logger.Info("ebpf process watcher stopped")
	})
}

// ─── Background loop ──────────────────────────────────────────────────────────

// readLoop is the background goroutine started by Start. It reads raw samples
// from the BPF ring buffer, decodes them into execEvent structs, and
// dispatches matching events. It exits when ctx is cancelled or the ring
// buffer returns an unrecoverable error.
func (w *ProcessWatcher) readLoop(ctx context.Context, obj *bpfObject) {
	defer w.wg.Done()
	defer obj.Close()

	for {
		select {
		case <-ctx.Done():
			return
		default:
		}

		sample, err := obj.ringbuf.readSample(ctx)
		if err != nil {
			// Context cancellation is normal shutdown.
			select {
			case <-ctx.Done():
				return
			default:
			}
			w.logger.Warn("ebpf process watcher: ring buffer read error",
				slog.Any("error", err),
			)
			return
		}

		if len(sample) != execEventSize {
			w.logger.Warn("ebpf process watcher: unexpected event size",
				slog.Int("got", len(sample)),
				slog.Int("want", execEventSize),
			)
			continue
		}

		var evt execEvent
		if err := binary.Read(bytes.NewReader(sample), binary.NativeEndian, &evt); err != nil {
			w.logger.Warn("ebpf process watcher: decode event", slog.Any("error", err))
			continue
		}

		w.handleEvent(&evt)
	}
}

// ─── Event handling ───────────────────────────────────────────────────────────

// handleEvent converts an execEvent into an AlertEvent and, if the event
// matches a configured PROCESS rule, delivers it via the events channel.
func (w *ProcessWatcher) handleEvent(evt *execEvent) {
	comm := nullTerminated(evt.Comm[:])
	filename := nullTerminated(evt.Filename[:])
	argv := nullTerminated(evt.Argv[:])

	// Try matching against the full filename first, then the comm name.
	rule := w.matchingRule(filename)
	if rule == nil {
		rule = w.matchingRule(comm)
	}
	if rule == nil {
		return // no configured rule matches this process
	}

	detail := map[string]any{
		"pid":  int(evt.PID),
		"ppid": int(evt.PPID),
		"uid":  int(evt.UID),
		"gid":  int(evt.GID),
		"comm": comm,
		"exe":  filename,
	}
	if argv != "" {
		detail["cmdline"] = argv
	}

	alert := watcher.AlertEvent{
		TripwireType: "PROCESS",
		RuleName:     rule.Name,
		Severity:     rule.Severity,
		Timestamp:    time.Now().UTC(),
		Detail:       detail,
	}

	select {
	case w.events <- alert:
	default:
		w.logger.Warn("ebpf process watcher: event channel full, dropping event",
			slog.String("rule", rule.Name),
			slog.Time("ts", alert.Timestamp),
		)
	}

	w.logger.Info("ebpf process watcher: execve alert",
		slog.String("rule", rule.Name),
		slog.Int("pid", int(evt.PID)),
		slog.String("exe", filename),
		slog.String("comm", comm),
	)
}

// matchingRule returns the first PROCESS rule whose Target glob pattern
// matches procName. The match is attempted against the base name first, then
// against the full path. An empty Target matches every process. Returns nil
// when no rule matches.
func (w *ProcessWatcher) matchingRule(procName string) *config.TripwireRule {
	base := filepath.Base(procName)
	for i := range w.rules {
		r := &w.rules[i]
		pat := r.Target
		if pat == "" {
			return r // wildcard
		}
		if ok, _ := filepath.Match(pat, base); ok {
			return r
		}
		if ok, _ := filepath.Match(pat, procName); ok {
			return r
		}
	}
	return nil
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

// nullTerminated returns the string content of buf up to and excluding the
// first NUL byte. If no NUL is present, the entire slice is returned as a
// string (this should not happen for well-formed kernel events).
func nullTerminated(buf []byte) string {
	if i := bytes.IndexByte(buf, 0); i >= 0 {
		return string(buf[:i])
	}
	return string(buf)
}
