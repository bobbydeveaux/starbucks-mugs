# FileGuard Middleware Reference

Documentation for the ASGI middleware stack used by the FileGuard API gateway.

---

## Overview

The FileGuard API applies three middleware layers in sequence on every incoming request:

```
Request
  │
  ▼
RequestLoggingMiddleware — extracts/generates correlation ID; logs structured JSON after response
  │
  ▼
AuthMiddleware           — validates Bearer token; attaches TenantConfig to request.state
  │
  ▼
RateLimitMiddleware      — enforces per-tenant sliding window rate limit via Redis
  │
  ▼
Route handler            — scan endpoint, batch endpoint, etc.
```

All middleware modules live in `fileguard/api/middleware/`.

---

## RequestLoggingMiddleware

**File:** `fileguard/api/middleware/logging.py`

Logs every HTTP request as a structured JSON record at `INFO` level, enriched with
a correlation ID and tenant context.

### Correlation ID

The middleware inspects the following request headers in priority order:

1. `X-Correlation-ID`
2. `X-Request-ID`

If neither header is present, a UUID v4 is generated for the request.

The resolved correlation ID is:

* Written to `request.state.correlation_id` so that downstream handlers
  (including `AuditService.log_scan_event`) can include it without re-parsing headers.
* Echoed back to the caller in the `X-Correlation-ID` response header.

### Log entry format

One JSON record is emitted at `INFO` level per request after the response has been produced:

```json
{
  "event": "http_request",
  "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
  "tenant_id": "d290f1ee-6c54-4b01-90e6-d701748f0851",
  "method": "POST",
  "path": "/v1/scan",
  "status_code": 200,
  "duration_ms": 42.7
}
```

| Field | Description |
|---|---|
| `event` | Always `"http_request"` |
| `correlation_id` | Propagated or generated identifier for end-to-end tracing |
| `tenant_id` | UUID of the authenticated tenant; `null` for public/unauthenticated paths |
| `method` | HTTP method (`GET`, `POST`, etc.) |
| `path` | URL path (without query string) |
| `status_code` | HTTP response status code |
| `duration_ms` | Wall-clock request duration in milliseconds (float, rounded to 2 dp) |

### Registration

`RequestLoggingMiddleware` must be the **outermost** middleware so it wraps the
full request–response cycle and can read `request.state.tenant` after
`AuthMiddleware` has populated it.

In Starlette, `add_middleware` calls are processed in **reverse** order, so the
last call becomes the outermost layer:

```python
from fileguard.api.middleware.auth import AuthMiddleware
from fileguard.api.middleware.logging import RequestLoggingMiddleware
from fileguard.api.middleware.rate_limit import RateLimitMiddleware

# Registration order (reverse = execution order):
app.add_middleware(RateLimitMiddleware, redis_client=redis_client)  # innermost
app.add_middleware(AuthMiddleware)
app.add_middleware(RequestLoggingMiddleware)                         # outermost — runs first
```

---

## AuthMiddleware

**File:** `fileguard/api/middleware/auth.py`

Validates the `Authorization: Bearer <token>` header on every non-public request.

### Authentication paths

| Token format | Mechanism |
|---|---|
| No dots (API key) | `bcrypt.checkpw(raw_key, stored_hash)` against `TenantConfig.api_key_hash` |
| Two dots (JWT) | JWT signature verification using JWKS fetched from `TenantConfig.jwks_url` |

### Responses

| Condition | Status |
|---|---|
| Missing or malformed `Authorization` header | `401 Unauthorized` |
| Valid token format but tenant not found / credentials invalid | `403 Forbidden` |
| Success | Sets `request.state.tenant: TenantConfig`; continues to next middleware |

### Public paths (bypass auth)

- `GET /healthz`
- `GET /v1/openapi.json`
- `GET /v1/docs`

### JWKS caching

JWKS responses are cached in-process (per `jwks_url`). Clear the cache between tenants
that rotate their JWKS endpoint by restarting the application instance. A TTL-based
cache eviction policy is planned for a future sprint.

---

## RateLimitMiddleware

**File:** `fileguard/api/middleware/rate_limit.py`

Enforces per-tenant request rate limits using a **Redis sorted-set sliding window**.

### Algorithm

A single Lua script executes atomically in Redis on every rate-limited request:

1. `ZREMRANGEBYSCORE key 0 (now_ms - window_ms)` — evict entries older than the window
2. `ZADD key now_ms member` — record this request with a millisecond-precision score
3. `ZCARD key` — count entries currently in the window
4. `EXPIRE key (window_seconds + 1)` — refresh TTL to prevent key leakage
5. `ZRANGE key 0 0 WITHSCORES` — fetch the oldest entry for `Retry-After` computation
6. Return `[count, oldest_score_ms]`

Using a Lua script ensures that steps 1–5 are atomic, preventing race conditions
between concurrent requests from the same tenant.

### Redis key format

```
fileguard:rl:{tenant_id}
```

Each key is a sorted set with millisecond timestamps as scores and unique request IDs
as members (format: `{timestamp_ms}-{request_object_id}`).

### Configuration

| Setting | Default | Source |
|---|---|---|
| Rate limit (req/min) | 100 | `TenantConfig.rate_limit_rpm` (per-tenant override) |
| Sliding window | 60 s | `RateLimitMiddleware(window_seconds=...)` constructor arg |
| Redis URL | `$REDIS_URL` | `fileguard.config.Settings.redis_url` |

The per-tenant rate limit is read from `request.state.tenant.rate_limit_rpm`
(set by `AuthMiddleware`). If the field is absent or zero, the middleware falls
back to the `default_rpm` constructor argument (default: 100).

### HTTP responses

**Within limit — 2xx pass-through with informational headers:**

```
HTTP/1.1 200 OK
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 73
X-RateLimit-Reset: 1740000060   (Unix epoch of window expiry)
```

**Limit exceeded:**

```
HTTP/1.1 429 Too Many Requests
Retry-After: 28
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1740000060

{
  "detail": "Rate limit exceeded",
  "limit": 100,
  "window_seconds": 60,
  "retry_after_seconds": 28
}
```

### Fail-open behaviour (Redis unavailable)

If Redis is unreachable or returns an error, the middleware:
1. Logs a `WARNING` message with the error details.
2. **Passes the request through** without applying rate limiting.

This fail-open strategy is intentional for rate limiting only. File scan failures
remain fail-secure (worker crashes result in `rejected` verdicts, not pass-through).

### Public paths (bypass rate limiting)

- `GET /healthz`
- `GET /v1/openapi.json`
- `GET /v1/docs`

### Registering the middleware

See the `RequestLoggingMiddleware` registration example above for the full
three-layer stack. For the rate-limiter alone:

```python
app.add_middleware(RateLimitMiddleware, redis_client=redis_client)
```

---

## TenantConfig schema

**File:** `fileguard/schemas/tenant.py`

Pydantic model representing a tenant's configuration as loaded from the database.

| Field | Type | Description |
|---|---|---|
| `id` | `UUID` | Tenant unique identifier |
| `api_key_hash` | `str \| None` | bcrypt hash of the tenant's API key |
| `jwks_url` | `HttpUrl \| None` | JWKS endpoint for OAuth 2.0 JWT verification |
| `client_id` | `str \| None` | OAuth 2.0 client ID (matched against JWT `sub`/`client_id` claim) |
| `audience` | `str \| None` | Expected JWT `aud` claim value |
| `rate_limit_rpm` | `int` | Requests per minute; default 100, range 1–100,000 |
| `disposition_rules` | `list[DispositionRule]` | Per file-type scan disposition actions |
| `custom_patterns` | `list[dict]` | Custom regex PII patterns |
| `webhook_url` | `str \| None` | Callback URL for async scan result delivery |
| `siem_config` | `SiemConfig \| None` | SIEM forwarding configuration |

---

## Running tests

```bash
pip install -e ".[dev]"
pytest tests/unit/ -v
```

All tests are fully offline — no database, Redis, or external services required.

**`test_logging_middleware.py`** covers:

- Correlation ID extracted from `X-Correlation-ID` header
- Correlation ID extracted from `X-Request-ID` header (fallback)
- UUID v4 generated when no correlation header is present
- `X-Correlation-ID` takes priority over `X-Request-ID`
- Correlation ID stored on `request.state.correlation_id`
- Correlation ID echoed in `X-Correlation-ID` response header
- Structured JSON log emitted once per request with all required fields
- `tenant_id` populated from `request.state.tenant` when set
- `tenant_id` is `null` for unauthenticated / public paths

**`test_rate_limit.py`** covers:

- Within-limit requests (200 with rate limit headers)
- Rate limit exceeded (429 with Retry-After)
- Redis unavailability (fail-open, request passes through)
- Per-tenant rate limit override respected
- Default 100 req/min applied when no override
- Public paths bypass rate limiting
- Per-tenant Redis key namespacing
- Retry-After computed from oldest window entry
