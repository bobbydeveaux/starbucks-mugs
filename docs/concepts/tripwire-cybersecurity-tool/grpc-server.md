# TripWire Dashboard — gRPC Alert Ingestion Service

This document describes the gRPC server that receives alert events from TripWire
agents, including the mTLS configuration, agent-identity (cert CN) extraction,
and the dashboard server entry point.

---

## Overview

The TripWire dashboard exposes a gRPC service (`AlertService`) that agent
binaries connect to over mTLS.  Every connecting agent must present a valid
client certificate signed by the shared CA; the server certificate is verified
by the agent in the same way.

Once the TLS handshake completes, the server extracts the **Common Name (CN)**
from the verified client certificate chain and injects it into the gRPC request
context.  All downstream handlers retrieve the agent identity from the context
via `grpcserver.AgentCNFromContext` — they never need to touch TLS state
directly.

---

## Package: `internal/server/grpc`

**File:** `internal/server/grpc/server.go`

### Config

```go
type Config struct {
    CertPath string // PEM server TLS certificate path. Required.
    KeyPath  string // PEM server TLS private key path. Required.
    CAPath   string // PEM CA certificate path for verifying client certs. Required.
    Addr     string // TCP listen address. Default: ":4443".
}
```

### Server

```go
func New(cfg Config, logger *slog.Logger, srv alertpb.AlertServiceServer) (*Server, error)
```

`New` loads TLS credentials from `cfg`, configures mTLS with
`tls.RequireAndVerifyClientCert`, and wraps the gRPC server with two
interceptors (unary and streaming) that extract the client cert CN.

Returns an error if any certificate path is invalid or the CA certificate
cannot be parsed.

#### TLS configuration

| Property | Value |
|----------|-------|
| `ClientAuth` | `tls.RequireAndVerifyClientCert` — all client certs are verified against `CAPath` |
| `MinVersion` | `tls.VersionTLS12` |
| `RootCAs` / `ClientCAs` | loaded from `CAPath` |

Connections without a valid, CA-signed client certificate are **rejected at
the TLS handshake** before any RPC handler is invoked.

### Lifecycle methods

```go
func (s *Server) Serve(ctx context.Context) error
func (s *Server) ServeOnListener(ctx context.Context, lis net.Listener) error
func (s *Server) GracefulStop()
func (s *Server) Stop()
```

| Method | Description |
|--------|-------------|
| `Serve` | Binds `cfg.Addr`, then calls `ServeOnListener`. Blocks until ctx is cancelled or a fatal error. |
| `ServeOnListener` | Accepts connections on the provided listener. Useful in tests using port 0. |
| `GracefulStop` | Stops accepting new connections; blocks until in-flight RPCs complete. |
| `Stop` | Hard-stops immediately, terminating all active RPCs. |

When `ctx` is cancelled, `Serve` / `ServeOnListener` initiates a graceful stop.

### Agent CN context helpers

```go
// AgentCNFromContext retrieves the agent CN injected by the interceptor.
// Returns ("", false) when no CN is present.
func AgentCNFromContext(ctx context.Context) (string, bool)
```

#### Usage in a handler

```go
func (s *AlertService) RegisterAgent(ctx context.Context, req *proto.AgentRegistration) (*proto.ServerAck, error) {
    cn, ok := grpcserver.AgentCNFromContext(ctx)
    if !ok {
        return nil, status.Error(codes.Unauthenticated, "missing agent identity")
    }
    // cn == "sensor-rack-42.example.com" (the agent cert CN)
    ...
}
```

### CN interceptors

Two interceptors are installed at server creation via
`grpc.ChainUnaryInterceptor` and `grpc.ChainStreamInterceptor`:

| Interceptor | Scope |
|-------------|-------|
| `cnUnaryInterceptor` | All unary RPCs |
| `cnStreamInterceptor` | All streaming RPCs |

Both interceptors:
1. Call `peer.FromContext(ctx)` to retrieve the TLS peer info.
2. Walk `tlsInfo.State.VerifiedChains[0][0].Subject.CommonName` to get the CN.
3. Inject the CN into the context via `context.WithValue`.
4. Return `codes.Unauthenticated` if extraction fails (defence-in-depth; the
   mTLS layer should have already rejected invalid clients).

---

## Proto schema: `proto/alert.proto`

**Files:** `proto/alert.proto`, `proto/alert.pb.go`, `proto/alert_grpc.pb.go`

```protobuf
syntax = "proto3";
package alert;
option go_package = "github.com/tripwire/agent/proto";

message AgentRegistration {
  string agent_cn      = 1; // Common Name from the agent's mTLS certificate
  string hostname      = 2;
  string platform      = 3;
  string agent_version = 4;
  string ip_address    = 5;
}

message AgentEvent {
  string host_id       = 1;
  int64  timestamp_ms  = 2; // Unix milliseconds
  string tripwire_type = 3; // FILE | NETWORK | PROCESS
  string rule_name     = 4;
  string severity      = 5; // INFO | WARN | CRITICAL
  bytes  event_detail  = 6; // JSON payload
}

message ServerAck {
  bool   ok       = 1;
  string alert_id = 2; // set when ok=true
  string error    = 3; // set when ok=false
}

service AlertService {
  rpc RegisterAgent(AgentRegistration) returns (ServerAck);
  rpc StreamAlerts(stream AgentEvent) returns (stream ServerAck);
}
```

The `.pb.go` and `_grpc.pb.go` files contain hand-authored Go bindings that
are compatible with `protoc-gen-go v1.34.2`.  The raw `FileDescriptorProto`
binary is generated by `internal/proto/gen/gen.js` (a Node.js encoder script).

---

## Binary: `cmd/server/main.go`

### CLI flags

| Flag | Default | Description |
|------|---------|-------------|
| `-grpc-addr` | `:4443` | gRPC listener address (mTLS) |
| `-http-addr` | `:8080` | HTTP REST API listener address |
| `-tls-cert` | `/etc/tripwire/server.crt` | PEM server certificate |
| `-tls-key` | `/etc/tripwire/server.key` | PEM server private key |
| `-tls-ca` | `/etc/tripwire/ca.crt` | PEM CA certificate (verifies agent client certs) |
| `-dsn` | _(empty)_ | PostgreSQL DSN; storage disabled when empty (dev mode) |
| `-jwt-pubkey` | _(empty)_ | PEM RSA public key for JWT validation; REST auth disabled when empty |
| `-log-level` | `info` | Log level: `debug` \| `info` \| `warn` \| `error` |

### Startup sequence

1. Parse flags and initialise a structured JSON `slog.Logger`.
2. Open PostgreSQL connection pool (skipped when `dsn` is empty).
3. Create the gRPC server:
   - Load mTLS credentials from cert/key/CA paths.
   - Install CN interceptors.
   - Register `UnimplementedAlertServiceServer` stub (replaced in sprint 4 by the concrete `AlertService` implementation).
4. Parse optional JWT public key for REST API authentication.
5. Create the REST HTTP server (chi router + JWT middleware).
6. Start gRPC and HTTP servers in goroutines.
7. Block until `SIGTERM`, `SIGINT`, or a fatal server error.
8. Initiate graceful shutdown (30-second timeout):
   - Cancel the context (triggers gRPC graceful stop).
   - Shut down the HTTP server.
   - Wait for gRPC drain to complete; force-stop if timeout exceeded.

### Running the server

```bash
# Build
go build -o tripwire-server ./cmd/server

# Run (dev mode — no DB, no JWT)
./tripwire-server \
  -grpc-addr :4443 \
  -http-addr :8080 \
  -tls-cert  /path/to/server.crt \
  -tls-key   /path/to/server.key \
  -tls-ca    /path/to/ca.crt

# Production (with DB and JWT)
./tripwire-server \
  -dsn "postgres://user:pass@db:5432/tripwire?sslmode=require" \
  -jwt-pubkey /etc/tripwire/jwt.pub \
  -log-level info
```

---

## Testing

**File:** `internal/server/grpc/server_test.go`

The test suite uses an in-memory PKI (`testPKI`) that generates a self-signed
CA and signs server and client certificates in `t.TempDir()`.  All tests bind
on `127.0.0.1:0` (OS-assigned port) to avoid port conflicts.

| Test | Description |
|------|-------------|
| `TestAgentCNFromContext` | Verifies `AgentCNFromContext` returns false on a plain context |
| `TestMTLSAcceptsValidClientCert` | End-to-end: valid CA-signed cert → RegisterAgent succeeds, CN extracted correctly |
| `TestMTLSRejectsNoClientCert` | Client without cert → TLS handshake fails |
| `TestMTLSRejectsUnknownCAClientCert` | Client with cert from a foreign CA → TLS handshake fails |
| `TestCNExtraction` | Various CN strings are correctly propagated to handlers |
| `TestServerNewErrorBadCert` | Invalid cert paths → `New` returns error |

---

## Security notes

- mTLS is enforced at the **TLS transport layer**, not at the application
  layer.  The CN interceptors add defence-in-depth but connections without a
  valid client certificate never reach any handler.
- The server uses a minimum TLS version of 1.2.  TLS 1.3 is preferred by
  default when both sides support it.
- The agent CN is the **authoritative identity** for all RPCs.  Handlers should
  always call `AgentCNFromContext` and reject requests where the CN is absent.
- Never disable `ClientAuth: tls.RequireAndVerifyClientCert` — doing so would
  allow unauthenticated agents to stream arbitrary alert events.
