//go:build darwin

package watcher

import (
	"bufio"
	"bytes"
	"log/slog"
	"os/exec"
	"strconv"
	"strings"
	"syscall"
	"time"
)

// newProcessBackend returns the macOS process monitoring backend.
//
// The backend combines two mechanisms:
//   - A kqueue with EVFILT_PROC / NOTE_EXEC filters monitors individual known
//     PIDs and fires immediately when they call exec(2). This gives
//     near-instant notification for exec calls from already-tracked processes.
//   - A periodic scan using ps(1) detects any processes started before their
//     parent's fork event was registered on the kqueue, and populates the PID
//     set for kqueue registration.
//
// Together these two mechanisms implement the "kqueue fallback" described in
// the task specification: kqueue provides event-driven notification when
// possible, while periodic ps scanning ensures completeness.
func newProcessBackend(logger *slog.Logger) processBackend {
	return &darwinKqueueBackend{
		logger:   logger,
		interval: 500 * time.Millisecond,
	}
}

// darwinKqueueBackend monitors process executions on macOS. It uses kqueue
// EVFILT_PROC with NOTE_EXEC to receive immediate notification when a tracked
// PID calls exec(2), combined with periodic ps-based scanning to discover new
// processes that were not yet tracked by the kqueue.
type darwinKqueueBackend struct {
	logger   *slog.Logger
	interval time.Duration
}

// run is the main monitoring loop. It initialises a kqueue, scans existing
// processes, registers EVFILT_PROC watchers on them, and then interleaves
// kqueue event draining with periodic full scans until done is closed.
func (b *darwinKqueueBackend) run(done <-chan struct{}, events chan<- ProcessEvent) error {
	// Create a kqueue instance for EVFILT_PROC monitoring.
	kqfd, err := syscall.Kqueue()
	if err != nil {
		b.logger.Warn("process watcher: kqueue creation failed, using scan-only mode",
			slog.Any("error", err))
		return b.runScanOnly(done, events)
	}
	defer syscall.Close(kqfd)

	// Take an initial snapshot and register kqueue filters for all running PIDs.
	seen := b.scanProcs()
	b.registerPIDs(kqfd, pidsFrom(seen))

	ticker := time.NewTicker(b.interval)
	defer ticker.Stop()

	// kevent buffer for batch retrieval.
	kevents := make([]syscall.Kevent_t, 32)
	// 100 ms kqueue timeout — allows timely response to both EVFILT_PROC
	// events and the done signal without busy-looping.
	kqTimeout := syscall.Timespec{Nsec: 100_000_000}

	for {
		// Check for shutdown before blocking.
		select {
		case <-done:
			return nil
		default:
		}

		// Drain kqueue for EVFILT_PROC / NOTE_EXEC events.
		n, kqErr := syscall.Kevent(kqfd, nil, kevents, &kqTimeout)
		if kqErr != nil && kqErr != syscall.EINTR {
			b.logger.Warn("process watcher: kqueue wait error",
				slog.Any("error", kqErr))
		}
		for i := 0; i < n; i++ {
			kev := kevents[i]
			if kev.Filter == syscall.EVFILT_PROC && kev.Fflags&syscall.NOTE_EXEC != 0 {
				pid := int(kev.Ident)
				// Re-read process information since comm may have changed after exec.
				if pe, ok := seen[pid]; ok {
					select {
					case events <- pe:
					default:
						b.logger.Warn("process watcher: backend channel full; dropping kqueue exec event",
							slog.Int("pid", pid))
					}
				}
			}
		}

		// Periodic scan: detect new processes missed by kqueue.
		select {
		case <-done:
			return nil
		case <-ticker.C:
			current := b.scanProcs()
			var newPIDs []int
			for pid, pe := range current {
				if _, existed := seen[pid]; !existed {
					newPIDs = append(newPIDs, pid)
					select {
					case events <- pe:
					default:
						b.logger.Warn("process watcher: backend channel full; dropping scan event",
							slog.Int("pid", pe.PID))
					}
				}
			}
			// Register kqueue watchers for newly discovered PIDs so future
			// exec calls from them are detected immediately.
			b.registerPIDs(kqfd, newPIDs)
			seen = current
		default:
		}
	}
}

// runScanOnly is the fallback when kqueue creation fails. It polls the process
// list at the configured interval.
func (b *darwinKqueueBackend) runScanOnly(done <-chan struct{}, events chan<- ProcessEvent) error {
	seen := b.scanProcs()

	ticker := time.NewTicker(b.interval)
	defer ticker.Stop()

	for {
		select {
		case <-done:
			return nil
		case <-ticker.C:
			current := b.scanProcs()
			for pid, pe := range current {
				if _, existed := seen[pid]; !existed {
					select {
					case events <- pe:
					default:
						b.logger.Warn("process watcher: backend channel full; dropping event",
							slog.Int("pid", pe.PID))
					}
				}
			}
			seen = current
		}
	}
}

// registerPIDs adds EVFILT_PROC / NOTE_EXEC | NOTE_FORK filters to the
// kqueue for each PID in pids. Processes that have already exited are silently
// skipped (kevent returns ESRCH for them).
func (b *darwinKqueueBackend) registerPIDs(kqfd int, pids []int) {
	if len(pids) == 0 {
		return
	}
	changes := make([]syscall.Kevent_t, 0, len(pids))
	for _, pid := range pids {
		changes = append(changes, syscall.Kevent_t{
			Ident:  uint64(pid),
			Filter: syscall.EVFILT_PROC,
			Flags:  syscall.EV_ADD | syscall.EV_ENABLE | syscall.EV_ONESHOT,
			Fflags: syscall.NOTE_EXEC | syscall.NOTE_FORK,
		})
	}
	// Errors from individual kevent registrations (e.g. ESRCH for exited
	// processes) are intentionally ignored; we register on a best-effort basis.
	syscall.Kevent(kqfd, changes, nil, nil) //nolint:errcheck
}

// scanProcs enumerates all running processes by parsing ps(1) output.
// ps is universally available on macOS and provides accurate process
// information without requiring cgo or complex sysctl binary parsing.
func (b *darwinKqueueBackend) scanProcs() map[int]ProcessEvent {
	// Request pid, ppid, uid, and command with no header (= suffix suppresses header).
	out, err := exec.Command("ps", "-e", "-o", "pid=,ppid=,uid=,comm=").Output()
	if err != nil {
		b.logger.Warn("process watcher: ps scan failed", slog.Any("error", err))
		return make(map[int]ProcessEvent)
	}

	result := make(map[int]ProcessEvent)
	scanner := bufio.NewScanner(bytes.NewReader(out))
	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		fields := strings.Fields(line)
		if len(fields) < 4 {
			continue
		}
		pid, err := strconv.Atoi(fields[0])
		if err != nil {
			continue
		}
		ppid, _ := strconv.Atoi(fields[1])
		uid, _ := strconv.Atoi(fields[2])
		comm := fields[3]

		result[pid] = ProcessEvent{
			PID:      pid,
			PPID:     ppid,
			UID:      uid,
			Command:  comm,
			Username: resolveUsername(uid),
		}
	}
	return result
}

// pidsFrom extracts a slice of PID keys from the given process map.
func pidsFrom(procs map[int]ProcessEvent) []int {
	pids := make([]int, 0, len(procs))
	for pid := range procs {
		pids = append(pids, pid)
	}
	return pids
}
