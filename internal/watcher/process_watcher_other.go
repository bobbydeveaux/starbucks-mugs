//go:build !linux && !darwin

package watcher

import (
	"bufio"
	"bytes"
	"log/slog"
	"os/exec"
	"strconv"
	"strings"
	"time"
)

// newProcessBackend returns a polling-based process monitoring backend for
// platforms that are neither Linux nor macOS. It parses ps(1) output at a
// fixed interval to detect new process executions.
//
// This backend is a best-effort fallback; platforms that do not ship a
// POSIX-compatible ps(1) will see an empty process list and no alerts.
func newProcessBackend(logger *slog.Logger) processBackend {
	return &pollProcBackend{
		logger:   logger,
		interval: 500 * time.Millisecond,
	}
}

// pollProcBackend detects new process executions by periodically parsing the
// output of ps(1). It maintains a set of known PIDs and emits a ProcessEvent
// for each PID that appears between successive scans.
type pollProcBackend struct {
	logger   *slog.Logger
	interval time.Duration
}

// run polls for new processes at the configured interval until done is closed.
// Returns nil on clean shutdown or a non-nil error on unrecoverable failure.
func (b *pollProcBackend) run(done <-chan struct{}, events chan<- ProcessEvent) error {
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
						b.logger.Warn("process watcher: backend channel full; dropping event",
							slog.Int("pid", pe.PID))
					}
				}
			}
			seen = current
		}
	}
}

// scan enumerates all running processes by parsing ps(1) output.
// Returns an empty map on error so the caller sees no new processes this cycle.
func (b *pollProcBackend) scan() map[int]ProcessEvent {
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
