# TripWire Agent — Process Watcher

This document describes `ProcessWatcher`, the process execution monitor
in the `internal/watcher` package. It satisfies the
[`agent.Watcher`](agent-core.md#interfaces) interface and emits
`AlertEvent`s with `TripwireType: "PROCESS"` whenever a watched process
name is executed on the host.

---

## Overview

| Implementation | File | Platform | Mechanism |
|----------------|------|----------|-----------|
| `ProcessWatcher` | `process_watcher.go` | All | Platform backend (see below) |
| Linux backend | `process_watcher_linux.go` | Linux | eBPF (stub) → /proc polling |
| macOS backend | `process_watcher_darwin.go` | macOS | kqueue EVFILT_PROC + ps scan |
| Other backend | `process_watcher_other.go` | Other | ps(1) polling |

---

## Architecture

`ProcessWatcher` delegates all platform-specific monitoring to a
`processBackend` implementation chosen at construction time. This design
keeps the dispatch and alert-emission logic in one place while allowing
each platform to use the best available kernel interface.

```
ProcessWatcher (process_watcher.go)
    │
    ├── run()  ← background goroutine
    │       │
    │       ├── processBackend.run(done, events) ← platform backend
    │       │         sends ProcessEvents
    │       │
    │       └── dispatch(pe) → emit(pe, rule) → chan AlertEvent
    │
    └── Stop() / Events() / Ready()
```

### Backend selection

**Linux (process_watcher_linux.go)**

1. Attempt eBPF backend (`newEBPFBackend`). The eBPF loader
   (task-tripwire-cybersecurity-tool-feat-process-watcher-1/2) returns
   `errEBPFNotSupported` until the sub-package is integrated. When
   available, eBPF provides zero-overhead exec tracing via
   `execve`/`execveat` tracepoints on Linux ≥ 5.8.
2. Fall back to `/proc` polling (`linuxProcBackend`): scans `/proc` at
   500 ms intervals, detects new PIDs by comparing successive snapshots,
   and reads `Name`, `PPid`, `Uid`, and `/proc/<pid>/cmdline` from each
   entry. This is the "ptrace fallback" referenced in the task
   specification — it achieves the same coverage as ptrace-based exec
   tracing without requiring a persistent `ptrace(2)` relationship to
   every process.

**macOS (process_watcher_darwin.go)**

`darwinKqueueBackend` combines two mechanisms:

- **kqueue EVFILT_PROC / NOTE_EXEC**: registers kevent filters on
  known PIDs so that exec calls from already-tracked processes trigger
  an immediate event (sub-interval latency).
- **Periodic ps scan**: runs `ps -e -o pid=,ppid=,uid=,comm=` at 500 ms
  intervals to discover processes started before their parent was
  registered with kqueue.

If `kqueue(2)` fails (extremely rare), falls back to scan-only mode.

**Other platforms (process_watcher_other.go)**

Parses `ps -e -o pid=,ppid=,uid=,comm=` at 500 ms intervals.
Platforms that do not ship a POSIX-compatible `ps(1)` will see an empty
process list. No PROCESS alerts will be emitted on such platforms.

---

## ProcessWatcher

**File:** `internal/watcher/process_watcher.go` (all platforms)

```go
type ProcessWatcher struct { /* unexported */ }

func NewProcessWatcher(rules []config.TripwireRule, logger *slog.Logger) *ProcessWatcher
func (pw *ProcessWatcher) Start(ctx context.Context) error
func (pw *ProcessWatcher) Stop()
func (pw *ProcessWatcher) Events() <-chan AlertEvent
func (pw *ProcessWatcher) Ready() <-chan struct{}
```

### `NewProcessWatcher`

| Parameter | Description |
|-----------|-------------|
| `rules`   | Slice of `TripwireRule`; only `Type == "PROCESS"` entries are used. Non-PROCESS rules are silently ignored. |
| `logger`  | Structured logger for diagnostic messages. Passing `nil` uses `slog.Default()`. |

### Process name matching

Rule `Target` is matched against the process `Command` (name/basename)
using the following logic:

1. Exact string equality: `target == command`
2. Basename equality: `filepath.Base(target) == filepath.Base(command)`

This means a rule with `Target: "bash"` matches both `"bash"` and
`"/bin/bash"`. A rule with `Target: "/usr/sbin/sshd"` matches both
`"/usr/sbin/sshd"` and `"sshd"`.

### `Ready()`

`Ready()` returns a channel that is closed once the initial process
snapshot has been taken and the watcher is actively monitoring. Waiting
on this channel in tests before triggering process executions eliminates
races.

---

## AlertEvent payload

```json
{
  "tripwire_type": "PROCESS",
  "rule_name":     "nc-watch",
  "severity":      "CRITICAL",
  "timestamp":     "2026-02-26T10:00:00Z",
  "detail": {
    "pid":      12345,
    "ppid":     1000,
    "uid":      0,
    "username": "root",
    "command":  "nc",
    "cmdline":  "nc -lvp 4444"
  }
}
```

| Detail field | Type   | Description |
|--------------|--------|-------------|
| `pid`        | `int`  | Process identifier of the new process |
| `ppid`       | `int`  | Parent process identifier |
| `uid`        | `int`  | Numeric user ID that owns the process |
| `username`   | `string` | Human-readable username resolved from UID. Absent if lookup fails |
| `command`    | `string` | Process name or executable basename |
| `cmdline`    | `string` | Full command-line string (space-joined argv). Absent when not available (e.g. kernel threads) |

---

## Configuration

PROCESS-type rules in the agent configuration:

```yaml
rules:
  - name: nc-watch
    type: PROCESS
    target: nc
    severity: CRITICAL

  - name: bash-watch
    type: PROCESS
    target: bash
    severity: WARN

  - name: python-watch
    type: PROCESS
    target: python3
    severity: INFO

  - name: sshd-watch
    type: PROCESS
    target: /usr/sbin/sshd
    severity: INFO
```

See [`agent-configuration.md`](agent-configuration.md) for the full
configuration reference.

---

## Wiring into the agent

```go
// ProcessWatcher is constructed with the full rule list; non-PROCESS
// rules are silently filtered out.
pw := watcher.NewProcessWatcher(cfg.Rules, logger)

ag := agent.New(cfg, logger,
    agent.WithWatchers(pw),
    agent.WithQueue(q),
    agent.WithTransport(tr),
)

if err := ag.Start(ctx); err != nil {
    log.Fatal(err)
}
```

---

## eBPF integration (future)

When
[task-tripwire-cybersecurity-tool-feat-process-watcher-1](../../../docs/concepts/tripwire-cybersecurity-tool/tasks.yaml)
(eBPF kernel program) and
[task-tripwire-cybersecurity-tool-feat-process-watcher-2](../../../docs/concepts/tripwire-cybersecurity-tool/tasks.yaml)
(Go userspace loader) are completed, the Linux backend's `newEBPFBackend`
stub should be replaced with a call to the eBPF loader. The `ProcessWatcher`
itself does not need to change — only `newEBPFBackend` in
`process_watcher_linux.go` needs updating.

**Integration point:**

```go
// In process_watcher_linux.go — replace the stub with:
func newEBPFBackend(logger *slog.Logger) (processBackend, error) {
    return ebpf.NewProcessLoader(logger) // from internal/watcher/ebpf/process.go
}
```

---

## Running the tests

```bash
# All process watcher tests (uses mock backend, no root required)
go test -v -run TestProcessWatcher ./internal/watcher/...

# All watcher tests
go test -v ./internal/watcher/...

# With race detector
go test -race ./internal/watcher/...
```

---

## Test coverage

### ProcessWatcher (`process_watcher_test.go`)

| Test | Description |
|------|-------------|
| `TestProcessWatcher_ImplementsWatcherInterface` | Compile-time interface check |
| `TestNewProcessWatcher_FiltersNonProcessRules` | Non-PROCESS rules are ignored |
| `TestNewProcessWatcher_NilLogger` | nil logger does not panic |
| `TestProcessWatcher_StartStop` | Lifecycle: Start and Stop complete cleanly |
| `TestProcessWatcher_StopIsIdempotent` | Double-Stop does not panic |
| `TestProcessWatcher_EventsChannelClosedAfterStop` | Channel closed after Stop |
| `TestProcessWatcher_ReadyChannelClosedAfterStart` | Ready() fires after Start |
| `TestProcessWatcher_StopBeforeStart` | Stop before Start is safe |
| `TestProcessWatcher_EmitsAlertEventOnMatch` | Alert emitted for matching process |
| `TestProcessWatcher_DropsNonMatchingEvents` | Non-matching processes are dropped |
| `TestProcessWatcher_MatchesByBasename` | `/bin/bash` matches rule target `bash` |
| `TestProcessWatcher_MultipleRulesCanMatch` | Single event triggers multiple rules |
| `TestProcessWatcher_EmptyRuleList` | No alerts when no PROCESS rules |
| `TestProcessWatcher_NoCmdlineInDetail` | `cmdline` absent when CmdLine is empty |
| `TestProcessWatcher_BackendErrorDoesNotPanic` | Backend error handled gracefully |
| `TestMatchProcessName` | Unit tests for basename matching logic |

All tests use an injected mock backend (`stubBackend`) so they run
without root privileges and without spawning real processes.
