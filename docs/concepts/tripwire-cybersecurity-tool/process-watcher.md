# TripWire Agent — Process Watcher

This document describes the process monitoring components that implement
the [`agent.Watcher`](agent-core.md#interfaces) interface and trace `execve`/`execveat`
syscalls using kernel-level mechanisms.

---

## Overview

The Process Watcher emits an `AlertEvent` (with `TripwireType: "PROCESS"`) whenever
a configured process name pattern is matched against a newly exec'd process.
It is designed as a three-layer system:

| Layer | File | Description |
|-------|------|-------------|
| eBPF kernel program | `internal/watcher/ebpf/process.bpf.c` | Attaches to execve/execveat tracepoints; writes events to a BPF ring buffer |
| eBPF Go userspace loader | `internal/watcher/ebpf/process.go` | Loads the compiled BPF object, reads ring-buffer events, converts to `ExecEvent` |
| Go userspace (runtime) | `internal/watcher/process_watcher_linux.go` | Linux runtime; uses `NETLINK_CONNECTOR` for kernel-level execve notifications |
| Go stub | `internal/watcher/process_watcher_other.go` | Non-Linux: returns error on Start |

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

> **Note**: A minimal placeholder `process.bpf.o` is committed to the repository
> so that `go build` succeeds without a BPF compiler toolchain. Running
> `make -C internal/watcher/ebpf` replaces it with the real object. The placeholder
> causes `Loader.Load()` to return an error on load, which callers treat as a
> signal to fall back to the NETLINK_CONNECTOR implementation.

### Kernel requirements

- Linux ≥ 5.8 — BPF ring buffer (`BPF_MAP_TYPE_RINGBUF`)
- `CONFIG_BPF_SYSCALL=y`, `CONFIG_DEBUG_INFO_BTF=y` (for CO-RE)
- `CAP_BPF` (Linux ≥ 5.8) or `CAP_SYS_ADMIN`

---

## eBPF Go Userspace Loader (`internal/watcher/ebpf`)

The `ebpf` package implements the `Loader` type that bridges the BPF kernel
program and the Go event pipeline:

```
                kernel
┌────────────────────────────────────────┐
│  Process calls execve(2)/execveat(2)   │
│              ↓                          │
│  BPF tracepoint fires                  │
│  → ring buffer record written          │
└──────────────┬─────────────────────────┘
               │ BPF_MAP_TYPE_RINGBUF
      ┌────────▼────────┐
      │ Loader.readLoop │  1-second deadline, checks ctx.Done()
      └────────┬────────┘
               │ parseExecEvent()
               │ deserialises execEvent struct (544 B)
               ↓
           ExecEvent ──► events chan ExecEvent
```

### Loader lifecycle

```go
// 1. Check kernel version (≥ 5.8) and create loader.
loader, err := ebpf.NewLoader(logger)
if errors.Is(err, ebpf.ErrNotSupported) {
    // Fall back to NETLINK_CONNECTOR implementation.
}

// 2. Load BPF object and attach to tracepoints.
if err := loader.Load(ctx); err != nil {
    loader.Close()
    // Handle: invalid BPF object or insufficient privileges.
}

// 3. Consume events.
for evt := range loader.Events() {
    fmt.Printf("pid=%d comm=%s filename=%s\n", evt.PID, evt.Comm, evt.Filename)
}

// 4. Clean up.
loader.Close()
```

### ExecEvent fields

| Field | Type | Description |
|-------|------|-------------|
| `PID` | `uint32` | tgid of the process that called execve |
| `PPID` | `uint32` | Parent tgid |
| `UID` | `uint32` | Real UID of the calling process |
| `GID` | `uint32` | Real GID of the calling process |
| `Comm` | `string` | Short task name (≤ 15 chars) |
| `Filename` | `string` | Path argument to execve/execveat |
| `Argv` | `string` | Space-joined argv[0..N], truncated at 255 chars |

### Graceful shutdown

`Close()` is idempotent and safe to call concurrently:
1. Closes the ring-buffer reader, unblocking the event-pump goroutine.
2. Waits for the goroutine to exit (no goroutine leak).
3. Detaches tracepoint links and frees all BPF objects.
4. Closes the `Events()` channel so `range` loops terminate cleanly.

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

## Non-Linux platforms

On macOS, Windows, and other non-Linux systems `ProcessWatcher.Start` returns:

```
process watcher: PROC_EVENT_EXEC / eBPF execve tracing is only
supported on Linux (current platform: darwin)
```

To add support for another OS, create
`internal/watcher/process_watcher_<goos>.go` with platform-specific `Start`
and `Stop` implementations.

---

## Related documents

- [File Watcher](file-watcher.md) — inotify / kqueue / polling implementations
- [Agent Core](agent-core.md) — Watcher interface and agent orchestrator
- [Alert Queue](alert-queue.md) — durable event storage
