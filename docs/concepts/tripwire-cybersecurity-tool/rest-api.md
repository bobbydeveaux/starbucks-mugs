# REST API

This document describes the HTTP REST API exposed by the TripWire dashboard
server, including authentication, routing, and all available endpoints.

## Overview

The REST API is implemented in `internal/server/rest/` using the
[chi](https://github.com/go-chi/chi) router (v5) and
[golang-jwt/jwt](https://github.com/golang-jwt/jwt) (v5) for RS256 token
validation.

### Package layout

| File | Responsibility |
|---|---|
| `middleware.go` | RS256 JWT Bearer token validation middleware |
| `store.go` | `Store` interface that handlers depend on (testability boundary) |
| `handlers.go` | HTTP handler functions for every endpoint |
| `router.go` | chi router wiring with middleware chains |

---

## Authentication

All `/api/v1/*` endpoints require a valid **RS256 signed JWT Bearer token** in
the `Authorization` header:

```
Authorization: Bearer <token>
```

The middleware (`JWTMiddleware`) performs the following checks in order:

1. `Authorization` header is present.
2. Header value has the format `Bearer <token>`.
3. Token signature is verified with the server's RSA public key using RS256.
4. Token expiry (`exp` claim) has not passed.

On success the parsed `Claims` struct is stored in the request context and
available to downstream handlers via `ClaimsFromContext(ctx)`.

On any failure the middleware responds with **HTTP 401** and a JSON body:

```json
{ "error": "invalid or expired token" }
```

The `/healthz` endpoint is **exempt** from authentication.

---

## Endpoints

### `GET /healthz`

Liveness probe. No authentication required.

**Response 200:**
```json
{ "status": "ok" }
```

---

### `GET /api/v1/alerts`

Returns a paginated, filtered list of security alerts. Requires JWT.

**Query parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `from` | RFC3339 timestamp | **yes** | Start of `received_at` window (inclusive) |
| `to` | RFC3339 timestamp | **yes** | End of `received_at` window (exclusive) |
| `host_id` | string | no | Exact host UUID filter |
| `severity` | `INFO` \| `WARN` \| `CRITICAL` | no | Severity filter |
| `limit` | integer (1–1000) | no | Max results (default: 100) |
| `offset` | integer ≥ 0 | no | Pagination offset (default: 0) |

**Response 200** – JSON array of Alert objects:
```json
[
  {
    "alert_id": "550e8400-e29b-41d4-a716-446655440000",
    "host_id": "host-uuid",
    "timestamp": "2026-02-01T12:34:56Z",
    "tripwire_type": "FILE",
    "rule_name": "etc-passwd-watch",
    "event_detail": { "path": "/etc/passwd", "event": "WRITE" },
    "severity": "CRITICAL",
    "received_at": "2026-02-01T12:34:56.123Z"
  }
]
```

**Error responses:**

| Status | Condition |
|---|---|
| `400` | Missing or malformed `from`/`to`; invalid `severity`; non-positive `limit`; negative `offset` |
| `401` | Missing or invalid JWT |
| `500` | Database error |

---

### `GET /api/v1/hosts`

Returns all registered hosts ordered alphabetically by hostname. Requires JWT.

**Response 200** – JSON array of Host objects:
```json
[
  {
    "host_id": "host-uuid",
    "hostname": "agent-01.example.com",
    "ip_address": "10.0.0.1",
    "platform": "linux",
    "agent_version": "v1.2.3",
    "last_seen": "2026-02-26T08:00:00Z",
    "status": "ONLINE"
  }
]
```

**Error responses:**

| Status | Condition |
|---|---|
| `401` | Missing or invalid JWT |
| `500` | Database error |

---

### `GET /api/v1/audit`

Returns tamper-evident audit log entries for a specific host. Requires JWT.

**Query parameters:**

| Parameter | Type | Required | Description |
|---|---|---|---|
| `host_id` | string | **yes** | Host UUID to query audit entries for |
| `from` | RFC3339 timestamp | **yes** | Start of `created_at` window (inclusive) |
| `to` | RFC3339 timestamp | **yes** | End of `created_at` window (exclusive) |

**Response 200** – JSON array of AuditEntry objects ordered by `sequence_num`:
```json
[
  {
    "entry_id": "entry-uuid",
    "host_id": "host-uuid",
    "sequence_num": 42,
    "event_hash": "sha256-hex-digest",
    "prev_hash": "sha256-hex-digest-of-previous",
    "payload": { "action": "file_write", "path": "/etc/cron.d/tripwire" },
    "created_at": "2026-02-01T12:34:56Z"
  }
]
```

**Error responses:**

| Status | Condition |
|---|---|
| `400` | Missing `host_id`; missing or malformed `from`/`to`; `to` not after `from` |
| `401` | Missing or invalid JWT |
| `500` | Database error |

---

## Error Response Format

All error responses use a consistent JSON body:

```json
{ "error": "human-readable description" }
```

The `Content-Type` header is always `application/json`.

---

## Wiring the Server

```go
import (
    "crypto/rsa"
    "github.com/tripwire/agent/internal/server/rest"
    "github.com/tripwire/agent/internal/server/storage"
)

// store is a *storage.Store; it satisfies rest.Store automatically.
store, _ := storage.New(ctx, connStr, 0, 0)

srv := rest.NewServer(store)
handler := rest.NewRouter(srv, rsaPublicKey)

http.ListenAndServe(":8080", handler)
```

To wire the server **without JWT validation** (e.g. in unit tests), pass `nil`
as the public key:

```go
handler := rest.NewRouter(srv, nil) // authentication disabled
```

---

## Running Unit Tests

```sh
go test ./internal/server/rest/...
```

The unit tests use an in-memory `mockStore` and the standard `net/http/httptest`
package; no external dependencies (database, Docker) are required.
