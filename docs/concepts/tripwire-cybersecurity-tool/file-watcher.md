# TripWire Agent — File Watcher

This document describes the `internal/watcher` package, which provides three
filesystem monitoring implementations that satisfy the
[`agent.Watcher`](agent-core.md#interfaces) interface:

| Implementation | File | Platform | Mechanism |
|----------------|------|----------|-----------|
| `FileWatcher` | `file.go` | All | Polling (100 ms) |
| `InotifyWatcher` | `file_watcher_linux.go` | Linux | inotify syscall |
| `KqueueWatcher` | `file_watcher_darwin.go` | macOS | kqueue/EVFILT_VNODE |

---

## FileWatcher — Cross-Platform Polling

### FileWatcher (cross-platform polling)

The `FileWatcher` is a polling-based filesystem monitor. It scans configured
directory and file targets every **100 ms** (default), detects creates,
writes, and deletes, and forwards `AlertEvent`s to the agent orchestrator.

**Why polling?** Polling with a 100 ms interval guarantees detection within
≤ 200 ms worst case — more than **25× margin** against the 5-second alert
SLA stated in [PRD Goal G-2 and User Story US-01](PRD.md). It requires no
kernel-level hooks, works uniformly across Linux, macOS, and Windows, and
tolerates watched paths that do not yet exist at agent startup.

### InotifyWatcher (Linux kernel notifications)

The `InotifyWatcher` uses the Linux `inotify` subsystem to receive immediate
kernel notifications when watched paths change. Unlike polling, events arrive
as soon as the kernel processes the filesystem operation — typically within
microseconds.

**Advantages over polling:**
- Sub-millisecond detection latency for most operations
- No CPU overhead between events (kernel-driven wakeup)
- Detects file reads (`IN_ACCESS`) which polling cannot observe

**Limitation:** `inotify` does not expose the PID or UID of the triggering
process. The `Detail["pid"]` and `Detail["username"]` fields are set to
sentinel values (`-1` and `"unknown"` respectively).

### KqueueWatcher (macOS kernel notifications)

The `KqueueWatcher` uses the macOS `kqueue` event notification interface with
`EVFILT_VNODE` filters to receive kernel notifications for file and directory
changes.

- **File targets:** Receives immediate events for `NOTE_WRITE`, `NOTE_EXTEND`,
  `NOTE_ATTRIB`, `NOTE_DELETE`, and `NOTE_RENAME`.
- **Directory targets:** Receives `NOTE_WRITE` when directory contents change,
  then diffs against a saved snapshot to determine which files were created,
  modified, or deleted.

**Limitation:** `kqueue` does not expose the PID or UID of the triggering
process. The `Detail["pid"]` and `Detail["username"]` fields are set to
sentinel values (`-1` and `"unknown"` respectively).

---

## Package: `internal/watcher`

### FileWatcher

**File:** `internal/watcher/file.go` (all platforms)

```go
type FileWatcher struct { /* unexported */ }

func NewFileWatcher(rules []config.TripwireRule, logger *slog.Logger, interval time.Duration) *FileWatcher
func (fw *FileWatcher) Start(ctx context.Context) error
func (fw *FileWatcher) Stop()
func (fw *FileWatcher) Events() <-chan agent.AlertEvent
func (fw *FileWatcher) Ready() <-chan struct{}
```

#### `NewFileWatcher`

| Parameter  | Description |
|------------|-------------|
| `rules`    | Slice of `TripwireRule`; only `Type == "FILE"` entries are used |
| `logger`   | Structured logger for diagnostic messages |
| `interval` | Poll frequency; `0` or negative uses `DefaultPollInterval` (100 ms) |

### InotifyWatcher

**File:** `internal/watcher/file_watcher_linux.go` (`//go:build linux`)

```go
type InotifyWatcher struct { /* unexported */ }

func NewInotifyWatcher(rules []config.TripwireRule, logger *slog.Logger) (*InotifyWatcher, error)
func (iw *InotifyWatcher) Start(ctx context.Context) error
func (iw *InotifyWatcher) Stop()
func (iw *InotifyWatcher) Events() <-chan agent.AlertEvent
func (iw *InotifyWatcher) Ready() <-chan struct{}
```

`NewInotifyWatcher` returns an error if `inotify_init1(2)` fails (e.g.
insufficient file-descriptor quota). Non-FILE rules are silently ignored.

**inotify event mask subscribed:**

| inotify event | Meaning |
|---------------|---------|
| `IN_ACCESS` | File was read |
| `IN_MODIFY` | File content changed |
| `IN_CLOSE_WRITE` | Writable file was closed |
| `IN_CREATE` | File created in watched directory |
| `IN_MOVED_TO` | File moved into watched directory |
| `IN_DELETE` | File deleted from watched directory |
| `IN_MOVED_FROM` | File moved out of watched directory |

### KqueueWatcher

**File:** `internal/watcher/file_watcher_darwin.go` (`//go:build darwin`)

```go
type KqueueWatcher struct { /* unexported */ }

func NewKqueueWatcher(rules []config.TripwireRule, logger *slog.Logger) (*KqueueWatcher, error)
func (kw *KqueueWatcher) Start(ctx context.Context) error
func (kw *KqueueWatcher) Stop()
func (kw *KqueueWatcher) Events() <-chan agent.AlertEvent
func (kw *KqueueWatcher) Ready() <-chan struct{}
```

`NewKqueueWatcher` returns an error if `kqueue(2)` fails. Non-FILE rules are
silently ignored.

**kqueue EVFILT_VNODE flags subscribed (file targets):**

| Note flag | Meaning |
|-----------|---------|
| `NOTE_WRITE` | File data was modified |
| `NOTE_EXTEND` | File size was increased |
| `NOTE_ATTRIB` | File metadata changed |
| `NOTE_DELETE` | File was deleted |
| `NOTE_RENAME` | File was renamed/moved |

**kqueue EVFILT_VNODE flags subscribed (directory targets):**

| Note flag | Meaning |
|-----------|---------|
| `NOTE_WRITE` | Directory contents changed (triggers snapshot diff) |
| `NOTE_DELETE` | Directory was removed |
| `NOTE_RENAME` | Directory was renamed |

---

## InotifyWatcher — Linux Platform-Specific Watcher

**File:** `internal/watcher/inotify_linux.go` (Linux only, build tag `linux`)

**Stub:** `internal/watcher/inotify_stub.go` (non-Linux, always errors)

### Overview

`InotifyWatcher` uses the Linux [inotify(7)](https://man7.org/linux/man-pages/man7/inotify.7.html)
kernel API to receive **instant, event-driven** filesystem notifications
without polling. It satisfies the same `agent.Watcher` interface as
`FileWatcher` and provides an additional `Ready() <-chan struct{}` channel that
is closed once all initial watches have been registered.

Compared with `FileWatcher`:

| Property | FileWatcher | InotifyWatcher |
|---|---|---|
| Detection latency | ≤ 200 ms (100 ms poll) | < 1 ms (kernel push) |
| CPU at idle | Periodic wakeup | Zero until event |
| Platform | Any | Linux ≥ 2.6.36 only |
| Paths created after start | Detected on next scan | Not watched (limitation) |

### How it works

1. `InotifyInit1(IN_CLOEXEC)` — creates an inotify file descriptor.
2. For each configured `FILE` rule, `InotifyAddWatch` registers the target
   path with the appropriate event mask.
3. A background goroutine uses `poll(2)` to multiplex two file descriptors:
   - **inotifyFd** — becomes readable when the kernel has queued events.
   - **pipeR** — a self-pipe; `Stop()` writes one byte to unblock `poll`.
4. On each readable event: `Read(inotifyFd, buf)` drains the kernel buffer and
   `parseAndDispatch` converts raw `inotify_event` structs to `AlertEvent`s.

### Event masks

| Target type | Watched events |
|---|---|
| Directory | `IN_CREATE`, `IN_CLOSE_WRITE`, `IN_DELETE`, `IN_MOVED_FROM`, `IN_MOVED_TO` |
| Single file | `IN_CLOSE_WRITE`, `IN_DELETE`, `IN_MOVE_SELF` |

`IN_CLOSE_WRITE` (not `IN_MODIFY`) is used for write detection to fire once
per logical write operation (when the file is closed), preventing spurious
duplicate events from partial writes.

### API

```go
type InotifyWatcher struct { /* unexported */ }

func NewInotifyWatcher(rules []config.TripwireRule, logger *slog.Logger) (*InotifyWatcher, error)
func (w *InotifyWatcher) Start(ctx context.Context) error
func (w *InotifyWatcher) Stop()
func (w *InotifyWatcher) Events() <-chan agent.AlertEvent
func (w *InotifyWatcher) Ready() <-chan struct{}
```

#### `NewInotifyWatcher`

| Parameter | Description |
|---|---|
| `rules`   | Slice of `TripwireRule`; only `Type == "FILE"` entries are used |
| `logger`  | Structured logger for diagnostic messages |

Returns an error if the inotify kernel interface is unavailable (Linux < 2.6.36,
or non-Linux where the stub is compiled instead).

### Limitation: paths created after Start

`InotifyWatcher` can only watch paths that **exist when `Start` is called**.
If a watched path is created later (e.g. a directory that didn't exist at
agent startup), it will not be automatically detected. Use `FileWatcher` in
scenarios where target paths may not yet exist at agent startup.

### Wiring into the agent (Linux preferred path)

```go
// On Linux, prefer InotifyWatcher for near-zero-latency detection.
// Fall back to FileWatcher if inotify is unavailable.
var fw agent.Watcher
iw, err := watcher.NewInotifyWatcher(cfg.Rules, logger)
if err != nil {
    logger.Warn("inotify unavailable; falling back to polling", slog.Any("error", err))
    fw = watcher.NewFileWatcher(cfg.Rules, logger, 0)
} else {
    fw = iw
}

ag := agent.New(cfg, logger,
    agent.WithWatchers(fw),
    agent.WithQueue(q),
    agent.WithTransport(tr),
)

if err := ag.Start(ctx); err != nil {
    log.Fatal(err)
}
```

---

## Event types (both implementations)

| Filesystem change | `Detail["operation"]` | Emitted by |
|-------------------|-----------------------|-----------|
| New file appears  | `"create"`            | All implementations |
| File content or metadata changes | `"write"` | All implementations |
| File removed      | `"delete"`            | All implementations |
| File was read     | `"access"`            | `InotifyWatcher` only |

Sub-directory entries are **not** watched recursively in either implementation.
Only immediate children of a directory target are tracked.

---

## AlertEvent payload

```json
{
  "tripwire_type": "FILE",
  "rule_name":     "etc-passwd-watch",
  "severity":      "CRITICAL",
  "timestamp":     "2026-02-25T19:30:00Z",
  "detail": {
    "path":      "/etc/passwd",
    "operation": "write",
    "pid":       -1,
    "username":  "unknown"
  }
}
```

> **Note:** `pid` and `username` are always `-1` and `"unknown"` for
> `InotifyWatcher` and `KqueueWatcher` since neither `inotify` nor `kqueue`
> exposes the identity of the process that triggered the change. `FileWatcher`
> also sets these sentinel values. Future implementations using `fanotify`
> (Linux 5.1+) or `OpenBSM` (macOS) could populate these fields.

---

## Wiring into the agent

### Cross-platform (polling)

```go
fw := watcher.NewFileWatcher(cfg.Rules, logger, 0) // 0 → 100 ms default

ag := agent.New(cfg, logger,
    agent.WithWatchers(fw),
    agent.WithQueue(q),
    agent.WithTransport(tr),
)

if err := ag.Start(ctx); err != nil {
    log.Fatal(err)
}
```

### Linux (inotify)

```go
iw, err := watcher.NewInotifyWatcher(cfg.Rules, logger)
if err != nil {
    log.Fatal(err)
}

ag := agent.New(cfg, logger,
    agent.WithWatchers(iw),
    agent.WithQueue(q),
    agent.WithTransport(tr),
)
```

### macOS (kqueue)

```go
kw, err := watcher.NewKqueueWatcher(cfg.Rules, logger)
if err != nil {
    log.Fatal(err)
}

ag := agent.New(cfg, logger,
    agent.WithWatchers(kw),
    agent.WithQueue(q),
    agent.WithTransport(tr),
)
```

---

## 5-second SLA validation

The end-to-end alert emission SLA is validated by integration tests. Key tests:

**`TestE2E_FileAlertEmission_WithinSLA`** (`file_test.go`) — wires a real
`FileWatcher` into the `Agent` orchestrator with a fake transport, triggers
a file creation, and asserts the `AlertEvent` arrives at the transport within
5 seconds.

**`TestInotifyWatcher_AlertWithinSLA`** (`file_watcher_linux_test.go`) — same
SLA test for `InotifyWatcher` on Linux.

**`TestKqueueWatcher_AlertWithinSLA`** (`file_watcher_darwin_test.go`) — same
SLA test for `KqueueWatcher` on macOS.

```
# Run all file watcher tests
go test -v ./internal/watcher/...

# Run only SLA tests
go test -v -run TestE2E ./internal/watcher/...
go test -v -run TestInotifyWatcher_AlertWithinSLA ./internal/watcher/...
```

Typical observed latency:
- `FileWatcher`: **< 200 ms** (50 ms poll interval in tests)
- `InotifyWatcher`: **< 5 ms** (kernel notification)
- `KqueueWatcher`: **< 5 ms** (kernel notification)

---

## Configuration

All three watcher implementations are driven by `FILE`-type rules in the
agent configuration:

```yaml
rules:
  - name: etc-passwd-watch
    type: FILE
    target: /etc/passwd
    severity: CRITICAL

  - name: ssh-config-watch
    type: FILE
    target: /etc/ssh/sshd_config
    severity: WARN

  - name: home-dir-watch
    type: FILE
    target: /home/operator
    severity: WARN

  - name: var-log-auth
    type: FILE
    target: /var/log/auth.log
    severity: INFO
```

See [`agent-configuration.md`](agent-configuration.md) for the full
configuration reference.

---

## Running the tests

```bash
# All file watcher tests (polling + inotify on Linux)
go test -v ./internal/watcher/...

# Only inotify tests (Linux only)
go test -v -run TestInotify ./internal/watcher/...

# SLA acceptance tests (both backends)
go test -v -run TestE2E ./internal/watcher/...
```

---

## Test coverage

### FileWatcher (`file_test.go`)

| Test | Description |
|------|-------------|
| `TestFileWatcher_StartStop` | Lifecycle: Start and Stop complete cleanly |
| `TestFileWatcher_StopIsIdempotent` | Double-Stop does not panic |
| `TestFileWatcher_IgnoresNonFileRules` | Non-FILE rules filtered silently |
| `TestFileWatcher_DetectsFileCreate` | CREATE event emitted for new files |
| `TestFileWatcher_DetectsFileWrite` | WRITE event emitted for modified files |
| `TestFileWatcher_DetectsFileDelete` | DELETE event emitted for removed files |
| `TestFileWatcher_WatchesSingleFile` | Single-file (not directory) target |
| `TestFileWatcher_ReadyChannelClosedAfterStart` | Ready() fires after Start |
| `TestE2E_FileAlertEmission_WithinSLA` | **5-second SLA acceptance test** |
| `TestE2E_FileAlertEmission_MultipleEvents` | Multiple events all within SLA |
| `TestE2E_FileAlertEmission_AgentStop` | Agent.Stop during active watch |

### InotifyWatcher (`file_watcher_linux_test.go`, Linux only)

| Test | Description |
|------|-------------|
| `TestInotifyWatcher_StartStop` | Lifecycle: Start and Stop complete cleanly |
| `TestInotifyWatcher_StopIsIdempotent` | Double-Stop does not panic |
| `TestInotifyWatcher_IgnoresNonFileRules` | Non-FILE rules filtered silently |
| `TestInotifyWatcher_ReadyChannelClosedAfterStart` | Ready() fires after Start |
| `TestInotifyWatcher_DetectsFileCreate` | CREATE event with pid/username sentinels |
| `TestInotifyWatcher_DetectsFileWrite` | WRITE event for modified files |
| `TestInotifyWatcher_DetectsFileDelete` | DELETE event for removed files |
| `TestInotifyWatcher_DetectsFileAccess` | ACCESS event for read operations |
| `TestInotifyWatcher_WatchesSingleFile` | Single-file (not directory) target |
| `TestInotifyWatcher_AlertWithinSLA` | **5-second SLA acceptance test** |

### KqueueWatcher (`file_watcher_darwin_test.go`, macOS only)

| Test | Description |
|------|-------------|
| `TestKqueueWatcher_StartStop` | Lifecycle: Start and Stop complete cleanly |
| `TestKqueueWatcher_StopIsIdempotent` | Double-Stop does not panic |
| `TestKqueueWatcher_IgnoresNonFileRules` | Non-FILE rules filtered silently |
| `TestKqueueWatcher_ReadyChannelClosedAfterStart` | Ready() fires after Start |
| `TestKqueueWatcher_DetectsFileCreate` | CREATE event for new files |
| `TestKqueueWatcher_DetectsFileWrite` | WRITE event for modified files |
| `TestKqueueWatcher_DetectsFileDelete` | DELETE event for removed files |
| `TestKqueueWatcher_WatchesSingleFile` | Single-file (not directory) target |
| `TestKqueueWatcher_AlertWithinSLA` | **5-second SLA acceptance test** |
