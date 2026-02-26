# TripWire Agent — Process Watcher

This document describes the process monitoring components that implement
the [`agent.Watcher`](agent-core.md#interfaces) interface. The `ProcessWatcher`
emits `AlertEvent`s with `TripwireType: "PROCESS"` whenever a watched process
name is executed on the host, using kernel-level mechanisms to trace
`execve`/`execveat` syscalls.

---

## Overview

The Process Watcher emits an `AlertEvent` (with `TripwireType: "PROCESS"`) whenever
a configured process name pattern is matched against a newly exec'd process.
It is designed as a multi-layer system with platform-specific backends:

| Implementation | File | Platform | Mechanism |
|----------------|------|----------|-----------|
| `ProcessWatcher` | `process_watcher.go` | All | Platform backend (see below) |
| Linux backend | `process_watcher_linux.go` | Linux | NETLINK_CONNECTOR (kernel-driven) |
| macOS backend | `process_watcher_darwin.go` | macOS | kqueue EVFILT_PROC + ps scan |
| Other backend | `process_watcher_other.go` | Other | ps(1) polling |

The companion eBPF C program in `internal/watcher/ebpf/process.bpf.c` documents
the equivalent BPF tracepoint implementation for environments with BPF compiler
tooling. The Go eBPF loader in `internal/watcher/ebpf/process.go` provides a
`Loader` interface that loads the pre-compiled BPF object and delivers typed
`ExecEvent` values (see [Go eBPF Loader](#go-ebpf-loader) below).

### Choosing a runtime

| | eBPF loader (`ebpf.Loader`) | NETLINK_CONNECTOR (`watcher.ProcessWatcher`) |
|---|---|---|
| **Kernel req.** | Linux ≥ 5.8, `CAP_BPF` | Any Linux, `CAP_NET_ADMIN` |
| **argv capture** | In-kernel (race-free) | /proc read (TOCTOU risk) |
| **PPID / UID / GID** | Always available | Not available |
| **BPF toolchain** | Required to compile .bpf.o | Not required |
| **Deployment** | Build with `make -C internal/watcher/ebpf` | Standard build |

---

## Architecture

`ProcessWatcher` delegates all platform-specific monitoring to a
`processBackend` implementation chosen at construction time. This design
keeps the dispatch and alert-emission logic in one place while allowing
each platform to use the best available kernel interface.

```
ProcessWatcher (process_watcher.go)
    │
    ├── Start()  ← optional backendStarter.start() for privileged init
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

Uses the **NETLINK_CONNECTOR** process connector to receive `PROC_EVENT_EXEC`
notifications from the kernel. This mechanism delivers exec event notifications
with zero polling overhead and is semantically equivalent to the eBPF tracepoint
program.

Privilege requirement: opening a `NETLINK_CONNECTOR` socket requires
`CAP_NET_ADMIN` or root (uid 0). If the agent lacks these privileges, `Start`
returns a descriptive error immediately.

**macOS (process_watcher_darwin.go)**

`darwinKqueueBackend` combines two mechanisms:

- **kqueue EVFILT_PROC / NOTE_EXEC**: registers kevent filters on known PIDs
  so that exec calls from already-tracked processes trigger an immediate event.
- **Periodic ps scan**: runs `ps -e -o pid=,ppid=,uid=,comm=` at 500 ms
  intervals to discover processes started before their parent was registered
  with kqueue.

If `kqueue(2)` fails (extremely rare), falls back to scan-only mode.

**Other platforms (process_watcher_other.go)**

Parses `ps -e -o pid=,ppid=,uid=,comm=` at 500 ms intervals. Platforms that do
not ship a POSIX-compatible `ps(1)` will see an empty process list. No PROCESS
alerts will be emitted on such platforms.

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

1. Empty `Target`: matches every process (catch-all wildcard).
2. Exact string equality: `target == command`
3. Basename equality: `filepath.Base(target) == filepath.Base(command)`
4. Glob pattern: `filepath.Match(target, basename)` or `filepath.Match(target, fullpath)`

This means a rule with `Target: "bash"` matches both `"bash"` and
`"/bin/bash"`. A rule with `Target: "/usr/sbin/sshd"` matches both
`"/usr/sbin/sshd"` and `"sshd"`. A rule with `Target: "python*"` matches
`"python3"`, `"python3.11"`, etc.

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
    target: "python*"    # glob: matches python3, python3.11, etc.
    severity: INFO

  - name: sshd-watch
    type: PROCESS
    target: /usr/sbin/sshd
    severity: INFO

  - name: any-process
    type: PROCESS
    target: ""           # empty = catch all execve events
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

The eBPF kernel program in `internal/watcher/ebpf/process.bpf.c` attaches to
`tracepoint/syscalls/sys_enter_execve` and `tracepoint/syscalls/sys_enter_execveat`
hooks, capturing process events into a BPF ring buffer. The companion Go
userspace loader in `internal/watcher/ebpf/process.go` reads from the ring
buffer and converts events to `ExecEvent` structs.

When the eBPF sub-package is fully integrated, the Linux backend's `newEBPFBackend`
stub can be replaced with a call to the eBPF loader. The `ProcessWatcher`
itself does not need to change — only the backend selection in
`process_watcher_linux.go` needs updating.

### eBPF kernel requirements

- Linux ≥ 5.8 — BPF ring buffer (`BPF_MAP_TYPE_RINGBUF`)
- `CONFIG_BPF_SYSCALL=y`, `CONFIG_DEBUG_INFO_BTF=y` (for CO-RE)
- `CAP_BPF` (Linux ≥ 5.8) or `CAP_SYS_ADMIN`

---

## Go eBPF Loader (`ebpf.Loader`)

Package `internal/watcher/ebpf` provides a Go userspace component that loads
the pre-compiled `process.bpf.o`, attaches the tracepoints, reads events from
the BPF ring buffer, and delivers them as `ExecEvent` values.

### Architecture

```
                  kernel (Linux ≥ 5.8)
┌─────────────────────────────────────────────────────────┐
│  Process calls execve(2) / execveat(2)                  │
│         ↓                                                │
│  BPF tracepoint fires (sys_enter_execve / execveat)     │
│         ↓                                                │
│  fill_event() captures pid, ppid, uid, gid,             │
│               comm, filename, argv                       │
│         ↓                                                │
│  bpf_ringbuf_submit() — writes exec_event to ring buf   │
└──────────────────────────────┬──────────────────────────┘
                               │ mmap (shared ring buffer)
                    ┌──────────▼──────────┐
                    │ readLoop()           │  ringbuf.Reader polls
                    └──────────┬──────────┘
                               │ binary.Read() → ExecEvent{}
                               ↓
                         Events() channel
```

### Usage

```go
import "github.com/tripwire/agent/internal/watcher/ebpf"

l, err := ebpf.NewLoader(logger)
if err != nil {
    // ebpf.ErrNotSupported if kernel < 5.8; fall back to NETLINK_CONNECTOR
    log.Fatal(err)
}
defer l.Close()

if err := l.Load(ctx); err != nil {
    log.Fatal(err)
}

for evt := range l.Events() {
    fmt.Printf("execve: pid=%d filename=%s argv=%s\n",
        evt.PID, evt.Filename, evt.Argv)
}
```

### `ExecEvent` fields (eBPF variant)

The eBPF loader captures richer metadata than the NETLINK_CONNECTOR variant
because all fields are read atomically in the kernel at exec time:

```go
ExecEvent{
    PID:      <uint32>,  // process ID (tgid)
    PPID:     <uint32>,  // parent process ID (captured in-kernel)
    UID:      <uint32>,  // real UID (captured in-kernel)
    GID:      <uint32>,  // real GID (captured in-kernel)
    Comm:     <string>,  // short task name (≤ 15 chars)
    Filename: <string>,  // execve filename argument
    Argv:     <string>,  // space-joined argv (present if non-empty)
}
```

---

## Linux Runtime: NETLINK_CONNECTOR

```
              kernel
┌─────────────────────────────────────────┐
│  Process calls execve(2) / execveat(2)  │
│              ↓                           │
│  Kernel CN connector emits              │
│  PROC_EVENT_EXEC on NETLINK group 1     │
└────────────────────┬────────────────────┘
                     │ AF_NETLINK / SOCK_DGRAM
              ┌──────▼──────┐
              │ readLoop()  │  1-second timeout, checks done channel
              └──────┬──────┘
                     │ parseNetlinkMessages()
                     │ handleNetlinkMessage()
                     │ reads /proc/<pid>/status, comm, cmdline
                     ↓
              ProcessEvent ──► dispatch() ──► AlertEvent channel
```

### Privilege requirement

Opening a `NETLINK_CONNECTOR` socket for process events requires `CAP_NET_ADMIN`
or root (uid 0). If the agent lacks these privileges, `Start` returns a
descriptive error.

---

## Non-Linux platforms

On macOS, the `darwinKqueueBackend` provides kqueue-based monitoring with ps
polling as a fallback. On Windows and other non-Linux/non-darwin systems,
`ProcessWatcher.Start` uses a ps(1) polling backend.

---

## Running the tests

```bash
# All process watcher tests (uses mock backend, no root required)
go test -v -run TestProcessWatcher ./internal/watcher/...

# All watcher tests
go test -v ./internal/watcher/...

# With race detector
go test -race ./internal/watcher/...

# Linux integration tests (requires root / CAP_NET_ADMIN)
sudo go test -v -run TestProcessWatcher ./internal/watcher/...
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

### Linux integration tests (`process_watcher_linux_test.go`)

| Test | Description |
|------|-------------|
| `TestProcessWatcher_ImplementsWatcherInterface` | Compile-time agent.Watcher check |
| `TestNewProcessWatcher_EventsChannelNonNil` | Events() non-nil before Start |
| `TestNewProcessWatcher_FiltersNonProcessRules` | Non-PROCESS rules filtered |
| `TestProcessWatcher_StartReturnsErrorWithoutPrivilege` | Error when lacking CAP_NET_ADMIN |
| `TestProcessWatcher_StartStop` | Start/Stop lifecycle (requires root) |
| `TestProcessWatcher_StartIdempotent` | Double Start is a no-op (requires root) |
| `TestProcessWatcher_StopIdempotent` | Double Stop safe (requires root) |
| `TestProcessWatcher_EventsChannelClosedAfterStop` | Channel closed after Stop (requires root) |
| `TestProcessWatcher_ContextCancellation` | Context cancel triggers shutdown (requires root) |
| `TestProcessWatcher_ExecveAlertEvent` | Real execve emits alert (requires root) |
| `TestProcessWatcher_PatternFilter` | Pattern matching on real processes (requires root) |
| `TestProcessWatcher_StructSizeConstants` | Netlink ABI struct sizes correct (requires root) |

---

## Related documents

- [File Watcher](file-watcher.md) — inotify / kqueue / polling implementations
- [Agent Core](agent-core.md) — Watcher interface and agent orchestrator
- [Alert Queue](alert-queue.md) — durable event storage
- [gRPC Alert Service](grpc-alert-service.md) — event transport to dashboard
