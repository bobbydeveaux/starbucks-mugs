# TripWire Agent — File Watcher

This document describes the `internal/watcher` package that provides
cross-platform file system monitoring for the TripWire agent.

---

## Overview

The `internal/watcher` package exposes a single public type — `FileWatcher` —
that implements the `agent.Watcher` interface. When registered with the agent
orchestrator it watches one or more file system paths configured via
`TripwireRule.Target` and converts kernel file system events into
`agent.AlertEvent` objects that flow through the central alert pipeline
(local queue → gRPC transport → dashboard).

---

## Package: `internal/watcher`

### FileEvent

```go
type EventType uint32

const (
    EventRead   EventType = iota + 1 // file was accessed (read)
    EventWrite                        // file was written / modified
    EventCreate                       // new file created
    EventDelete                       // file removed
)

type FileEvent struct {
    FilePath  string    // absolute path of the affected file
    PID       int       // process ID; 0 when the kernel cannot provide it
    UID       int       // user ID; 0 when unknown
    Username  string    // human-readable username; empty when unknown
    EventType EventType
    Timestamp time.Time
}
```

`FileEvent` is an internal type used by platform-specific backends. It is
converted into an `agent.AlertEvent` by `FileWatcher.emitAlert` before being
sent to the agent pipeline.

---

### FileWatcher

```go
func NewFileWatcher(rule config.TripwireRule, logger *slog.Logger) *FileWatcher

func (fw *FileWatcher) Start(ctx context.Context) error
func (fw *FileWatcher) Stop()
func (fw *FileWatcher) Events() <-chan agent.AlertEvent
```

`FileWatcher` implements `agent.Watcher`. It:

1. Expands the `TripwireRule.Target` glob to a list of paths on `Start`.
2. If the glob matches nothing, watches the parent directory so file creation
   can be detected.
3. Forwards kernel file events as `agent.AlertEvent` values through the
   `Events()` channel (buffered at 64).
4. Restarts the underlying platform watcher automatically if it returns an
   error, using exponential backoff (1 s → 2 s → … → 30 s maximum).
5. Logs a warning when the event buffer is full and an event must be dropped.

`Stop` is safe to call multiple times and before `Start`.

---

## Platform implementations

### Linux (`file_watcher_linux.go`)

Uses the Linux `inotify(7)` subsystem via the `syscall` package in non-blocking
mode (`IN_NONBLOCK | IN_CLOEXEC`). A polling loop reads events every 50 ms
and checks for context cancellation between reads to ensure responsive shutdown.

**Watched events:**

| inotify constant    | EventType     |
|---------------------|---------------|
| `IN_ACCESS`         | `EventRead`   |
| `IN_MODIFY`         | `EventWrite`  |
| `IN_CLOSE_WRITE`    | `EventWrite`  |
| `IN_CREATE`         | `EventCreate` |
| `IN_MOVED_TO`       | `EventCreate` |
| `IN_DELETE`         | `EventDelete` |
| `IN_MOVED_FROM`     | `EventDelete` |

**PID/UID:** inotify does not expose the PID or UID of the process that
triggered the event. Both fields default to `0` on Linux.

### Non-Linux (`file_watcher_other.go`, build tag `!linux`)

A polling-based fallback that `os.Stat`-polls each configured path every
500 ms, comparing modification time and file size. Detects write (mtime/size
change), create (new file), and delete events. Access (read-only) events are
**not** detected by this backend.

---

## Goroutine lifecycle & restart logic

```
Start(ctx)
  └── go watchLoop(ctx, paths)
        ├── loop until ctx cancelled
        │    └── runWatcher(ctx, paths)   ← per-attempt
        │          ├── go platformWatcher()   sends FileEvents
        │          ├── forward FileEvents → emitAlert → fw.events
        │          └── returns nil (clean) or error (trigger restart)
        ├── on error: log + exponential backoff + retry
        └── defer: close(fw.events), close(fw.done)
Stop()
  └── cancel(ctx) + <-fw.done   ← blocks until watchLoop exits
```

---

## Integration with agent

`cmd/agent/main.go` creates one `FileWatcher` per `FILE`-type rule in the
configuration and registers them with the agent orchestrator via
`agent.WithWatchers`:

```go
func buildFileWatchers(cfg *config.Config, logger *slog.Logger) []agent.Watcher {
    var watchers []agent.Watcher
    for _, rule := range cfg.Rules {
        if rule.Type != "FILE" {
            continue
        }
        fw := watcher.NewFileWatcher(rule, logger)
        watchers = append(watchers, fw)
    }
    return watchers
}
```

The agent calls `FileWatcher.Start` on each registered watcher, fans events
from all watcher channels into a single goroutine per watcher, enqueues each
`AlertEvent` in the local SQLite queue, and forwards it to the gRPC transport.

---

## Configuration

FILE rules are declared in the agent YAML configuration:

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

  - name: var-log-auth
    type: FILE
    target: /var/log/auth.log
    severity: INFO
```

`target` is a standard `filepath.Glob` pattern. If the glob matches nothing at
startup, the parent directory is watched and events for any file created inside
it are forwarded.

---

## Alert event format

Each file event becomes an `agent.AlertEvent` with the following structure:

```json
{
  "tripwire_type": "FILE",
  "rule_name":     "etc-passwd-watch",
  "severity":      "CRITICAL",
  "timestamp":     "2026-02-25T19:30:00Z",
  "detail": {
    "path":       "/etc/passwd",
    "event_type": "write",
    "pid":        1234,
    "uid":        0,
    "username":   "root"
  }
}
```

`pid`, `uid`, and `username` are omitted from `detail` when they are zero /
empty (e.g. on Linux where inotify does not provide process identity).

---

## Tests

```
internal/watcher/file_watcher_test.go
```

| Test | What it verifies |
|------|-----------------|
| `TestFileWatcher_StartStop` | Start returns no error; Stop closes events channel |
| `TestFileWatcher_StopBeforeStart` | Stop before Start is safe (no panic) |
| `TestFileWatcher_StartTwiceReturnsError` | Second Start returns an error |
| `TestFileWatcher_EventDelivery` | Writing a watched file delivers an alert within 5 s |
| `TestFileWatcher_EventDelivery_GlobTarget` | Creating a file in a watched directory delivers an alert within 5 s |
| `TestFileWatcher_RestartOnError` | Watcher recovers from a platform error and resumes delivery |
| `TestFileWatcher_ContextCancellationStopsWatcher` | Cancelling ctx shuts down the watcher cleanly |
| `TestFileWatcher_InterfaceCompliance` | Compile-time check that `*FileWatcher` satisfies `agent.Watcher` |
| `TestFileWatcher_InvalidGlobReturnsError` | Invalid glob pattern causes Start to return an error |

Run:

```bash
go test ./internal/watcher/...
```
