# gRPC AlertService — Implementation Reference

**Status:** Implemented (Sprint 3)
**Packages:**
- `internal/server/grpc/alertpb/` — generated protobuf message & service types
- `internal/server/grpc/` — `Server` implementation
- `internal/server/websocket/` — `Broadcaster` + `Handler`

---

## Overview

The AlertService gRPC server is the primary ingestion endpoint for the TripWire
dashboard.  Agent binaries dial the dashboard via mTLS and:

1. Call `RegisterAgent` once to obtain a stable `host_id` UUID.
2. Open a `StreamAlerts` bidirectional stream to push `AgentEvent` messages
   continuously.

On each received `AgentEvent` the server:

1. Validates required fields (`alert_id`, `host_id`, `tripwire_type`, `severity`).
2. Persists the alert to PostgreSQL via `storage.Store.BatchInsertAlerts` (buffered,
   flushed every 100 ms or at 100 rows — whichever comes first).
3. Fans out the alert to all connected browser WebSocket clients via the
   in-process `Broadcaster`.

---

## Proto Definition

Source: `proto/alert.proto`

```protobuf
service AlertService {
  rpc RegisterAgent(RegisterRequest) returns (RegisterResponse);
  rpc StreamAlerts(stream AgentEvent) returns (stream ServerCommand);
}
```

Generated Go code is committed to `internal/server/grpc/alertpb/` so that
builds do not require `protoc`.  Regenerate with:

```sh
protoc \
  --proto_path=proto \
  --go_out=internal/server/grpc/alertpb --go_opt=paths=source_relative \
  --go-grpc_out=internal/server/grpc/alertpb --go-grpc_opt=paths=source_relative \
  proto/alert.proto
```

---

## gRPC Server

**File:** `internal/server/grpc/server.go`

```go
// Construct the server (wire at startup):
srv := grpc.NewServer(store, broadcaster, logger)

grpcSrv := googlegrpc.NewServer( /* TLS credentials, interceptors */ )
alertpb.RegisterAlertServiceServer(grpcSrv, srv)
grpcSrv.Serve(listener)
```

### RegisterAgent

| Field        | Required | Notes                                     |
|--------------|----------|-------------------------------------------|
| `hostname`   | yes      | Returns `InvalidArgument` if empty        |
| `platform`   | no       | Stored as-is (e.g. `"linux"`, `"darwin"`) |
| `agent_version` | no    | Stored for diagnostic purposes            |

Returns a `RegisterResponse` with:
- `host_id` — the stable UUID for this hostname.  The server generates a
  candidate UUID on every call, but uses `INSERT … ON CONFLICT (hostname) DO
  UPDATE … RETURNING host_id` so that the **existing** `host_id` is returned
  when the agent reconnects.  Alert correlation with historical records is
  preserved across agent restarts.
- `server_time_us` — server clock in Unix microseconds (clock-skew detection)

### StreamAlerts

The server loops on `stream.Recv()`.  For each `AgentEvent`:

| Field             | Validated as                                         |
|-------------------|------------------------------------------------------|
| `alert_id`        | Non-empty string; used as idempotent PK              |
| `host_id`         | Non-empty string; must have been issued by `RegisterAgent` |
| `tripwire_type`   | One of `FILE`, `NETWORK`, `PROCESS`                  |
| `severity`        | One of `INFO`, `WARN`, `CRITICAL`                    |
| `timestamp_us`    | Unix µs; defaults to server `time.Now()` if zero    |
| `event_detail_json` | Must be valid JSON or empty; stored as `null`      |

The server returns `nil` on clean stream close (`io.EOF`, `context.Canceled`,
`context.DeadlineExceeded`, gRPC `Canceled`/`DeadlineExceeded` codes).
Genuine transport errors are distinguished from normal closure and returned
as non-nil errors so that the gRPC runtime can observe and log them.
Validation failures also return a gRPC status error.

---

## WebSocket Broadcaster

**Files:** `internal/server/websocket/broadcaster.go`,
`internal/server/websocket/handler.go`

### Broadcaster

The `Broadcaster` maintains a `sync.Map` of connected `Client` instances.
Each `Client` owns a buffered send channel (default depth: 64).

```go
bc := ws.NewBroadcaster(logger, 64 /* clientBufSize */)

// Register a new client (call when a WS connection is accepted):
client := bc.Register(clientID)
defer bc.Unregister(clientID)

// Fan out an alert to all clients (called by the gRPC server):
bc.Broadcast(ws.AlertMessage{ Type: "alert", Data: ws.AlertData{...} })
```

`Broadcast` never blocks.  Slow clients with full send buffers have messages
dropped; `client.Dropped` is incremented for observability.

### Handler

`Handler` is an `http.Handler` that upgrades HTTP connections to WebSocket
using the RFC 6455 handshake (no external library required — standard
`net/http` + `http.Hijacker`).

```go
h := ws.NewHandler(bc, logger, 10*time.Second /* writeTimeout */)
mux.Handle("/ws/alerts", h)
```

Wire it into the dashboard HTTP router (chi or `net/http.ServeMux`).

### WebSocket Message Format

Server → Client (JSON text frame):

```json
{
  "type": "alert",
  "data": {
    "alert_id":      "uuid",
    "host_id":       "uuid",
    "hostname":      "web-01",
    "timestamp":     "2026-02-26T10:00:00Z",
    "tripwire_type": "FILE",
    "rule_name":     "etc-passwd-watch",
    "severity":      "CRITICAL",
    "event_detail":  { "path": "/etc/passwd", "pid": 1234 }
  }
}
```

---

## Integration Example

```go
// main.go (dashboard server)
store, _ := storage.New(ctx, connStr, 0, 0)
defer store.Close(ctx)

logger := slog.New(...)
bc := ws.NewBroadcaster(logger, 64)

// gRPC server
alertSrv := grpcserver.NewServer(store, bc, logger)
grpcSrv := googlegrpc.NewServer(tlsCredentials)
alertpb.RegisterAlertServiceServer(grpcSrv, alertSrv)
go grpcSrv.Serve(grpcListener)

// HTTP / WebSocket server
mux := http.NewServeMux()
mux.Handle("/ws/alerts", ws.NewHandler(bc, logger, 0))
mux.HandleFunc("/healthz", healthzHandler)
http.Serve(httpListener, mux)
```

---

## Test Coverage

| Test file                                                    | Scenarios |
|--------------------------------------------------------------|-----------|
| `internal/server/grpc/server_test.go`                        | RegisterAgent (success, stable host_id on reconnect, missing hostname); StreamAlerts (happy path with DB + WS fan-out, invalid type/severity, missing IDs, zero timestamp, null event_detail) |
| `internal/server/websocket/broadcaster_test.go`              | Register/Unregister, Broadcast delivery, drop on full buffer, empty room, unregister unknown ID |
| `internal/server/websocket/handler_test.go`                  | Reject non-WS request, reject missing key, full handshake + broadcast delivery |

## Security Notes

### WebSocket endpoint authentication

`/ws/alerts` performs no built-in authentication beyond the RFC 6455 handshake.
The endpoint is intended to be deployed behind an authentication-aware reverse
proxy (e.g. nginx, Envoy) that enforces session cookies or bearer tokens before
forwarding the `Upgrade` request.  If the endpoint is directly reachable from
untrusted networks, add token or session validation in `Handler.ServeHTTP`
before the `http.Hijacker` call.

### WebSocket frame size limit

The `readLoop` rejects any client-to-server frame whose extended payload length
exceeds `maxFrameSize` (64 KiB) and closes the connection.  This prevents both
the int64 overflow that would occur when a malicious client sends an 8-byte
length of `0xFFFFFFFFFFFFFFFF` and the memory exhaustion that would result from
allocating a buffer for an arbitrarily large frame.  The `readLoop` goroutine
also runs with a `recover()` as defence-in-depth so a panic cannot crash the
server process.
