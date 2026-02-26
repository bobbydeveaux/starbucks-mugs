# TripWire Agent — Process Watcher

This document describes the process monitoring components that implement
the [`agent.Watcher`](agent-core.md#interfaces) interface and trace `execve`/`execveat`
syscalls using kernel-level mechanisms.

---

## Overview

The Process Watcher emits an `AlertEvent` (with `TripwireType: "PROCESS"`) whenever
a configured process name pattern is matched against a newly exec'd process.
It is designed as a two-layer system with two alternative Go userspace implementations:

| Layer | File | Description |
|-------|------|-------------|
| eBPF kernel program | `internal/watcher/ebpf/process.bpf.c` | Attaches to execve/execveat tracepoints; writes events to a BPF ring buffer |
| Go eBPF loader | `internal/watcher/ebpf/process.go` | Loads the eBPF object, reads the ring buffer, converts raw kernel events to AlertEvents |
| Go NETLINK runtime | `internal/watcher/process_watcher_linux.go` | Linux runtime; uses `NETLINK_CONNECTOR` for kernel-level execve notifications (no BPF toolchain needed) |
| Go stub | `internal/watcher/process_watcher_other.go` | Non-Linux: returns error on Start |

### Choosing a runtime

| | eBPF loader (`ebpf.ProcessWatcher`) | NETLINK_CONNECTOR (`watcher.ProcessWatcher`) |
|---|---|---|
| **Kernel req.** | Linux ≥ 5.8, `CAP_BPF` | Any Linux, `CAP_NET_ADMIN` |
| **argv capture** | In-kernel (race-free) | /proc read (TOCTOU risk) |
| **PPID / UID / GID** | Always available | Not available |
| **BPF toolchain** | Required to compile .bpf.o | Not required |
| **Deployment** | Build with `-tags bpf_embedded` | Standard build |

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

The resulting `process.bpf.o` is embedded into the Go binary when built with
`-tags bpf_embedded` (see [Go eBPF Loader](#go-ebpf-loader) below) so that no
runtime compilation is required.

### Kernel requirements

- Linux ≥ 5.8 — BPF ring buffer (`BPF_MAP_TYPE_RINGBUF`)
- `CONFIG_BPF_SYSCALL=y`, `CONFIG_DEBUG_INFO_BTF=y` (for CO-RE)
- `CAP_BPF` (Linux ≥ 5.8) or `CAP_SYS_ADMIN`

---

## Go eBPF Loader (`ebpf.ProcessWatcher`)

Package `internal/watcher/ebpf` provides a Go userspace component that loads
the pre-compiled `process.bpf.o`, attaches the tracepoints, reads events from
the BPF ring buffer, and delivers them as `AlertEvent` values.

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
                    │ readLoop()           │  readSample() spins on
                    │                      │  consumer_pos / producer_pos
                    └──────────┬──────────┘
                               │ binary.Read() → execEvent{}
                               │ handleEvent() → matchingRule()
                               ↓
                         emit AlertEvent
```

### Loading sequence (in `Start`)

1. **Parse ELF** — `parseBPFELF` extracts map definitions, program
   instructions, relocation entries, and the license string from `process.bpf.o`.
2. **Create maps** — `BPF_MAP_CREATE` (`BPF_MAP_TYPE_RINGBUF`, 16 MiB).
3. **Patch relocations** — `applyMapRelocations` patches `LD_IMM64` instructions
   that reference the ring buffer map with the real kernel fd.
4. **Load programs** — `BPF_PROG_LOAD` for `trace_execve` and `trace_execveat`.
5. **Attach tracepoints** — `perf_event_open(PERF_TYPE_TRACEPOINT, id, cpu=-1)` ×
   `PERF_EVENT_IOC_SET_BPF` × `PERF_EVENT_IOC_ENABLE` for each CPU.
6. **Open ring buffer** — `mmap` the ring buffer map fd; start the read loop.

### Build variants

| Tag | Effect |
|-----|--------|
| *(none)* | Standard build; BPF object not embedded. `Start()` returns a clear error unless `SetBPFObject()` is called first. |
| `bpf_embedded` | Embeds the compiled `process.bpf.o` at link time via `//go:embed`. |

```bash
# Standard build (compiles and tests without BPF object):
go build ./internal/watcher/ebpf/...
go test ./internal/watcher/ebpf/...

# Embedded build (requires process.bpf.o to exist):
make -C internal/watcher/ebpf
go build -tags bpf_embedded ./internal/watcher/ebpf/...
```

### Usage

```go
import "github.com/tripwire/agent/internal/watcher/ebpf"

rules := []config.TripwireRule{
    {Name: "shell-exec", Type: "PROCESS", Target: "sh", Severity: "WARN"},
}
w := ebpf.NewProcessWatcher(rules, logger)

// Optional: inject BPF object bytes at runtime (e.g. in tests).
// w.SetBPFObject(myBPFObjectBytes)

if err := w.Start(ctx); err != nil {
    log.Fatal(err)
}
defer w.Stop()

for evt := range w.Events() {
    fmt.Printf("Alert: %s pid=%v\n", evt.RuleName, evt.Detail["pid"])
}
```

### AlertEvent fields (eBPF variant)

The eBPF loader captures richer metadata than the NETLINK_CONNECTOR variant
because all fields are read atomically in the kernel at exec time:

```go
AlertEvent{
    TripwireType: "PROCESS",
    RuleName:     "<rule name from config>",
    Severity:     "<INFO | WARN | CRITICAL>",
    Timestamp:    time.Now().UTC(),
    Detail: map[string]any{
        "pid":     <int>,    // process ID (tgid)
        "ppid":   <int>,    // parent process ID (captured in-kernel)
        "uid":    <int>,    // real UID (captured in-kernel)
        "gid":    <int>,    // real GID (captured in-kernel)
        "comm":   <string>, // short task name (≤ 15 chars)
        "exe":    <string>, // execve filename argument
        "cmdline": <string>, // space-joined argv (present if non-empty)
    },
}
```

### Rule matching

Identical to the NETLINK_CONNECTOR variant: the `Target` glob is matched
against the executable basename first, then the full path. An empty `Target`
matches every execve event.

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
