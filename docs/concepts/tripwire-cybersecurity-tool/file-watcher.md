# TripWire Agent — File Watcher

This document describes the `internal/watcher` package, which provides two
complementary filesystem monitoring implementations:

| Implementation | Mechanism | Platforms | File |
|---|---|---|---|
| `FileWatcher` | Polling (100 ms default) | All | `internal/watcher/file.go` |
| `InotifyWatcher` | Linux inotify API | Linux only | `internal/watcher/inotify_linux.go` |

Both implement the [`agent.Watcher`](agent-core.md#interfaces) interface and the
additional `Ready() <-chan struct{}` channel for test synchronisation.

---

## FileWatcher — Cross-Platform Polling

**File:** `internal/watcher/file.go`

### Overview

`FileWatcher` scans configured directory and file targets every **100 ms**
(default), detects creates, writes, and deletes by comparing filesystem
snapshots, and forwards `AlertEvent`s to the agent orchestrator.

Polling with a 100 ms interval guarantees detection within ≤ 200 ms worst
case — more than **25× margin** against the 5-second alert SLA stated in
[PRD Goal G-2 and User Story US-01](PRD.md). It requires no kernel-level
hooks, works uniformly across Linux, macOS, and Windows, and tolerates
watched paths that do not yet exist at agent startup.

### API

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

### Wiring into the agent

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

| Filesystem change | `Detail["operation"]` |
|-------------------|-----------------------|
| New file appears  | `"create"`            |
| File modified     | `"write"`             |
| File removed      | `"delete"`            |

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
    "operation": "write"
  }
}
```

---

## Configuration

Both watchers are driven by `FILE`-type rules in the agent configuration:

```yaml
rules:
  - name: etc-passwd-watch
    type: FILE
    target: /etc/passwd
    severity: CRITICAL

  - name: home-dir-watch
    type: FILE
    target: /home/operator
    severity: WARN
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

### InotifyWatcher (`inotify_linux_test.go`, Linux only)

| Test | Description |
|------|-------------|
| `TestInotifyWatcher_StartStop` | Lifecycle: Start and Stop complete cleanly |
| `TestInotifyWatcher_StopIsIdempotent` | Double-Stop does not panic |
| `TestInotifyWatcher_IgnoresNonFileRules` | Non-FILE rules filtered silently |
| `TestInotifyWatcher_ReadyChannelClosedAfterStart` | Ready() fires after watches registered |
| `TestInotifyWatcher_DetectsFileCreate` | CREATE event via IN_CREATE |
| `TestInotifyWatcher_DetectsFileWrite` | WRITE event via IN_CLOSE_WRITE |
| `TestInotifyWatcher_DetectsFileDelete` | DELETE event via IN_DELETE |
| `TestInotifyWatcher_WatchesSingleFile` | Single-file (not directory) target |
| `TestInotifyE2E_FileAlertEmission_WithinSLA` | **5-second SLA acceptance test** |
| `TestInotifyE2E_AgentStop` | Agent.Stop during active inotify watch |
