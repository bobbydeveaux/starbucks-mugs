# REST API – RS256 JWT Authentication Middleware

**Package:** `github.com/tripwire/agent/internal/server/rest`
**File:** `internal/server/rest/middleware.go`

---

## Overview

All TripWire dashboard REST API routes (except the liveness probe) require a valid
**RS256-signed JWT** presented as an OAuth 2.0 Bearer token.

The `JWTMiddleware` function wraps any `http.Handler` and enforces this requirement
using only the Go standard library — no external JWT library is needed.

---

## Authentication Flow

```
Client                            Dashboard REST API
  │                                       │
  │  GET /api/v1/alerts                   │
  │  Authorization: Bearer <JWT>  ──────► │
  │                                  JWTMiddleware
  │                                       │ 1. Extract Bearer token
  │                                       │ 2. Decode & validate JOSE header
  │                                       │    (must be alg=RS256)
  │                                       │ 3. Verify RSA-PKCS1v15 signature
  │                                       │ 4. Check exp claim (not expired)
  │                                       │ 5. Optionally check iss / aud
  │                                       │ 6. Inject Claims into context
  │                                       │
  │  200 OK  ◄────────────────────────── │ → next handler
  │                                       │
  │  401 Unauthorized  ◄──────────────── │ (on any failure)
  │  {"error":"unauthorized"}             │
```

---

## Usage

### 1. Load the RSA public key

```go
import "github.com/tripwire/agent/internal/server/rest"

pemBytes, err := os.ReadFile("/etc/tripwire/dashboard-rsa.pub")
if err != nil { /* handle */ }

pubKey, err := rest.ParseRSAPublicKey(pemBytes)
if err != nil { /* handle */ }
```

`ParseRSAPublicKey` accepts both:

| PEM Type          | Format            |
|-------------------|-------------------|
| `RSA PUBLIC KEY`  | PKCS#1 (RFC 3447) |
| `PUBLIC KEY`      | PKIX / SPKI       |

### 2. Wrap your router

```go
mux := http.NewServeMux()
mux.HandleFunc("/healthz",      healthzHandler)
mux.HandleFunc("/api/v1/alerts", alertsHandler)
mux.HandleFunc("/api/v1/hosts",  hostsHandler)

protected := rest.JWTMiddleware(rest.JWTConfig{
    PublicKey: pubKey,
    Issuer:    "https://auth.example.com",       // optional
    Audience:  "tripwire-dashboard",             // optional
    SkipPaths: []string{"/healthz"},             // bypass auth
}, mux)

http.ListenAndServe(":8080", protected)
```

### 3. Read claims in handlers

```go
func alertsHandler(w http.ResponseWriter, r *http.Request) {
    claims, ok := rest.ClaimsFromContext(r.Context())
    if !ok {
        // Should not happen behind JWTMiddleware, but handle defensively.
        http.Error(w, "unauthenticated", http.StatusUnauthorized)
        return
    }

    // Use claims.Subject, claims.Issuer, etc.
    log.Printf("request from subject=%s", claims.Subject)
    // ...
}
```

---

## Configuration Reference

### `JWTConfig`

| Field       | Type           | Required | Description |
|-------------|----------------|----------|-------------|
| `PublicKey` | `*rsa.PublicKey` | Yes    | RSA public key for RS256 verification |
| `Issuer`    | `string`       | No       | Expected `iss` claim; mismatch → 401 |
| `Audience`  | `string`       | No       | Must appear in `aud` claim; mismatch → 401 |
| `SkipPaths` | `[]string`     | No       | Exact URL paths that bypass auth (e.g. `/healthz`) |
| `Logger`    | `*slog.Logger` | No       | Auth-failure logger; defaults to `slog.Default()` |

---

## Claims Reference

On successful authentication, a `*rest.Claims` value is stored in the request
context.

| Field       | JSON key | Type       | Description |
|-------------|----------|------------|-------------|
| `Issuer`    | `iss`    | `string`   | Token issuer |
| `Subject`   | `sub`    | `string`   | Token subject (user/service ID) |
| `Audience`  | `aud`    | `[]string` | Token audience(s); both string and array JWT forms are normalised |
| `ExpiresAt` | `exp`    | `int64`    | Expiry (Unix seconds) |
| `IssuedAt`  | `iat`    | `int64`    | Issued-at (Unix seconds) |
| `JWTID`     | `jti`    | `string`   | JWT identifier |

---

## Error Responses

All authentication failures return:

```
HTTP/1.1 401 Unauthorized
Content-Type: application/json

{"error":"unauthorized"}
```

The specific failure reason (expired token, wrong issuer, bad signature, etc.) is
logged server-side at `WARN` level with the request path and remote address but is
**not** exposed to the caller to avoid information leakage.

---

## Security Notes

* **Algorithm enforcement** – The middleware rejects any JWT whose header declares an
  algorithm other than `RS256`. This prevents algorithm-confusion attacks (e.g.
  downgrade to `none` or `HS256`).
* **Signature-first** – The RSA signature is verified before claims are parsed.
  Invalid tokens never reach claim-validation logic.
* **No external dependencies** – Verification uses only the Go standard library
  (`crypto/rsa`, `crypto/sha256`, `encoding/base64`, `encoding/json`).
* **Skip-path exact match** – `SkipPaths` performs exact string matching on
  `r.URL.Path`, so `/healthz` does not grant access to `/healthz/extra`.

---

## Testing

Unit tests live in `internal/server/rest/middleware_test.go` and cover:

| Scenario | Expected result |
|----------|----------------|
| Valid RS256 token | 200 – claims in context |
| Missing `Authorization` header | 401 |
| Non-Bearer scheme | 401 |
| Empty token | 401 |
| Signature from wrong key | 401 |
| Corrupt signature bytes | 401 |
| Expired token (`exp` in the past) | 401 |
| `alg` ≠ RS256 in header | 401 |
| Malformed JWT structure | 401 |
| Wrong `iss` claim | 401 |
| Correct `iss` claim | 200 |
| Wrong `aud` claim | 401 |
| Correct `aud` – string form | 200 |
| Correct `aud` – array form | 200 |
| Skip-path (no token needed) | 200 |
| Skip-path exact-match only | 401 for prefix |
| `sub` claim propagated to context | verified |
| No `exp` claim | 200 (no expiry check) |
| 401 response body has `error` JSON key | verified |
| 401 `Content-Type` is `application/json` | verified |

Run tests with:

```sh
go test ./internal/server/rest/... -v
```
