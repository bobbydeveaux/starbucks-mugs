# High-Level Design: TripWire CyberSecurity Tool

**Created:** 2026-02-25T19:25:01Z
**Status:** Draft

## 1. Architecture Overview

TripWire follows a distributed agent/server architecture. A lightweight Go agent binary runs on each monitored host and initiates an outbound gRPC+mTLS bidirectional stream to a central Dashboard Server. The dashboard persists alerts and host state to PostgreSQL, and pushes real-time events to browser clients via WebSocket.

```
  Monitored Hosts                    Dashboard Server                Browser
  ┌──────────────────┐               ┌──────────────────────────┐   ┌──────────────┐
  │  TripWire Agent  │               │  Alert Ingestion Service  │   │  React UI    │
  │  ┌────────────┐  │  gRPC+mTLS   │  (gRPC Server)            │   │              │
  │  │ File Watch │──┼──────────────▶│                           │   │  TanStack Q  │
  │  │ Net Watch  │  │  StreamAlerts │  ┌─────────────────────┐  │   │  + WebSocket │
  │  │ Proc Watch │  │               │  │  Alert Storage      │  │◀──┼─────────────┤
  │  └────┬───────┘  │               │  │  (PostgreSQL)       │  │   │              │
  │       │          │               │  └─────────────────────┘  │   └──────────────┘
  │  ┌────▼───────┐  │               │  ┌─────────────────────┐  │
  │  │Local Queue │  │               │  │  WebSocket          │  │
  │  │ (SQLite)   │  │               │  │  Broadcaster        │  │
  │  └────────────┘  │               │  └─────────────────────┘  │
  │  ┌────────────┐  │               │  ┌─────────────────────┐  │
  │  │Audit Logger│  │               │  │  REST API (chi)     │  │
  │  │(SHA-256    │  │               │  └─────────────────────┘  │
  │  │ chained)   │  │               └──────────────────────────┘
  │  └────────────┘  │
  └──────────────────┘
              (×N hosts)
```

Agents initiate all connections outbound; no inbound ports are opened on monitored hosts except `/healthz`. The dashboard is stateless and horizontally scalable behind a TLS-terminating reverse proxy (Nginx/Caddy).

---

## 2. System Components

- **TripWire Agent (Go binary):** Single statically-compiled binary deployed per host; orchestrates all watchers, local queue, and gRPC transport.
- **File Watcher:** Uses inotify (Linux), FSEvents (macOS), or ReadDirectoryChangesW (Windows) to detect reads/writes on configured paths.
- **Network Watcher:** Raw socket or netlink listeners that detect inbound/outbound connections on configured ports.
- **Process Watcher:** Uses eBPF (Linux, kernel ≥5.8) or ptrace/kqueue fallback to detect execve events for configured process names.
- **Local Alert Queue (SQLite):** WAL-mode SQLite database embedded in the agent; buffers alerts during dashboard outages for at-least-once delivery.
- **Local Audit Logger:** Append-only flat file on the agent host; each entry contains SHA-256(prev_hash + payload) for tamper detection.
- **gRPC Transport Client:** Manages the mTLS bidirectional stream to the dashboard; handles reconnection with exponential backoff.
- **Dashboard Server (Go):** Hosts all server-side services; stateless; connects to PostgreSQL and manages WebSocket connections.
- **Alert Ingestion Service:** gRPC server implementing AlertService; receives StreamAlerts and RegisterAgent RPCs from agents.
- **Alert Storage (PostgreSQL):** Persistent store for alerts, hosts, rules, and audit entries; uses jsonb for flexible event_detail.
- **WebSocket Broadcaster:** Fans out new alert events to all connected browser clients; optionally backed by Redis pub/sub for multi-instance deployments.
- **REST API:** chi-based HTTP router exposing query and management endpoints for the React UI and external consumers.
- **React Dashboard UI:** Single-page application providing real-time alert feed, multi-host views, filtering, and trend charts.
- **Certificate Authority (x509 PKI):** Operator-managed CA; signs per-agent client certificates used for mTLS; agent CN encodes hostname identity.

---

## 3. Data Model

**Alert**
```
alert_id      UUID        PK
host_id       UUID        FK → Host
timestamp     TIMESTAMPTZ event occurrence time (agent clock)
tripwire_type ENUM        FILE | NETWORK | PROCESS
rule_name     TEXT        name of the triggering TripwireRule
event_detail  JSONB       flexible payload (path, pid, port, etc.)
severity      ENUM        INFO | WARN | CRITICAL
received_at   TIMESTAMPTZ dashboard ingestion time
```

**Host**
```
host_id       UUID        PK
hostname      TEXT        UNIQUE NOT NULL
ip_address    INET
platform      TEXT        linux | darwin | windows
agent_version TEXT
last_seen     TIMESTAMPTZ updated on each gRPC heartbeat
status        ENUM        ONLINE | OFFLINE | DEGRADED
```

**TripwireRule**
```
rule_id       UUID        PK
host_id       UUID        FK → Host (NULL = global)
rule_type     ENUM        FILE | NETWORK | PROCESS
target        TEXT        path, port number, or process name
severity      ENUM        INFO | WARN | CRITICAL
enabled       BOOLEAN     DEFAULT TRUE
```

**AuditEntry**
```
entry_id      UUID        PK
host_id       UUID        FK → Host
sequence_num  BIGINT      monotonically increasing per host
event_hash    CHAR(64)    SHA-256 hex of this entry
prev_hash     CHAR(64)    SHA-256 of previous entry (genesis = zeros)
payload       JSONB       full event data
created_at    TIMESTAMPTZ
```

---

## 4. API Contracts

**gRPC — AlertService (proto3)**
```protobuf
service AlertService {
  rpc StreamAlerts(stream AgentEvent) returns (stream ServerCommand);
  rpc RegisterAgent(RegisterRequest)  returns (RegisterResponse);
}

message AgentEvent  { string alert_id = 1; string host_id = 2;
                      int64 timestamp_us = 3; string tripwire_type = 4;
                      string rule_name = 5; bytes event_detail_json = 6;
                      string severity = 7; }
message RegisterRequest { string hostname = 1; string platform = 2;
                          string agent_version = 3; }
message RegisterResponse { string host_id = 1; int64 server_time_us = 2; }
message ServerCommand   { string type = 1; bytes payload = 2; }
```

**REST API**
```
POST   /api/v1/alerts            Ingest alert (agent HTTP fallback)
GET    /api/v1/alerts            Query alerts
         ?host=<id>&type=FILE|NETWORK|PROCESS
         &severity=INFO|WARN|CRITICAL&from=<rfc3339>&to=<rfc3339>
         &limit=100&offset=0
GET    /api/v1/hosts             List registered hosts with status
GET    /api/v1/audit             Query audit log entries (?host=&from=&to=)
GET    /healthz                  Liveness probe — 200 OK {status:"ok"}
```

**WebSocket**
```
ws://dashboard/ws/alerts
Server → Client (JSON):
{
  "type": "alert",
  "data": {
    "alert_id": "uuid", "host_id": "uuid", "hostname": "web-01",
    "timestamp": "2026-02-25T19:25:01Z", "tripwire_type": "FILE",
    "rule_name": "etc-passwd-watch", "severity": "CRITICAL",
    "event_detail": { "path": "/etc/passwd", "pid": 1234, "user": "root" }
  }
}
```

---

## 5. Technology Stack

### Backend
- Go 1.22+ for both agent and dashboard server
- gRPC + protobuf (`google.golang.org/grpc`, `google.golang.org/protobuf`)
- chi v5 or net/http stdlib for REST routing
- golang-migrate for PostgreSQL schema migrations
- `modernc.org/sqlite` (pure-Go) for agent queue — avoids CGo for static compilation
- uber-go/zap for structured JSON logging

### Frontend
- React 18 with TypeScript, Vite for build tooling
- TanStack Query v5 for REST data fetching; native WebSocket API for real-time stream
- Tailwind CSS + shadcn/ui (Radix UI primitives) for components
- recharts for alert trend and volume visualizations

### Infrastructure
- Docker + Docker Compose for dashboard deployment
- systemd unit file (Linux) and launchd plist (macOS) for agent lifecycle
- GitHub Actions CI with GOOS/GOARCH build matrix
- Nginx or Caddy as TLS-terminating reverse proxy

### Data Storage
- PostgreSQL 15+ for dashboard persistent storage (alerts, hosts, rules, audit)
- SQLite 3 embedded in agent (WAL mode) for local alert queue
- Append-only flat file on agent host for SHA-256 chained audit log

---

## 6. Integration Points

- **OS Kernel APIs:** inotify (Linux), FSEvents (macOS), eBPF via cilium/ebpf for process exec monitoring (Linux ≥5.8), ptrace/kqueue as fallback
- **Identity Provider (OIDC/OAuth2):** Dashboard delegates user authentication to an external OIDC provider; issues short-lived RS256 JWT bearer tokens (1-hour expiry with refresh) post-login
- **x509 PKI (mTLS):** Operator-managed CA signs per-agent client certificates; agent cert CN = hostname; dashboard validates full chain on every gRPC connection
- **systemd/launchd:** Service definitions shipped in release package; agent runs under a dedicated low-privilege `tripwire` system user

---

## 7. Security Architecture

- **mTLS (Agent ↔ Dashboard):** All gRPC connections require client certificates signed by the operator CA; dashboard extracts agent identity from cert CN; unauthenticated connections rejected at TLS handshake.
- **Dashboard API Auth:** RS256 JWT bearer tokens issued post-OIDC login; 1-hour expiry; rotation via refresh grant; signature and expiry validated on every request.
- **Audit Log Integrity:** Each log entry stores SHA-256(prev_hash ‖ payload); chain-break detection runs on every read; file opened with `O_APPEND` to prevent seek-and-overwrite.
- **Secrets Management:** Agent cert/key at `/etc/tripwire/agent.{crt,key}` mode 0600, owned by `tripwire` user; dashboard DB credentials via environment variables or external secrets manager (Vault/AWS Secrets Manager).
- **Network Hardening:** Agents open no inbound ports except `/healthz` on loopback; all external communication is agent-initiated outbound gRPC.

---

## 8. Deployment Architecture

**Agent**
- Static binary at `/usr/local/bin/tripwire`; config at `/etc/tripwire/config.yaml`
- Runs as `tripwire` system user (no shell, minimal capabilities)
- systemd (Linux) or launchd (macOS) manages lifecycle and auto-restart

**Dashboard**
```
Internet → Nginx/Caddy (TLS 443) → Dashboard Container (8080)
                                          │
                                    PostgreSQL (5432)
                                   (sidecar or managed RDS)
```
- Stateless Docker container; multiple replicas share PostgreSQL
- WebSocket fan-out via in-process broadcaster (single instance) or Redis pub/sub (multi-instance)
- golang-migrate runs schema migrations as pre-deploy init container

**CI/CD (GitHub Actions)**
- Build matrix: `linux/amd64`, `linux/arm64`, `darwin/amd64`, `darwin/arm64`
- Agent binaries uploaded as release artifacts; dashboard image pushed to container registry

---

## 9. Scalability Strategy

- **Agent:** One goroutine per watcher type plus an event-processing pool; targets <50 MB RSS, <1% CPU idle; SQLite WAL enables non-blocking concurrent queue reads
- **Dashboard:** Stateless — scale horizontally; pgx connection pool; batch-insert alerts with 100 ms flush interval to reduce write amplification
- **Alert Throughput:** 1,000 alerts/min across 100 agents; PostgreSQL partitioned by `received_at` month; 90-day retention with scheduled purge
- **WebSocket Fan-out:** In-process channel broadcaster for single instance; Redis pub/sub for multi-instance (eliminates sticky session requirement)

---

## 10. Monitoring & Observability

**Agent**
- `/healthz` → `{"status":"ok","uptime_s":N,"queue_depth":N,"last_alert_at":"<rfc3339>"}`
- Optional Prometheus `/metrics` (compile-time build tag): `queue_depth`, `alerts_sent_total`, `reconnect_total`

**Dashboard**
- Prometheus: `alert_ingestion_rate`, `active_agent_count`, `websocket_client_count`, `grpc_error_rate`, `db_query_duration_seconds`
- Structured JSON logs via zap; log level configurable at runtime
- Optional OpenTelemetry tracing: spans from gRPC ingestion through DB write and WebSocket broadcast

**External**
- Dashboard `/healthz` polled by uptime check; PagerDuty/OpsGenie webhook on dashboard-down
- PostgreSQL monitored via `pg_stat_statements`
- Agent local queue auto-purged after confirmed ACK; PostgreSQL alerts purged after `ALERT_RETENTION_DAYS` (default 90) via `pg_cron`

---

## 11. Architectural Decisions (ADRs)

**ADR-001: gRPC over REST for agent transport**
Bidirectional streaming enables server-push commands (future rule updates) alongside agent-push alerts. Protobuf encoding is more efficient than JSON for high-frequency events. Agent-initiated connections simplify firewall rules. Built-in mTLS eliminates a separate auth layer at the transport level.

**ADR-002: SQLite for agent-side alert queue**
Zero external dependencies; embedded in binary. WAL mode allows concurrent reads (flush goroutine) without blocking the write path (watcher goroutines). Satisfies at-least-once delivery without requiring a message broker on the monitored host.

**ADR-003: SHA-256 chained audit log**
Tamper-evident forensic integrity without a distributed ledger. Append-only file semantics enforced via `O_APPEND`; chain-break detection on read is O(n) — acceptable for forensic use. No external dependency.

**ADR-004: Single static Go binary for agent**
Eliminates runtime dependency management on monitored hosts. `modernc.org/sqlite` (pure-Go) avoids CGo for true static compilation. eBPF loader compiled in but gated by kernel version check at startup, allowing graceful fallback to ptrace on older kernels.

**ADR-005: PostgreSQL with jsonb for dashboard storage**
ACID guarantees ensure alert integrity under concurrent ingestion. `jsonb` column for `event_detail` allows new tripwire types to carry arbitrary payloads without per-type schema migrations. Native range index support simplifies time-range and severity filter queries.

---

## Appendix: PRD Reference

[PRD content omitted for brevity]