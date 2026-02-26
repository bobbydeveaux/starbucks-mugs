// macOS implementation of ProcessWatcher using kqueue EVFILT_PROC.
//
// On Darwin there is no NETLINK_CONNECTOR or /proc filesystem. Instead,
// kqueue's EVFILT_PROC filter is used to receive NOTE_EXEC notifications when
// a watched process calls execve. Because EVFILT_PROC requires a specific PID
// (it is not a system-wide subscription), two complementary mechanisms work
// together:
//
//  1. kqueue event loop — NOTE_EXEC fires for already-tracked PIDs; NOTE_FORK
//     fires when a tracked process spawns a child; NOTE_TRACK asks the kernel
//     to auto-register the child for the same events so exec detection is
//     transitive for any process descended from one we already watch.
//
//  2. Poll loop — every pollInterval the full process list is re-enumerated
//     via `ps` and any PID not yet in the kqueue is added. This acts as a
//     safety net for: (a) processes that existed before the watcher started,
//     (b) children where NOTE_TRACK failed (NOTE_TRACKERR) because the kernel
//     ran out of kqueue resources or lacked permission.
//
// Privilege requirement:
//
//   - kqueue itself requires no privilege.
//   - EVFILT_PROC filters succeed only for processes owned by the current user
//     (or all processes when running as root). Filters for other users' processes
//     silently fail in addPID, which is expected and harmless.
//   - KERN_PROCARGS2 sysctl (used to read process details after NOTE_EXEC)
//     requires the requesting process to have the same effective UID as the
//     target process, or root. Falls back to an empty string when unavailable.
//
// Known limitations (fallback vs Linux NETLINK):
//
//   - Processes that spawn and exit faster than the poll interval may be missed
//     if they are not descendants of a process we are already watching.
//   - KERN_PROCARGS2 may return no data if the target process has already exited
//     by the time we read it; in that case only the PID is recorded in Detail.
//
//go:build darwin

package watcher

import (
	"bytes"
	"context"
	"fmt"
	"log/slog"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
)

// ─── Darwin-specific EVFILT_PROC NOTE flags ──────────────────────────────────
// These constants come from /usr/include/sys/event.h on macOS. They are stable
// kernel ABI but are absent from Go's syscall package.

const (
	// noteTrack asks the kernel to automatically register the same EVFILT_PROC
	// filters on any process forked from the watched PID (NOTE_TRACK = 0x1).
	noteTrack uint32 = 0x00000001

	// noteTrackErr is set in Fflags when NOTE_TRACK was requested but the
	// kernel could not register the forked child (NOTE_TRACKERR = 0x2). The
	// poll loop will re-discover the missed process on the next tick.
	noteTrackErr uint32 = 0x00000002

	// noteChild is set in Fflags of an event that was auto-registered on a
	// forked child via NOTE_TRACK (NOTE_CHILD = 0x4). The parent's PID is
	// in the Data field of that event.
	noteChild uint32 = 0x00000004
)

// procKqueueFflags is the EVFILT_PROC filter combination registered on every
// watched PID:
//
//   - NOTE_EXEC  — fires when the process calls execve (alert trigger).
//   - NOTE_FORK  — fires when the process forks; child PID is in Data.
//   - NOTE_EXIT  — fires on process exit so we can clean up tracked state.
//   - noteTrack  — requests recursive tracking of forked children.
const procKqueueFflags uint32 = syscall.NOTE_EXEC | syscall.NOTE_FORK | syscall.NOTE_EXIT | noteTrack

// processKqueuePollInterval controls how often the running process list is
// re-scanned to pick up processes not yet tracked by kqueue.
const processKqueuePollInterval = 500 * time.Millisecond

// procKqueueState holds the mutable kqueue state shared between the two
// background goroutines. All fields except kqfd are protected by mu. kqfd is
// written only in Start (before goroutines start) and closed only by the
// kqueue goroutine (after context cancellation), so there is no concurrent
// access to kqfd itself between goroutines at runtime.
type procKqueueState struct {
	kqfd int
	mu   sync.Mutex
	pids map[int]struct{} // PIDs currently registered in kqueue
}

// addPID registers a kqueue EVFILT_PROC filter on pid if it is not already
// tracked. EPERM (other user's process), ESRCH (process gone), and all other
// errors from kevent(2) are silently ignored — they are expected in normal
// operation.
func (s *procKqueueState) addPID(pid int) {
	s.mu.Lock()
	defer s.mu.Unlock()

	if _, exists := s.pids[pid]; exists {
		return
	}

	kev := syscall.Kevent_t{
		Ident:  uint64(pid),
		Filter: syscall.EVFILT_PROC,
		Flags:  syscall.EV_ADD | syscall.EV_ENABLE | syscall.EV_CLEAR,
		Fflags: procKqueueFflags,
	}
	if _, err := syscall.Kevent(s.kqfd, []syscall.Kevent_t{kev}, nil, nil); err == nil {
		s.pids[pid] = struct{}{}
	}
	// On error (EPERM, ESRCH, etc.) we do not add to pids; the poll loop will
	// retry on the next tick if the process is still alive and accessible.
}

// removePID removes pid from the tracked set. It does not send EV_DELETE to
// kqueue because kqueue automatically removes the filter when the process exits.
func (s *procKqueueState) removePID(pid int) {
	s.mu.Lock()
	defer s.mu.Unlock()
	delete(s.pids, pid)
}

// ─── Start / Stop ─────────────────────────────────────────────────────────────

// Start opens a kqueue, seeds the initial watchlist with all running processes,
// and launches two background goroutines (kqueue event loop and poll loop). It
// returns immediately after the goroutines are started.
//
// Start is a no-op (returns nil) if the watcher is already running.
func (w *ProcessWatcher) Start(ctx context.Context) error {
	w.mu.Lock()
	defer w.mu.Unlock()

	if w.cancel != nil {
		return nil // already running
	}

	kqfd, err := syscall.Kqueue()
	if err != nil {
		return fmt.Errorf("process watcher: kqueue: %w", err)
	}

	state := &procKqueueState{
		kqfd: kqfd,
		pids: make(map[int]struct{}),
	}

	// Seed the initial process list. addPID silently ignores permission errors
	// for processes owned by other users.
	for _, pid := range listRunningPIDs() {
		state.addPID(pid)
	}

	ctx, cancel := context.WithCancel(ctx)
	w.cancel = cancel

	w.wg.Add(2)
	go w.runProcKqueueLoop(ctx, state)
	go w.runProcPollLoop(ctx, state)

	w.logger.Info("process watcher started",
		slog.Int("rules", len(w.rules)),
		slog.String("mechanism", "kqueue/EVFILT_PROC+NOTE_EXEC+poll"),
	)
	return nil
}

// Stop signals the background goroutines to exit, waits for them to finish,
// then closes the Events channel. Safe to call multiple times (idempotent).
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
		w.logger.Info("process watcher stopped")
	})
}

// ─── kqueue event loop ────────────────────────────────────────────────────────

// runProcKqueueLoop is the primary background goroutine. It calls kevent(2)
// with a 100 ms timeout so the shutdown check inside the select fires promptly
// when the context is cancelled.
func (w *ProcessWatcher) runProcKqueueLoop(ctx context.Context, state *procKqueueState) {
	defer w.wg.Done()
	defer func() { _ = syscall.Close(state.kqfd) }()

	events := make([]syscall.Kevent_t, 32)
	timeout := syscall.Timespec{Nsec: 100_000_000} // 100 ms

	for {
		select {
		case <-ctx.Done():
			return
		default:
		}

		n, err := syscall.Kevent(state.kqfd, nil, events, &timeout)
		if err != nil {
			if err == syscall.EINTR {
				continue
			}
			select {
			case <-ctx.Done():
				return
			default:
			}
			w.logger.Warn("process watcher: kevent error", slog.Any("error", err))
			return
		}

		for i := 0; i < n; i++ {
			w.handleProcKevent(state, &events[i])
		}
	}
}

// handleProcKevent dispatches a single EVFILT_PROC kqueue event.
func (w *ProcessWatcher) handleProcKevent(state *procKqueueState, ev *syscall.Kevent_t) {
	pid := int(ev.Ident)
	fflags := ev.Fflags

	switch {
	case fflags&syscall.NOTE_EXEC != 0:
		// Process called execve. Enrich with process details and emit if a
		// PROCESS rule matches.
		comm, exe, cmdline := darwinProcInfo(pid)
		w.emitExecEvent(pid, comm, exe, cmdline)

	case fflags&syscall.NOTE_FORK != 0:
		// The watched process forked. Data contains the child PID. NOTE_TRACK
		// should auto-register the child in kqueue, but we also call addPID
		// as a belt-and-suspenders backup for when NOTE_TRACK fails.
		childPID := int(ev.Data)
		if childPID > 0 {
			state.addPID(childPID)
		}

	case fflags&noteTrackErr != 0:
		// NOTE_TRACK could not register the forked child. The poll loop will
		// re-discover and add it on the next tick.
		w.logger.Debug("process watcher: NOTE_TRACKERR — child not tracked",
			slog.Int("pid", pid),
		)

	case fflags&noteChild != 0:
		// This event fires on a child process that was auto-registered via
		// NOTE_TRACK. Record it in pids so addPID skips it in future polls.
		state.mu.Lock()
		state.pids[pid] = struct{}{}
		state.mu.Unlock()

	case fflags&syscall.NOTE_EXIT != 0:
		// Process exited; remove from tracked set. kqueue drops the filter
		// automatically on process exit.
		state.removePID(pid)
	}
}

// ─── Poll loop ────────────────────────────────────────────────────────────────

// runProcPollLoop periodically enumerates all running PIDs and adds any that
// are not yet tracked to the kqueue. This acts as a safety net for:
//   - Processes that existed before the watcher started.
//   - Children whose NOTE_TRACK registration failed (NOTE_TRACKERR).
func (w *ProcessWatcher) runProcPollLoop(ctx context.Context, state *procKqueueState) {
	defer w.wg.Done()

	ticker := time.NewTicker(processKqueuePollInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			for _, pid := range listRunningPIDs() {
				state.addPID(pid)
			}
		}
	}
}

// ─── Process info helpers ─────────────────────────────────────────────────────

// darwinProcInfo reads the executable path, comm (base name), and command-line
// for the given PID using the KERN_PROCARGS2 sysctl. This sysctl returns a
// variable-length buffer with the following layout:
//
//	[4 bytes]  argc as little-endian int32
//	[n bytes]  NUL-terminated exec path, followed by NUL padding to align
//	[n bytes]  NUL-terminated argv[0], argv[1], …, envp[0], …
//
// If the process has already exited or the caller lacks permission, empty
// strings are returned for comm and exe and an empty cmdline string is returned.
// In that case, the caller still emits the event using only the PID.
func darwinProcInfo(pid int) (comm, exe, cmdline string) {
	raw, err := syscall.SysctlRaw("kern.procargs2", int32(pid))
	if err != nil || len(raw) < 4 {
		return "", "", ""
	}

	// Skip the 4-byte argc prefix; we do not need the argument count.
	rest := raw[4:]

	// The first NUL-terminated string is the executable path.
	if idx := bytes.IndexByte(rest, 0); idx >= 0 {
		exe = string(rest[:idx])
		rest = rest[idx+1:]
	} else {
		return "", "", ""
	}

	comm = filepath.Base(exe)

	// After the exe path there is NUL padding to align to a pointer boundary.
	for len(rest) > 0 && rest[0] == 0 {
		rest = rest[1:]
	}

	// Collect argv strings (argv[0] through argv[argc-1]). We cap at 64 args
	// to avoid walking into the environment section for unusual binaries.
	var args []string
	for len(rest) > 0 && len(args) < 64 {
		idx := bytes.IndexByte(rest, 0)
		if idx < 0 {
			if len(rest) > 0 {
				args = append(args, string(rest))
			}
			break
		}
		if idx > 0 {
			args = append(args, string(rest[:idx]))
		}
		rest = rest[idx+1:]
	}

	cmdline = strings.Join(args, " ")
	return comm, exe, cmdline
}

// listRunningPIDs returns the PIDs of all currently running processes on the
// system by invoking `ps -axo pid=`. An empty slice is returned on any error.
func listRunningPIDs() []int {
	out, err := exec.Command("ps", "-axo", "pid=").Output()
	if err != nil {
		return nil
	}

	var pids []int
	for _, line := range strings.Split(strings.TrimSpace(string(out)), "\n") {
		line = strings.TrimSpace(line)
		if pid, err := strconv.Atoi(line); err == nil && pid > 0 {
			pids = append(pids, pid)
		}
	}
	return pids
}
