# ROAM Analysis: tripwire-cybersecurity-tool

**Feature Count:** 13
**Created:** 2026-02-25T19:37:23Z

## Risks

1. **eBPF Kernel Version Dependency** (High): The process watcher relies on eBPF (Linux ≥5.8) for execve monitoring. A significant portion of production fleets run RHEL/CentOS 7/8 or older Ubuntu LTS kernels (4.x–5.4) that are incompatible. The ptrace fallback exists but is documented as an afterthought with no specified performance or reliability guarantees, and ptrace introduces substantial per-process overhead under high fork rates.

2. **mTLS PKI Operational Complexity at Scale** (High): The design delegates cert issuance, rotation, and revocation entirely to operator shell scripts. There is no CRL/OCSP mechanism specified, no automated rotation, and no revocation path if an agent cert is compromised. At 50+ hosts this becomes a manual operational burden; a single expired or misconfigured cert silently drops all alerts from that host.

3. **Elevated Privilege Requirements Conflict with Security Posture** (High): Network monitoring via raw sockets or netlink requires `CAP_NET_RAW` or `CAP_NET_ADMIN`; eBPF loading requires `CAP_BPF` and `CAP_PERFMON` (Linux 5.8+) or full `CAP_SYS_ADMIN` on older kernels. This directly conflicts with the stated goal of running under a "low-privilege `tripwire` system user with minimal capabilities." Running a security agent with broad capabilities on every monitored host is itself a high-value attack surface.

4. **SQLite Write Contention Under Burst Alert Volume** (Medium): WAL mode prevents write-read blocking but serializes all writers. During a high-activity event (e.g., a directory scan triggering thousands of inotify events in seconds), all three watcher goroutines contend on a single SQLite write lock. The 5-second alert latency SLA may be violated before the gRPC transport can drain the queue.

5. **Cross-Platform Watcher Implementation Divergence** (Medium): Three fundamentally different kernel APIs (inotify, FSEvents, ReadDirectoryChangesW) must provide behaviorally identical alert semantics. FSEvents on macOS does not provide the triggering PID for read events — only write events carry process identity. This breaks the acceptance criterion for US-01 on macOS. The platform-specific files (`file_watcher_linux.go`, `file_watcher_darwin.go`) have no Windows equivalent in the epic file list despite Windows being listed as a supported platform in G-1.

6. **WebSocket Broadcaster Single-Point-of-Failure Without Redis** (Medium): The in-process broadcaster using `sync.Map` is scoped to one dashboard instance. Multi-instance deployments require Redis pub/sub, but Redis is listed as optional. If operators deploy two dashboard replicas behind a load balancer without Redis, 50% of browser clients miss alerts depending on which instance processed the gRPC stream — a silent correctness failure with no visible error.

7. **`modernc.org/sqlite` Binary Size and Performance** (Medium): The pure-Go SQLite driver avoids CGo but produces significantly larger binaries (~10–15 MB overhead) and is measurably slower than the native C SQLite library for write-heavy workloads. The 50 MB RSS target for the agent may be difficult to meet once the eBPF object files, SQLite, and zap logging are all statically linked.

---

## Obstacles

- **No OIDC Provider Specified or Provisioned**: The dashboard auth flow delegates entirely to an external OIDC identity provider (FR-005, HLD §6), but no provider is selected, configured, or included in the Docker Compose definition. This blocks the REST API middleware implementation (`tripwire-cybersecurity-tool-feat-rest-api`) and the React login flow (`tripwire-cybersecurity-tool-feat-dashboard-ui`) until an OIDC provider (Keycloak, Auth0, Okta, Dex) is chosen and its discovery URL is known.

- **eBPF Compilation Toolchain Not Integrated into CI**: The `process.bpf.c` eBPF program requires `clang/LLVM` and kernel BTF headers at build time to produce the CO-RE object embedded in the Go binary. The GitHub Actions build matrix as described only covers Go cross-compilation. eBPF C compilation cannot be cross-compiled the same way — a Linux amd64 runner with the correct kernel headers must be available, and the darwin/arm64 agent binary must embed a pre-compiled eBPF object or stub.

- **PostgreSQL Monthly Partition Automation Not Designed**: The HLD specifies monthly partitions for the `alerts` table (HLD §9) but the migration files (`002_alerts.sql`) only create the parent table and initial partition. Future partitions must be created before the month boundary or inserts fail. No `pg_cron` job, partition management procedure, or maintenance runbook is included in the epic scope.

- **Windows Network Watcher Has No Implementation Path**: NG-05 excludes Windows kernel-level hooks, but G-1 states the binary runs on "any Linux/macOS/Windows server." The epic file list contains no `file_watcher_windows.go` or network watcher Windows variant. Windows builds will silently produce an agent that monitors files and processes but emits no network alerts — with no user-facing indication of this limitation.

---

## Assumptions

1. **Target Linux hosts run kernel ≥5.8 for eBPF support.** Validation approach: survey the target fleet kernel versions before committing to eBPF as the primary process monitoring path. If >20% of hosts run older kernels, elevate the ptrace fallback to a first-class implementation with its own test suite and performance characterization rather than treating it as a contingency.

2. **Operators possess the PKI expertise and tooling to generate, distribute, and rotate x509 certificates for every monitored host.** Validation approach: run a pilot deployment with 5 hosts using the provided shell scripts. If the cert management workflow takes more than 15 minutes per host or produces errors for non-expert operators, the PKI feature scope must expand to include automated cert provisioning (e.g., integration with ACME/Let's Encrypt or HashiCorp Vault PKI secrets engine).

3. **The monitored host's filesystem generates inotify/FSEvents events for all access patterns covered by the acceptance criteria.** Validation approach: verify that inotify `IN_ACCESS` events fire for read-only opens on the test OS versions. On Linux, `IN_ACCESS` is not generated for `mmap`-based reads or reads by the kernel itself (e.g., exec loader reading a setuid binary). Test the US-01 acceptance criterion against real attack scenarios, not just `cat /etc/passwd`.

4. **The PostgreSQL instance can sustain 1,000 inserts/minute with monthly partitioning and jsonb without dedicated tuning.** Validation approach: run a pgbench-equivalent load test against the schema with realistic alert payloads before declaring the storage layer production-ready. The 100 ms batch-insert flush interval assumes the pgx pool can absorb bursty ingest; validate under simulated 100-agent simultaneous alert floods.

5. **A single gRPC bidirectional stream per agent can sustain the required alert throughput without head-of-line blocking.** Validation approach: benchmark the `StreamAlerts` RPC under sustained 10 alerts/second per agent with the SQLite queue flush goroutine running concurrently. gRPC streams serialize messages; if the dashboard ACK is slow, the agent-side send blocks and queue depth grows unboundedly.

---

## Mitigations

### Risk 1 — eBPF Kernel Version Dependency

- Implement the ptrace fallback (`ptrace`/`PTRACE_SYSCALL` on Linux, `kqueue` on macOS) as a fully-tested, production-quality code path, not a stub. Define explicit test coverage for the fallback path in the test plan.
- Add a kernel version check at agent startup that logs a `WARN`-level message when falling back to ptrace, making the degraded mode visible in `/healthz` output (`"process_monitor_mode": "ptrace"`).
- Document the performance implications of ptrace fallback (per-process attach overhead) and recommend a maximum `processes_watched` limit when running in fallback mode.
- Evaluate `fanotify` (available since Linux 3.8) as an intermediate option for process exec monitoring that does not require eBPF but provides better performance than ptrace.

### Risk 2 — mTLS PKI Operational Complexity

- Extend `tripwire-cybersecurity-tool-feat-mtls-pki` to include a cert expiry monitoring script that emits a WARN alert via the agent itself when its own certificate is within 30 days of expiry.
- Add cert serial tracking to the `hosts` table so the dashboard can display cert expiry dates and highlight agents with near-expiry certificates.
- Document a cert rotation procedure that allows zero-downtime rotation: agent loads new cert from disk on SIGHUP without restarting the gRPC stream.
- Define a minimum cert lifetime of 1 year and maximum of 2 years in the operator scripts to bound the rotation frequency.

### Risk 3 — Elevated Privilege Requirements

- Audit the minimum Linux capabilities required for each watcher type and document them explicitly: inotify requires no special capabilities; eBPF requires `CAP_BPF + CAP_PERFMON`; raw socket network monitoring requires `CAP_NET_RAW`. Use `AmbientCapabilities` in the systemd unit to grant only the necessary capabilities rather than running as root.
- Evaluate `fanotify FAN_OPEN_PERM` as a less-privileged alternative to raw sockets for network connection detection (requires `CAP_SYS_ADMIN` but is scoped to mount namespaces).
- For the network watcher, assess whether `ss`/`/proc/net/tcp` polling at 1-second intervals is an acceptable alternative to raw sockets for port connection detection — this requires no elevated capabilities and may be sufficient for the 5-second SLA.
- Add a capabilities validation step to agent startup that logs a CRITICAL error and exits cleanly if required capabilities are absent, rather than failing silently at the first monitored event.

### Risk 4 — SQLite Write Contention Under Burst Alert Volume

- Implement per-watcher in-memory ring buffers (buffered Go channels, capacity 1,000 per watcher) that absorb event bursts before SQLite writes. Watchers write to channels; a single dedicated queue-writer goroutine performs batched SQLite inserts in a single transaction.
- Add a `queue_depth` metric to `/healthz` and the Prometheus endpoint with an alert threshold. If `queue_depth > 500`, log a WARN; if `> 2000`, log CRITICAL.
- Set a configurable `max_queue_depth` in `config.yaml`; when exceeded, drop INFO-severity events first (priority-based shedding) and log the drop count as a metric.
- Test SQLite WAL performance under 10,000 events/second burst on target hardware to validate the 5-second SLA before committing to the architecture.

### Risk 5 — Cross-Platform Watcher Behavioral Divergence

- Create a `WatcherCapabilities` struct returned by each platform watcher implementation that declares which fields are populated (e.g., `ProvidesPID: false` for macOS FSEvents read events). Alert payloads must include a `capabilities_mask` so the dashboard and consumers know which fields are authoritative vs. absent.
- Add `file_watcher_windows.go` to the epic scope explicitly, or formally document Windows as unsupported for the file watcher and gate the Windows build with a compile-time error or runtime warning.
- Write a cross-platform acceptance test suite that validates US-01 criteria on each supported OS using a test harness that generates known filesystem events and asserts the resulting alert fields — run this in CI on macOS and Linux runners.

### Risk 6 — WebSocket Broadcaster Single-Point-of-Failure

- Make Redis pub/sub a required dependency for multi-instance deployments and document this constraint clearly in the deployment guide. The Docker Compose file should include a Redis service commented out but ready to enable.
- Add a startup check: if `REPLICA_COUNT > 1` and `REDIS_URL` is unset, refuse to start and log a CRITICAL error rather than silently delivering incomplete alerts.
- Implement a `broadcaster_mode` field in `/healthz` (`"in_process"` vs `"redis"`) so operators can verify their deployment configuration at a glance.

### Risk 7 — Binary Size and RSS Footprint

- Benchmark the statically compiled agent binary size and RSS at idle after all dependencies are linked. If binary size exceeds 30 MB or idle RSS exceeds 40 MB, evaluate replacing `modernc.org/sqlite` with a flat-file queue implementation (append-only JSON lines with a compaction step on reconnect) to eliminate the largest dependency.
- Use `go build -ldflags="-s -w"` and UPX compression for release binaries to reduce on-disk size.
- Profile goroutine and heap allocation during idle watcher operation using `pprof` before declaring the <50 MB RSS target met; inotify watchers with large watch lists can accumulate significant kernel memory not reflected in RSS.

---

## Appendix: Plan Documents

### PRD
# Product Requirements Document: TripWire CyberSecurity Tool

I want to bulld a cybersecurity tool that runs as a go binary on any server it is installed on. it will be responsible for setting tripwires and monitoring alerts to a security dashboard.

**Created:** 2026-02-25T19:23:42Z
**Status:** Draft

## 1. Overview

**Concept:** TripWire CyberSecurity Tool

I want to bulld a cybersecurity tool that runs as a go binary on any server it is installed on. it will be responsible for setting tripwires and sending alerts to a security dashboard.

**Description:** TripWire CyberSecurity Tool

I want to bulld a cybersecurity tool that runs as a go binary on any server it is installed on. it will be responsible for setting tripwires and sending alerts to a security dashboard.

---

## 2. Goals

- **G-1:** Deploy a single self-contained Go binary that installs and runs on any Linux/macOS/Windows server without external runtime dependencies.
- **G-2:** Enable operators to configure file, network, and process tripwires that detect unauthorized access or modification within 5 seconds of occurrence.
- **G-3:** Deliver real-time alerts with contextual metadata (timestamp, host, tripwire type, triggering event) to a centralized security dashboard.
- **G-4:** Maintain an audit log of all tripwire events with tamper-evident storage for forensic use.
- **G-5:** Minimize agent resource footprint to under 50MB RAM and 1% CPU on monitored hosts during idle operation.

---

## 3. Non-Goals

- **NG-1:** This tool will not perform active threat remediation or automated incident response (read-only detection only).
- **NG-2:** This tool will not replace full SIEM platforms or provide log aggregation beyond tripwire events.
- **NG-3:** This tool will not provide vulnerability scanning, patch management, or compliance auditing.
- **NG-4:** This tool will not implement its own authentication system — dashboard auth is delegated to an identity provider.
- **NG-5:** This tool will not support Windows kernel-level hooks in the initial release; Windows support is limited to file and process monitoring.

---

## 4. User Stories

- **US-01:** As a security engineer, I want to place a file-based tripwire on sensitive directories so that I am alerted when unauthorized reads or writes occur.
- **US-02:** As a SOC analyst, I want to see all tripwire alerts in a central dashboard so that I can triage incidents across multiple servers from one location.
- **US-03:** As a DevOps operator, I want to install the agent via a single binary with a config file so that onboarding new servers requires minimal effort.
- **US-04:** As a security engineer, I want to set network tripwires on specific ports so that I am notified when unexpected connections are established.
- **US-05:** As a SOC analyst, I want each alert to include host metadata and event context so that I can assess severity without logging into the affected server.
- **US-06:** As an incident responder, I want to query the audit log for historical tripwire events so that I can reconstruct attacker activity during forensic investigations.
- **US-07:** As a security engineer, I want to define process-based tripwires so that I am alerted when unexpected executables run on a monitored host.
- **US-08:** As an operator, I want the agent to automatically reconnect to the dashboard if connectivity is lost so that no alerts are dropped during network interruptions.

---

## 5. Acceptance Criteria

**US-01 — File Tripwires**
- Given a tripwire is configured on `/etc/passwd`, when any process reads or writes that file, then an alert is sent to the dashboard within 5 seconds containing file path, PID, and user.

**US-02 — Central Dashboard**
- Given multiple agents are registered, when any agent fires an alert, then the dashboard displays it in under 2 seconds with host name, alert type, and timestamp.

**US-03 — Binary Installation**
- Given a target server with Go binary copied, when the operator runs `tripwire start --config config.yaml`, then the agent begins monitoring within 10 seconds and registers with the dashboard.

**US-04 — Network Tripwires**
- Given a tripwire on port 2222, when an inbound TCP connection is established to that port, then an alert fires with source IP, destination port, and protocol.

**US-07 — Process Tripwires**
- Given a tripwire on process name `nc`, when `nc` is executed, then an alert is raised with PID, parent PID, executing user, and full command line.

---

## 6. Functional Requirements

- **FR-001:** Agent binary must accept a YAML configuration file defining tripwire rules (file paths, ports, process names).
- **FR-002:** Agent must support three tripwire types: filesystem (inotify/FSEvents/ReadDirectoryChangesW), network (port listeners), and process (execve monitoring).
- **FR-003:** Agent must transmit alerts to the dashboard via a secured WebSocket or gRPC stream.
- **FR-004:** Agent must queue alerts locally (SQLite or flat file) when the dashboard is unreachable and flush on reconnection.
- **FR-005:** Dashboard must expose a REST API for alert ingestion from agents and a WebSocket feed for real-time UI updates.
- **FR-006:** Dashboard must support multi-host views, filtering by host, tripwire type, and time range.
- **FR-007:** Each alert payload must include: `alert_id`, `host`, `timestamp`, `tripwire_type`, `rule_name`, `event_detail`, `severity`.
- **FR-008:** Agent must log all events locally with append-only semantics and SHA-256 chaining for tamper detection.
- **FR-009:** Configuration must support severity levels (INFO, WARN, CRITICAL) per rule.
- **FR-010:** Agent must expose a `/healthz` HTTP endpoint for liveness checks by orchestration systems.

---

## 7. Non-Functional Requirements

### Performance
- Agent idle CPU usage: <1% on a single core; alert processing latency: <5 seconds end-to-end from event to dashboard display.
- Dashboard must handle at least 100 connected agents and 1,000 alerts/minute without degradation.

### Security
- All agent-to-dashboard communication must use mutual TLS (mTLS) with certificate-based agent identity.
- Local audit logs must use append-only writes; SHA-256 chaining must detect log tampering.
- Dashboard API must require bearer token authentication; tokens must expire and rotate.

### Scalability
- Agent binary must be statically compiled and cross-compiled for linux/amd64, linux/arm64, darwin/amd64, darwin/arm64.
- Dashboard must be horizontally scalable behind a load balancer with shared alert storage (PostgreSQL).

### Reliability
- Agent must survive dashboard downtime via local alert queuing with at-least-once delivery guarantee.
- Agent must auto-restart on crash using systemd/launchd service definitions included in the release package.

---

## 8. Dependencies

| Dependency | Purpose |
|---|---|
| Go 1.22+ | Agent and dashboard implementation language |
| inotify (Linux) / FSEvents (macOS) | Kernel-level filesystem event monitoring |
| eBPF / ptrace (Linux) | Process execution monitoring |
| gRPC + Protocol Buffers | Agent-to-dashboard alert transport |
| PostgreSQL | Dashboard persistent alert and audit storage |
| SQLite | Agent-side local alert queue |
| React + WebSocket | Dashboard front-end real-time UI |
| mTLS / x509 | Mutual authentication between agent and dashboard |
| systemd / launchd | Agent lifecycle management on target hosts |

---

## 9. Out of Scope

- Automated threat response or process termination by the agent.
- Vulnerability scanning, CVE correlation, or patch recommendations.
- Log aggregation from application logs, syslog, or SIEM integration.
- Windows kernel-level process monitoring (file and network only for Windows v1).
- Role-based access control (RBAC) on the dashboard beyond single admin token.
- Mobile dashboard application.
- Agent auto-update mechanism.

---

## 10. Success Metrics

| Metric | Target |
|---|---|
| Alert delivery latency (p95) | <5 seconds from event to dashboard |
| Agent memory footprint (idle) | <50 MB RSS |
| Agent CPU usage (idle) | <1% single core |
| Alert drop rate during dashboard outage | 0% (local queue + replay) |
| Installation time (copy binary + start) | <2 minutes per host |
| Supported platforms at v1.0 | linux/amd64, linux/arm64, darwin/amd64 |
| Dashboard uptime SLO | 99.9% monthly |

---

## Appendix: Clarification Q&A

### Clarification Questions & Answers

*No clarification questions were submitted for this concept.*

### HLD
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

### LLD
The LLD has been written to `docs/concepts/tripwire-cybersecurity-tool/LLD.md` at 629 lines (within the 800-line limit).

Here's a summary of what was produced:

**Section highlights:**

- **File Structure** — Full repository layout across `cmd/`, `internal/` (agent-side: watcher, queue, audit, transport; server-side: grpc, rest, websocket, storage), `dashboard-ui/src/`, and `deployments/`
- **Component Designs** — Detailed Go struct + function signatures for Agent orchestrator, Watcher interface, File/Process watchers (including eBPF/ptrace fallback), SQLite queue (with schema), SHA-256 chained audit logger, gRPC transport client, gRPC server (cert CN extraction), WebSocket broadcaster, and key React hooks/components
- **Database Schema** — All four migration files (hosts, alerts with monthly partitioning, rules, audit entries) with indexes covering primary query patterns
- **API Implementation** — Handler logic, middleware chains, validation rules, and error responses for all endpoints including the WS upgrade
- **Function Signatures** — Go storage layer, config structs, and TypeScript API client + type interfaces
- **State Management** — Channel/goroutine model for agent; pgx pool + sync.Map for dashboard; TanStack Query + WS cache patching for browser
- **Test Plan** — 12 unit test files, 5 integration test scenarios (testcontainers-go), 5 Playwright E2E scenarios
- **Performance** — Batch inserts, partition pruning, react-window virtualization, eBPF ring-buffer back-pressure, sync.Map lock-free fan-out