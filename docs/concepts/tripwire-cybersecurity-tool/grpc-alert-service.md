# gRPC Alert Service & WebSocket Broadcaster

**Status:** Implemented (Sprint 3)

This document describes the gRPC alert ingestion service and the in-process
WebSocket broadcaster that together form the real-time alert pipeline of the
TripWire dashboard server.

---

## Overview

```
TripWire Agent                 Dashboard Server
┌────────────┐  gRPC stream   ┌──────────────────────────────────┐
│ AgentEvent │──────────────▶ │  AlertService.StreamAlerts        │
└────────────┘  ServerCommand │   1. Validate event               │
                ◀──────────── │   2. Persist to PostgreSQL        │
                              │   3. Publish to Broadcaster ──▶ chan│
                              └──────────────────────────────────┘
                                         │
                                         ▼ (non-blocking fan-out)
                              ┌──────────────────────────────────┐
                              │  InProcessBroadcaster            │
                              │  sync.Map: ch1, ch2, ch3 ...     │
                              └──────────────────────────────────┘
                                   │         │         │
                                   ▼         ▼         ▼
                              WS client1  WS client2  WS client3
```

---

## gRPC Service

### Package

```
internal/server/grpc/alert_service.go
```

### Proto definition

```protobuf
// proto/alert.proto
service AlertService {
  rpc StreamAlerts(stream AgentEvent) returns (stream ServerCommand);
  rpc RegisterAgent(RegisterRequest) returns (RegisterResponse);
}
```

Generate Go code with:
```sh
protoc --go_out=. --go_opt=paths=source_relative \
       --go-grpc_out=. --go-grpc_opt=paths=source_relative \
       proto/alert.proto
```

Pre-generated stubs live in `proto/alert/`.

### Constructor

```go
svc := grpc.NewAlertService(
    store,       // storage.Store (Postgres)
    broadcaster, // websocket.Broadcaster
    logger,      // *slog.Logger
    300,         // maxEventAgeSecs (0 = default 300)
)
```

### RegisterAgent

Upserts a `Host` record in PostgreSQL.  The hostname is taken from the mTLS
client-certificate CN when available, falling back to the `hostname` field in
the `RegisterRequest`.  Returns the dashboard-assigned `host_id` and the server
clock for skew compensation.

| Field        | Required | Notes                                     |
|--------------|----------|-------------------------------------------|
| `hostname`   | yes      | Returns `InvalidArgument` if empty        |
| `platform`   | no       | Stored as-is (e.g. `"linux"`, `"darwin"`) |
| `agent_version` | no    | Stored for diagnostic purposes            |

Returns a `RegisterResponse` with:
- `host_id` — a **stable** UUID that is consistent across reconnects.  The
  first registration generates a new UUID which is stored in PostgreSQL.
  Subsequent calls for the same hostname return the pre-existing UUID via
  `ON CONFLICT (hostname) DO UPDATE … RETURNING host_id` so that all
  historical alerts remain correlated to a single identifier.
- `server_time_us` — server clock in Unix microseconds (clock-skew detection)

### StreamAlerts

Reads `AgentEvent` messages from the bidirectional client stream and for each:

1. **Validates** the event (required fields, timestamp bounds ±5 min/+60s,
   `tripwire_type` ∈ {FILE, NETWORK, PROCESS}, `severity` ∈ {INFO, WARN, CRITICAL},
   JSON validity of `event_detail_json`).
2. **Persists** a valid alert to PostgreSQL via `store.BatchInsertAlerts` (batched,
   100 ms flush interval).
3. **Publishes** the persisted alert to the WebSocket broadcaster using a
   **non-blocking send** — slow or disconnected WebSocket clients cannot stall
   the gRPC goroutine.
4. Sends an `ACK` `ServerCommand` back to the agent.  Invalid events receive an
   `ERROR` `ServerCommand` and are not written to the database.

| Field             | Validated as                                         |
|-------------------|------------------------------------------------------|
| `alert_id`        | Non-empty string; used as idempotent PK              |
| `host_id`         | Non-empty string; must have been issued by `RegisterAgent` |
| `tripwire_type`   | One of `FILE`, `NETWORK`, `PROCESS`                  |
| `severity`        | One of `INFO`, `WARN`, `CRITICAL`                    |
| `timestamp_us`    | Unix µs; must be within [-5 min, +60s] of server time |
| `event_detail_json` | Must be valid JSON or empty; stored as `null`      |

---

## gRPC Server (mTLS Infrastructure)

**File:** `internal/server/grpc/server.go`

```go
// Construct the server (wire at startup):
srv := grpc.New(cfg, logger, alertService)
```

The server requires mutual TLS (mTLS). Certificate paths are supplied via `Config`:

```go
cfg := grpcserver.Config{
    CertPath: "/etc/tripwire/server.crt",
    KeyPath:  "/etc/tripwire/server.key",
    CAPath:   "/etc/tripwire/ca.crt",
    Addr:     ":4443",
}
```

The Common Name (CN) of the connecting agent's mTLS client certificate is extracted and injected into the request context. Handlers can retrieve it via `grpcserver.AgentCNFromContext(ctx)`.

---

## WebSocket Broadcaster

### Package

```
internal/server/websocket/broadcaster.go
```

### Interface

```go
type Broadcaster interface {
    Subscribe(ctx context.Context) <-chan storage.Alert
    Unsubscribe(ch <-chan storage.Alert)
    Publish(a storage.Alert)
    Close()
}
```

### InProcessBroadcaster

The concrete implementation for single-instance deployments.

```go
b := websocket.NewBroadcaster(logger, 64 /* per-subscriber buffer */)
defer b.Close()

// WebSocket handler subscribes on connect:
ch := b.Subscribe(clientCtx)

// Alert service publishes on every persisted event (non-blocking):
b.Publish(alert)

// WebSocket handler reads and writes to the browser:
for a := range ch {
    conn.WriteJSON(a)
}
```

### Fan-out semantics

| Property | Detail |
|---|---|
| **Delivery** | Best-effort; drops for full buffers |
| **Back-pressure** | None — `Publish` is always O(1) and non-blocking |
| **Concurrency** | `sync.Map` for lock-free subscriber enumeration |
| **Cleanup** | Context cancellation automatically calls `Unsubscribe` |
| **Multi-instance** | Replace `InProcessBroadcaster` with a Redis pub/sub adapter |

### Non-blocking publish

```go
// Inside Publish:
select {
case ch <- a:
    // delivered
default:
    logger.Warn("subscriber buffer full, dropping alert", ...)
}
```

A full subscriber buffer (caused by a slow or disconnected browser client)
results in a warning log and a dropped alert for **that subscriber only**.
Other subscribers and the gRPC ingestion goroutine are unaffected.

---

## Acceptance Criteria

| # | Criterion | Covered by |
|---|---|---|
| 1 | Each persisted alert is published to the broadcaster without blocking StreamAlerts | `Publish` non-blocking select/default |
| 2 | A slow/disconnected WebSocket consumer does not cause back-pressure on the gRPC stream | Per-subscriber buffered channel; drop-on-full |
| 3 | Integration test confirms an ingested event appears on a subscribed WebSocket connection | `TestIntegration_IngestedEventAppearsOnWebSocketSubscription` |

---

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

---

## Tests

```sh
go test ./internal/server/grpc/...
go test ./internal/server/websocket/...
```

Key test cases:

| Test | What it checks |
|---|---|
| `TestStreamAlerts_PersistsAndBroadcasts` | Happy path: persist + broadcast + ACK |
| `TestStreamAlerts_SlowSubscriberDoesNotBlock` | Criterion §2: 10 events with a full buffer completes quickly |
| `TestIntegration_IngestedEventAppearsOnWebSocketSubscription` | Criterion §3: end-to-end event delivery |
| `TestBroadcaster_SlowConsumer_DropsNotBlocks` | Publish never blocks on a slow consumer |
| `TestBroadcaster_ContextCancelUnsubscribes` | Automatic cleanup on context cancel |
| `TestStreamAlerts_InvalidTripwireType` | Validation: error ACK, no persistence |
| `TestStreamAlerts_StaleTimestamp` | Validation: reject events >5 min old |
| `TestStreamAlerts_StoreError_SendsErrorACK` | DB failure: error ACK, no broadcast |
| `TestMTLSAcceptsValidClientCert` | mTLS: valid client cert authenticated, CN extracted |
| `TestMTLSRejectsNoClientCert` | mTLS: connection without client cert rejected |
| `TestMTLSRejectsUnknownCAClientCert` | mTLS: rogue CA cert rejected |
