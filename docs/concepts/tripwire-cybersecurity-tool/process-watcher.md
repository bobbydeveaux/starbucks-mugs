# TripWire Agent — Process Watcher

This document describes the process monitoring components that implement
the [`agent.Watcher`](agent-core.md#interfaces) interface and trace `execve`/`execveat`
syscalls using kernel-level mechanisms.

---

## Overview

The Process Watcher emits an `AlertEvent` (with `TripwireType: "PROCESS"`) whenever
a configured process name pattern is matched against a newly exec'd process.
It is designed as a multi-layer system with platform-specific backends:

| Layer | File | Description |
|-------|------|-------------|
| eBPF kernel program | `internal/watcher/ebpf/process.bpf.c` | Attaches to execve/execveat tracepoints; writes events to a BPF ring buffer |
| Go userspace — Linux | `internal/watcher/process_watcher_linux.go` | Uses `NETLINK_CONNECTOR` for kernel-level PROC_EVENT_EXEC notifications |
| Go userspace — Darwin | `internal/watcher/process_watcher_darwin.go` | Uses kqueue `EVFILT_PROC`/`NOTE_EXEC` + process-list poll fallback |
| Go stub | `internal/watcher/process_watcher_other.go` | All other platforms: returns an error on Start |

---

## eBPF Kernel Program (`process.bpf.c`)

The canonical implementation is an eBPF program that attaches to the
`tracepoint/syscalls/sys_enter_execve` and `tracepoint/syscalls/sys_enter_execveat`
hooks. It captures the following fields into a BPF ring buffer:

| Field | Type | Description |
|-------|------|-------------|
| `pid` | `uint32` | Process ID (tgid) of the new process |
| `ppid` | `uint32` | Parent process ID |
| `uid` | `uint32` | Real UID of the calling process |
| `gid` | `uint32` | Real GID of the calling process |
| `comm` | `[16]byte` | Short task name (≤ 15 chars, NUL-terminated) |
| `filename` | `[256]byte` | Path argument to execve/execveat |
| `argv` | `[256]byte` | Space-joined argv[0..N], NUL-terminated |

### Shared header

The event struct is defined in `internal/watcher/ebpf/process.h` and is
included by both the BPF C program and (as a Go mirror) the userspace loader.

### Building the BPF object

```bash
# Install prerequisites (Debian/Ubuntu):
apt-get install -y clang llvm libbpf-dev linux-headers-$(uname -r)

# Generate vmlinux.h from the running kernel's BTF info (needed for CO-RE):
bpftool btf dump file /sys/kernel/btf/vmlinux format c \
    > internal/watcher/ebpf/vmlinux.h

# Compile:
make -C internal/watcher/ebpf
```

The resulting `process.bpf.o` is embedded into the Go binary via `//go:embed`
in `internal/watcher/ebpf/process.go` so that no runtime compilation is required.

### Kernel requirements

- Linux ≥ 5.8 — BPF ring buffer (`BPF_MAP_TYPE_RINGBUF`)
- `CONFIG_BPF_SYSCALL=y`, `CONFIG_DEBUG_INFO_BTF=y` (for CO-RE)
- `CAP_BPF` (Linux ≥ 5.8) or `CAP_SYS_ADMIN`

---

## Linux Runtime: `ProcessWatcher`

On Linux the `ProcessWatcher` uses the **NETLINK_CONNECTOR** process connector
to receive `PROC_EVENT_EXEC` notifications from the kernel. This mechanism is
available on all Linux kernels without requiring a BPF compiler, and provides
semantics equivalent to the eBPF program for the alert detection use case.

### Privilege requirement

Opening a `NETLINK_CONNECTOR` socket for process events requires `CAP_NET_ADMIN`
or root (uid 0). If the agent lacks these privileges, `Start` returns a descriptive
error.

### How it works

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
              │ readLoop()  │  1-second timeout, checks ctx.Done()
              └──────┬──────┘
                     │ parseNetlinkMessages()
                     │ handleNetlinkMessage()
                     │ reads /proc/<pid>/comm, exe, cmdline
                     ↓
              matchingRule() ──► emit AlertEvent to channel
```

### ProcessRule matching

Rules are sourced from `config.TripwireRule` entries with `Type: "PROCESS"`.
The `Target` field is treated as a glob pattern matched against:

1. The base name of the executable path (e.g. `sh` matches `/bin/sh`)
2. The full executable path (e.g. `*/python*` matches `/usr/bin/python3`)

An **empty `Target`** matches every execve event (catch-all rule).

### AlertEvent fields

```go
AlertEvent{
    TripwireType: "PROCESS",
    RuleName:     "<rule name from config>",
    Severity:     "<INFO | WARN | CRITICAL>",
    Timestamp:    time.Now().UTC(),
    Detail: map[string]any{
        "pid":     <int>,    // process ID
        "comm":    <string>, // short task name
        "exe":     <string>, // full exe path from /proc/<pid>/exe
        "cmdline": <string>, // space-joined argv from /proc/<pid>/cmdline
    },
}
```

---

## Configuration example

```yaml
rules:
  - name: shell-execution
    type: PROCESS
    target: "sh"        # matches /bin/sh, /usr/bin/sh, etc.
    severity: WARN

  - name: python-script
    type: PROCESS
    target: "python*"   # matches python, python3, python3.11, …
    severity: INFO

  - name: any-process
    type: PROCESS
    target: ""          # empty = catch all execve events
    severity: INFO
```

---

## macOS / Darwin: kqueue fallback

On Darwin, `ProcessWatcher` uses the **kqueue** `EVFILT_PROC` filter with
`NOTE_EXEC` to detect execve events without requiring a BPF compiler or
`NETLINK_CONNECTOR`. Two complementary mechanisms work together:

### How it works

```
                macOS kernel
┌────────────────────────────────────────────┐
│  Process calls execve(2)                    │
│              ↓                              │
│  kqueue delivers EVFILT_PROC + NOTE_EXEC    │
│  to any kq that watches the PID            │
└─────────────────────┬──────────────────────┘
                      │  kqueue fd
        ┌─────────────▼──────────────────┐
        │  runProcKqueueLoop()            │  100 ms timeout, checks ctx.Done()
        │    handleProcKevent()           │
        │      darwinProcInfo(pid)        │  sysctl kern.procargs2.<pid>
        └─────────────┬──────────────────┘
                      │
               matchingRule() ──► emit AlertEvent to channel

        ┌─────────────────────────────────┐
        │  runProcPollLoop()              │  every 500 ms
        │    listRunningPIDs()            │  ps -axo pid=
        │    state.addPID(pid)            │  add new PIDs to kqueue
        └─────────────────────────────────┘
```

### Privilege requirement

- `kqueue()` itself requires no privilege.
- `EVFILT_PROC` registration succeeds for processes owned by the **same user**
  as the watcher. Root can watch all processes. Non-root watchers silently skip
  processes owned by other users.
- `KERN_PROCARGS2` sysctl (process details after NOTE_EXEC) requires the same
  effective UID as the target process, or root. If unavailable the event is
  still emitted with only the PID recorded.

### NOTE_TRACK: transitive fork tracking

When `NOTE_TRACK` is set on a watched PID, the kernel automatically registers
the same `EVFILT_PROC` filters on any child process spawned via `fork(2)`. This
means exec events for all descendants of a tracked process are delivered without
explicit re-registration.

If `NOTE_TRACK` fails for a child (`NOTE_TRACKERR`), the poll loop re-discovers
the missed PID within the next poll interval (default 500 ms).

### Known limitations (vs Linux NETLINK)

| Constraint | Details |
|------------|---------|
| PID-scoped | kqueue watches specific PIDs; system-wide coverage relies on NOTE_TRACK propagation starting from processes already running when the watcher started |
| Poll gap | New processes spawned between poll ticks by non-descendant parents may be detected up to 500 ms late |
| Race on exit | KERN_PROCARGS2 may fail if the target process exits before the watcher reads it; the event is still emitted with only the PID |
| Non-root scope | Without root, only same-UID processes are monitored |

### AlertEvent fields (Darwin)

```go
AlertEvent{
    TripwireType: "PROCESS",
    RuleName:     "<rule name from config>",
    Severity:     "<INFO | WARN | CRITICAL>",
    Timestamp:    time.Now().UTC(),
    Detail: map[string]any{
        "pid":     <int>,    // process ID
        "comm":    <string>, // base name of executable (empty if process exited first)
        "exe":     <string>, // full exe path from kern.procargs2 sysctl
        "cmdline": <string>, // space-joined argv from kern.procargs2 sysctl
    },
}
```

---

## Other platforms (Windows, FreeBSD, …)

On platforms other than Linux and macOS, `ProcessWatcher.Start` returns:

```
process watcher: execve tracing is only supported on Linux
(NETLINK_CONNECTOR) and macOS (kqueue/EVFILT_PROC); current platform: <goos>
```

To add support for another OS, create
`internal/watcher/process_watcher_<goos>.go` with platform-specific `Start`
and `Stop` implementations and update the build tag in
`process_watcher_other.go` to exclude the new platform.

---

## Related documents

- [File Watcher](file-watcher.md) — inotify / kqueue / polling implementations
- [Agent Core](agent-core.md) — Watcher interface and agent orchestrator
- [Alert Queue](alert-queue.md) — durable event storage
