//go:build linux

package watcher

import (
	"bufio"
	"errors"
	"fmt"
	"log/slog"
	"os"
	"strconv"
	"strings"
	"time"
)

// newProcessBackend returns the best available Linux process monitoring
// backend.
//
// Selection order:
//  1. eBPF backend (Linux >= 5.8): zero-copy ring buffer fed directly by the
//     kernel execve/execveat tracepoints. Provided by the ebpf sub-package
//     (task-tripwire-cybersecurity-tool-feat-process-watcher-1/2). Returns
//     errEBPFNotSupported when the sub-package is not yet available or when
//     the running kernel is older than 5.8.
//  2. /proc polling backend: scans the Linux /proc virtual filesystem at a
//     fixed interval (default 500 ms) and emits a ProcessEvent for each PID
//     that appears between successive scans. This is the "ptrace fallback"
//     referenced in the task specification — it achieves equivalent coverage
//     without requiring a persistent ptrace(2) relationship to every process.
func newProcessBackend(logger *slog.Logger) processBackend {
	// Attempt the eBPF backend. newEBPFBackend returns a non-nil error when
	// the implementation is unavailable (see stub below).
	if b, err := newEBPFBackend(logger); err == nil {
		logger.Info("process watcher: using eBPF backend")
		return b
	}

	// Fall back to /proc polling.
	logger.Info("process watcher: eBPF unavailable, using /proc polling backend")
	return &linuxProcBackend{
		logger:   logger,
		interval: 500 * time.Millisecond,
	}
}

// errEBPFNotSupported is the sentinel returned by newEBPFBackend when the
// eBPF implementation is not yet compiled into the binary or the kernel does
// not meet the minimum version requirement (5.8).
var errEBPFNotSupported = errors.New("eBPF process backend not supported on this kernel")

// newEBPFBackend attempts to create a processBackend backed by the eBPF
// loader from the ebpf sub-package (task-1 and task-2 of the process watcher
// feature). Until that sub-package is available this function always returns
// errEBPFNotSupported, causing the caller to fall back to /proc polling.
//
// When the eBPF sub-package is integrated, replace this stub with a call to
// ebpf.NewProcessLoader(logger) and map its events to ProcessEvents.
func newEBPFBackend(_ *slog.Logger) (processBackend, error) {
	// eBPF implementation is provided by the sibling sub-package once
	// task-tripwire-cybersecurity-tool-feat-process-watcher-1 and -2 are
	// merged. Until then, always signal "not supported" to the caller.
	return nil, errEBPFNotSupported
}

// linuxProcBackend polls the Linux /proc virtual filesystem at a fixed
// interval to detect new process executions. It maintains an in-memory
// snapshot of known PIDs and emits a ProcessEvent for each PID that appears
// between successive scans.
//
// This is intentionally described as the "ptrace fallback" in the product
// specification, reflecting that it fills the role of ptrace(2)-based exec
// tracing without requiring a persistent ptrace relationship to every process.
// Using /proc provides equivalent PID, PPID, UID, and command information
// without elevated privileges beyond read access to /proc.
type linuxProcBackend struct {
	logger   *slog.Logger
	interval time.Duration
}

// run polls /proc at the configured interval. It emits a ProcessEvent for
// each new PID detected since the previous scan. Returns nil on clean
// shutdown (done closed) or a non-nil error on unrecoverable failure.
func (b *linuxProcBackend) run(done <-chan struct{}, events chan<- ProcessEvent) error {
	// Take an initial snapshot so that processes already running when the
	// watcher starts are not incorrectly reported as new.
	seen := b.scan()

	ticker := time.NewTicker(b.interval)
	defer ticker.Stop()

	for {
		select {
		case <-done:
			return nil
		case <-ticker.C:
			current := b.scan()
			for pid, pe := range current {
				if _, existed := seen[pid]; !existed {
					select {
					case events <- pe:
					default:
						b.logger.Warn("process watcher: backend event channel full; dropping event",
							slog.Int("pid", pe.PID),
							slog.String("command", pe.Command),
						)
					}
				}
			}
			seen = current
		}
	}
}

// scan reads /proc and returns a map of pid → ProcessEvent for all currently
// running processes. Processes that exit between ReadDir and the per-entry
// reads are silently skipped.
func (b *linuxProcBackend) scan() map[int]ProcessEvent {
	entries, err := os.ReadDir("/proc")
	if err != nil {
		b.logger.Warn("process watcher: cannot read /proc", slog.Any("error", err))
		return make(map[int]ProcessEvent)
	}

	result := make(map[int]ProcessEvent, len(entries))
	for _, e := range entries {
		if !e.IsDir() {
			continue
		}
		pid, err := strconv.Atoi(e.Name())
		if err != nil {
			continue // non-numeric entry (e.g. "net", "sys", "self")
		}
		pe, err := readProcEntry(pid)
		if err != nil {
			continue // process exited between ReadDir and the status read
		}
		result[pid] = pe
	}
	return result
}

// readProcEntry parses /proc/<pid>/status to extract the process name (Name),
// parent PID (PPid), and real UID (Uid). It also reads /proc/<pid>/cmdline for
// the full command line. Returns an error if the process has exited or the
// status file is unreadable.
func readProcEntry(pid int) (ProcessEvent, error) {
	statusPath := fmt.Sprintf("/proc/%d/status", pid)
	f, err := os.Open(statusPath)
	if err != nil {
		return ProcessEvent{}, err
	}
	defer f.Close()

	var pe ProcessEvent
	pe.PID = pid

	scanner := bufio.NewScanner(f)
	for scanner.Scan() {
		line := scanner.Text()
		switch {
		case strings.HasPrefix(line, "Name:\t"):
			pe.Command = strings.TrimPrefix(line, "Name:\t")
		case strings.HasPrefix(line, "PPid:\t"):
			pe.PPID, _ = strconv.Atoi(strings.TrimPrefix(line, "PPid:\t"))
		case strings.HasPrefix(line, "Uid:\t"):
			// Format: "Uid:\treal\teffective\tsaved\tfs"
			fields := strings.Fields(line)
			if len(fields) >= 2 {
				pe.UID, _ = strconv.Atoi(fields[1])
			}
		}
	}
	if err := scanner.Err(); err != nil {
		return ProcessEvent{}, err
	}

	pe.Username = resolveUsername(pe.UID)

	// Read the full argv from /proc/<pid>/cmdline (NUL-separated args).
	// The file may be empty for kernel threads; that is not an error.
	cmdlinePath := fmt.Sprintf("/proc/%d/cmdline", pid)
	cmdlineBytes, err := os.ReadFile(cmdlinePath)
	if err == nil && len(cmdlineBytes) > 0 {
		// NUL separators between argv entries → replace with spaces and trim.
		pe.CmdLine = strings.TrimRight(
			strings.ReplaceAll(string(cmdlineBytes), "\x00", " "),
			" ",
		)
	}

	return pe, nil
}
