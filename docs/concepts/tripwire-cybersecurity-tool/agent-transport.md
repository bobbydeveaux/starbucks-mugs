# Agent gRPC Transport Client

**Status:** Implemented (Sprint 4)

**Package:** `internal/transport`

This document describes the mTLS gRPC transport client that streams alert
events from the TripWire agent to the dashboard server.

---

## Overview

```
TripWire Agent                            Dashboard Server
┌─────────────────────────────────┐  mTLS   ┌──────────────────────────────┐
│ GRPCTransport                   │─────────▶│  AlertService                │
│                                 │          │  RegisterAgent ──▶ host_id    │
│  1. loadTLSCredentials()        │          │  StreamAlerts  ──▶ persist    │
│  2. RegisterAgent  ◀──────────── │          │               ──▶ broadcast  │
│  3. StreamAlerts stream opens   │ ACK ◀─── │               ◀── ServerCmd  │
│  4. Send(AlertEvent)  ─────────▶│          └──────────────────────────────┘
│  5. drainStream (ACKs) ◀────────│
│  6. reconnect loop (backoff)    │
└─────────────────────────────────┘
```

---

## Package: `internal/transport`

**File:** `internal/transport/grpctransport.go`

### Config

```go
type Config struct {
    DashboardAddr  string        // Required. "host:port" of the gRPC server.
    CertPath       string        // Required. PEM agent TLS certificate.
    KeyPath        string        // Required. PEM agent TLS private key.
    CAPath         string        // Required. PEM CA certificate for server verification.
    InitialBackoff time.Duration // Backoff starting interval. Default: 1s.
    MaxBackoff     time.Duration // Backoff cap. Default: 2m.
    DialTimeout    time.Duration // Per-attempt RegisterAgent timeout. Default: 30s.
    Hostname       string        // Sent in RegisterAgent. Default: os.Hostname().
    Platform       string        // Sent in RegisterAgent. Default: "GOOS/GOARCH".
    AgentVersion   string        // Sent in RegisterAgent (e.g. "v1.0.0").
}
```

### Constructor

```go
func New(cfg Config, logger *slog.Logger) *GRPCTransport
```

Applies defaults (`InitialBackoff`, `MaxBackoff`, `DialTimeout`) and returns
a transport ready to be started. Does **not** open any connections.

### GRPCTransport

```go
func (t *GRPCTransport) Start(ctx context.Context) error
func (t *GRPCTransport) Send(ctx context.Context, evt watcher.AlertEvent) error
func (t *GRPCTransport) Stop()
```

`GRPCTransport` implements the `agent.Transport` interface and is registered
with the agent orchestrator via `agent.WithTransport(grpcTransport)`.

---

## Connection Lifecycle

### Start

1. **Credential loading** — `tls.LoadX509KeyPair` reads the agent cert+key; the
   CA PEM file is parsed into an `x509.CertPool`. If any file is missing or
   malformed, `Start` returns an error immediately (fast-fail at startup, before
   any connection attempt).
2. **Hostname/Platform resolution** — `os.Hostname()` and `runtime.GOOS +
   "/" + runtime.GOARCH` are resolved once and stored.
3. **Background goroutine** — `connectLoop` is launched. `Start` returns `nil`
   immediately; all subsequent connection management is asynchronous.

### connectLoop

The connection loop runs indefinitely until `Stop` is called:

```
for {
    connect(ctx)         // blocks for the lifetime of one connection
    if ctx cancelled → return
    wait = backoff.NextBackOff()
    sleep(wait)
}
```

On a successful connection (stream was established) the exponential backoff is
**reset** so the next failure starts from `InitialBackoff` again.

### connect (one connection lifecycle)

```
grpc.NewClient(addr, mTLS creds)
  └─ RegisterAgent(ctx with DialTimeout)  → host_id
       └─ StreamAlerts(ctx)               → stream
            ├─ publish stream to Send()
            └─ drainStream()              ← blocks
                 └─ stream.Recv() loop
                      ├─ ACK/ERROR: logged at debug
                      └─ error/EOF → return
  └─ conn.Close()
```

When `Stop` is called, the context is cancelled, which causes `stream.Recv()`
to return a gRPC status error. `drainStream` returns, `connect` clears the
stream pointer, and `connectLoop` detects `ctx.Err() != nil` and exits.

---

## mTLS Details

The agent presents its TLS client certificate during the gRPC handshake. The
server (`internal/server/grpc`) requires a valid client certificate signed by
the configured CA (`ClientAuth: tls.RequireAndVerifyClientCert`). Connections
without a valid client cert are rejected at the TLS layer.

On the agent side, the transport verifies the server's certificate against the
same CA cert (configured in `CAPath`). The `ServerName` is derived from the
host portion of `DashboardAddr`.

| TLS parameter | Agent side | Server side |
|---------------|-----------|------------|
| Cert+key | `CertPath` / `KeyPath` | `CertPath` / `KeyPath` |
| CA for verification | `CAPath` (verify server cert) | `CAPath` (verify client cert) |
| Min TLS version | 1.2 | 1.2 |
| Server name | derived from `DashboardAddr` | `localhost` (tests), any (production) |

---

## Exponential Backoff

Reconnection uses [`github.com/cenkalti/backoff/v4`](https://pkg.go.dev/github.com/cenkalti/backoff/v4).

| Parameter | Default | Description |
|-----------|---------|-------------|
| `InitialBackoff` | 1 s | Wait after the first failure |
| `MaxBackoff` | 2 min | Maximum wait between retries |
| `MaxElapsedTime` | 0 (∞) | Never give up |
| Reset on success | yes | Backoff resets to `InitialBackoff` after each successful stream |

Example backoff sequence after a failure:
```
attempt 1: immediate
fail → wait 1 s
attempt 2
fail → wait 2 s
attempt 3
fail → wait 4 s
…
fail → wait 2 min  (capped at MaxBackoff)
attempt N
```

---

## Send

```go
func (t *GRPCTransport) Send(_ context.Context, evt watcher.AlertEvent) error
```

- Returns `"transport: not connected to dashboard"` if no stream is active
  (during reconnection). The agent logs this as a warning; the local SQLite
  queue provides at-least-once delivery durability.
- Converts `watcher.AlertEvent` to `alertpb.AgentEvent`:
  - `AlertId` — UUID v4 (client-generated, for idempotent replay).
  - `HostId` — assigned by the server during `RegisterAgent`.
  - `TimestampUs` — `evt.Timestamp.UnixMicro()`.
  - `EventDetailJson` — `json.Marshal(evt.Detail)`.
- Concurrent `Send` calls from multiple watcher goroutines are serialised with
  an internal `sync.Mutex` (`sendMu`) because gRPC client streams do not
  support concurrent writes.

---

## Wiring in main.go

```go
grpcTransport := transport.New(transport.Config{
    DashboardAddr: cfg.DashboardAddr,
    CertPath:      cfg.TLS.CertPath,
    KeyPath:       cfg.TLS.KeyPath,
    CAPath:        cfg.TLS.CAPath,
    AgentVersion:  cfg.AgentVersion,
}, logger)
agentOpts = append(agentOpts, agent.WithTransport(grpcTransport))
```

Default backoff values (`1s` initial, `2m` max) are applied automatically.

---

## Tests

```sh
go test ./internal/transport/...
```

| Test | What it verifies |
|------|-----------------|
| `TestGRPCTransport_LoadTLSCredentials_BadCert` | Start returns an error for missing cert files |
| `TestGRPCTransport_SendBeforeStart` | Send returns error when no stream is active |
| `TestGRPCTransport_ConnectsAndRegisters` | Full mTLS dial + RegisterAgent handshake |
| `TestGRPCTransport_SendEventReachesServer` | AlertEvent is received and ACKed by the server |
| `TestGRPCTransport_StopIsClean` | Stop terminates all goroutines within 5 s |
| `TestGRPCTransport_ReconnectsAfterServerRestart` | Transport reconnects after the server is restarted |
| `TestGRPCTransport_MTLSRejectsRogueClientCert` | Server rejects a client cert signed by an unknown CA |
| `TestGRPCTransport_MultipleEvents` | Multiple sequential Send calls all reach the server |

All tests use an in-process gRPC server (`grpcserver.New` / `grpcserver.ServeOnListener`)
with a temporary in-memory PKI (CA, server cert, agent cert) to avoid any
external dependencies.

---

## Sequence Diagram

```
Agent Main          GRPCTransport            Dashboard gRPC Server
    │                    │                         │
    │  Start(ctx)        │                         │
    │──────────────────▶│                         │
    │  (validate certs) │                         │
    │  (launch goroutine)│                        │
    │◀──────────────────│                         │
    │                   │  grpc.NewClient          │
    │                   │─────────────────────────▶│
    │                   │  RegisterAgent            │
    │                   │─────────────────────────▶│
    │                   │◀──── host_id ────────────│
    │                   │  StreamAlerts             │
    │                   │─────────────────────────▶│
    │                   │  ◀── stream open ─────────│
    │                   │                         │
    │  Send(alertEvt)   │                         │
    │──────────────────▶│  stream.Send(AgentEvent)│
    │                   │─────────────────────────▶│
    │                   │◀── ServerCommand(ACK) ───│
    │                   │                         │
    │  Stop()            │                         │
    │──────────────────▶│  cancel ctx              │
    │                   │  stream closes            │
    │                   │  conn.Close()             │
    │◀──────────────────│                         │
```
