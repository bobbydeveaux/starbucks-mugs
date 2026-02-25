# ROAM Analysis: tripwire-cybersecurity-tool

**Feature Count:** 13
**Created:** 2026-02-25T19:37:23Z
**Refined:** 2026-02-25T19:45:00Z

## Risks

1. **eBPF Kernel Version Dependency** (High): The process watcher relies on eBPF (Linux ≥5.8) for execve monitoring (`internal/watcher/ebpf/process.bpf.c`). A significant portion of production fleets run RHEL/CentOS 7/8 or older Ubuntu LTS kernels (4.x–5.4) that are incompatible. The ptrace fallback exists but is documented as an afterthought with no specified performance or reliability guarantees, and ptrace introduces substantial per-process overhead under high fork rates.

2. **mTLS PKI Operational Complexity at Scale** (High): The design delegates cert issuance, rotation, and revocation entirely to operator shell scripts (`deployments/certs/generate_ca.sh`, `deployments/certs/generate_agent_cert.sh`). There is no CRL/OCSP mechanism specified, no automated rotation, and no revocation path if an agent cert is compromised. At 50+ hosts this becomes a manual operational burden; a single expired or misconfigured cert silently drops all alerts from that host. The mitigations below require schema additions (cert serial/expiry columns on the `hosts` table) not present in the current `tripwire-cybersecurity-tool-feat-db-schema` migration files.

3. **Elevated Privilege Requirements Conflict with Security Posture** (High): Network monitoring via raw sockets or netlink requires `CAP_NET_RAW` or `CAP_NET_ADMIN`; eBPF loading requires `CAP_BPF` and `CAP_PERFMON` (Linux 5.8+) or full `CAP_SYS_ADMIN` on older kernels. This directly conflicts with the stated goal of running under a "low-privilege `tripwire` system user with minimal capabilities." Running a security agent with broad capabilities on every monitored host is itself a high-value attack surface.

4. **SQLite Write Contention Under Burst Alert Volume** (Medium): WAL mode prevents write-read blocking but serializes all writers. During a high-activity event (e.g., a directory scan triggering thousands of inotify events in seconds), all three watcher goroutines contend on a single SQLite write lock. The 5-second alert latency SLA may be violated before the gRPC transport can drain the queue.

5. **Cross-Platform Watcher Implementation Divergence** (Medium): Three fundamentally different kernel APIs (inotify, FSEvents, ReadDirectoryChangesW) must provide behaviorally identical alert semantics. FSEvents on macOS does not provide the triggering PID for read events — only write events carry process identity. This breaks the acceptance criterion for US-01 on macOS. The epic explicitly lists `file_watcher_linux.go` and `file_watcher_darwin.go` but includes no `file_watcher_windows.go` or Windows network watcher variant, despite Windows being listed as a supported platform in G-1.

6. **WebSocket Broadcaster Single-Point-of-Failure Without Redis** (Medium): The in-process broadcaster using `sync.Map` (`internal/server/websocket/broadcaster.go`) is scoped to one dashboard instance. Multi-instance deployments require Redis pub/sub, but Redis is listed as optional. If operators deploy two dashboard replicas behind a load balancer without Redis, 50% of browser clients miss alerts — a silent correctness failure with no visible error.

7. **`modernc.org/sqlite` Binary Size and Performance** (Medium): The pure-Go SQLite driver avoids CGo but produces significantly larger binaries (~10–15 MB overhead) and is measurably slower for write-heavy workloads. The 50 MB RSS target may be difficult to meet once the eBPF object files, SQLite, and zap logging are all statically linked.

8. **gRPC Protocol Version Skew Between Agents and Dashboard** (Medium): The `AgentEvent` proto has no version field and `RegisterResponse` has no capability negotiation. The dashboard has no mechanism to reject or adapt to agents running incompatible proto versions. As agents are deployed independently across a fleet, version-skewed agents could send messages with missing required fields. Proto3's silent unknown-field-drop behavior makes these failures invisible at the transport layer.

9. **Audit Log Disk Exhaustion on Agent Hosts** (Medium): The SHA-256 chained audit log (`internal/audit/audit_logger.go`) uses `O_APPEND` semantics with no rotation or maximum size constraint defined anywhere in the epic scope. On a host monitoring a high-traffic directory, this file grows unboundedly. Disk exhaustion would silently halt audit logging — the very mechanism intended for forensic continuity. No logrotate integration, size-based compaction, or `max_audit_log_size` config option is included in the current design.

---

## Obstacles

- **No OIDC Provider Specified or Provisioned**: Blocks `tripwire-cybersecurity-tool-feat-rest-api` and `tripwire-cybersecurity-tool-feat-dashboard-ui` until an OIDC provider (Keycloak, Auth0, Okta, Dex) is chosen and its discovery URL is known.

- **eBPF Compilation Toolchain Not Integrated into CI**: `internal/watcher/ebpf/process.bpf.c` requires `clang/LLVM` and kernel BTF headers. The GitHub Actions `build.yml` only covers Go cross-compilation. A Linux amd64 runner with kernel headers must be provisioned; the darwin/arm64 binary must embed a pre-compiled eBPF object or stub.

- **PostgreSQL Monthly Partition Automation Not Designed**: `db/migrations/002_alerts.sql` only creates the parent table and initial partition. Future partitions must be created before the month boundary or inserts fail. No `pg_cron` job or maintenance runbook is in scope.

- **Windows Network Watcher Has No Implementation Path**: The epic file list contains no `file_watcher_windows.go` or Windows network watcher variant. Windows builds will silently produce an agent with no network alerts and no user-facing indication of this limitation.

- **Agent `host_id` Bootstrap Sequencing Not Specified**: The `AgentEvent` message requires a `host_id` (field 2), but the agent only receives its `host_id` from a successful `RegisterAgent` RPC. The proto and orchestrator design (`internal/agent/agent.go`) do not specify what value the agent sends if `StreamAlerts` opens before registration completes, or how events queued during a first-boot registration failure are handled. This is an integration gap between `tripwire-cybersecurity-tool-feat-agent-core` and `tripwire-cybersecurity-tool-feat-agent-transport`.

---

## Assumptions

1. **Target Linux hosts run kernel ≥5.8 for eBPF support.** Validation: survey fleet kernel versions before committing to eBPF as the primary path. If >20% of hosts run older kernels, elevate the ptrace fallback to a first-class implementation with its own test suite.

2. **Operators possess the PKI expertise to generate, distribute, and rotate x509 certificates for every monitored host.** Validation: run a pilot with 5 hosts using the provided shell scripts. If the workflow takes more than 15 minutes per host, expand scope to include automated cert provisioning (Vault PKI, ACME).

3. **The monitored host's filesystem generates inotify/FSEvents events for all access patterns covered by the acceptance criteria.** Validation: verify that inotify `IN_ACCESS` fires for read-only opens. On Linux, `IN_ACCESS` is not generated for `mmap`-based reads or kernel-initiated reads (e.g., exec loader reading a setuid binary). Test US-01 against real attack scenarios, not just `cat /etc/passwd`.

4. **The PostgreSQL instance can sustain 1,000 inserts/minute with monthly partitioning and jsonb without dedicated tuning.** Validation: run a pgbench-equivalent load test with realistic alert payloads before declaring the storage layer production-ready. Validate under simulated 100-agent simultaneous alert floods.

5. **A single gRPC bidirectional stream per agent can sustain the required alert throughput without head-of-line blocking.** Validation: benchmark `StreamAlerts` under sustained 10 alerts/second per agent with the SQLite queue flush goroutine running concurrently. If the dashboard ACK is slow, the agent-side send blocks and queue depth grows unboundedly.

6. **The agent orchestrator always completes `RegisterAgent` and obtains a valid `host_id` before opening the `StreamAlerts` stream, and alerts queued before registration are held in the SQLite queue until a valid `host_id` is assigned.** Validation: confirm this sequencing is enforced in `internal/agent/agent.go` and add an integration test for the cold-start path where `RegisterAgent` fails on first attempt.

---

## Mitigations

### Risk 1 — eBPF Kernel Version Dependency
- Implement the ptrace fallback (`ptrace`/`PTRACE_SYSCALL` on Linux, `kqueue` on macOS) as a fully-tested, production-quality code path, not a stub. Define explicit test coverage for the fallback path in the test plan.
- Add a kernel version check at agent startup that logs a `WARN`-level message when falling back to ptrace, making the degraded mode visible in `/healthz` output (`"process_monitor_mode": "ptrace"`).
- Document the performance implications of ptrace fallback and recommend a maximum `processes_watched` limit when running in fallback mode.
- Evaluate `fanotify` (available since Linux 3.8) as an intermediate option that does not require eBPF but provides better performance than ptrace.

### Risk 2 — mTLS PKI Operational Complexity
- Extend `tripwire-cybersecurity-tool-feat-mtls-pki` to include a cert expiry monitoring script that emits a WARN alert via the agent when its own certificate is within 30 days of expiry.
- Add `cert_serial` and `cert_expires_at` columns to the `hosts` table (requires an additional migration in `tripwire-cybersecurity-tool-feat-db-schema`) so the dashboard can display cert expiry dates and flag near-expiry agents.
- Document a zero-downtime cert rotation procedure: agent loads new cert from disk on SIGHUP without restarting the gRPC stream.
- Define a minimum cert lifetime of 1 year and maximum of 2 years in the operator scripts to bound rotation frequency.

### Risk 3 — Elevated Privilege Requirements
- Audit minimum Linux capabilities per watcher type and document them explicitly: inotify requires no capabilities; eBPF requires `CAP_BPF + CAP_PERFMON`; raw socket network monitoring requires `CAP_NET_RAW`. Use `AmbientCapabilities` in `deployments/systemd/tripwire.service` to grant only necessary capabilities rather than running as root.
- Evaluate `fanotify FAN_OPEN_PERM` as a less-privileged alternative to raw sockets for network connection detection.
- For the network watcher, assess whether `ss`/`/proc/net/tcp` polling at 1-second intervals is an acceptable capability-free alternative sufficient for the 5-second SLA.
- Add a capabilities validation step at agent startup that logs CRITICAL and exits cleanly if required capabilities are absent, rather than failing silently at the first monitored event.

### Risk 4 — SQLite Write Contention Under Burst Alert Volume
- Implement per-watcher in-memory ring buffers (buffered Go channels, capacity 1,000 per watcher) that absorb event bursts before SQLite writes. Watchers write to channels; a single dedicated queue-writer goroutine performs batched SQLite inserts in a single transaction.
- Add a `queue_depth` metric to `/healthz` and the Prometheus endpoint. If `queue_depth > 500`, log WARN; if `> 2000`, log CRITICAL.
- Set a configurable `max_queue_depth` in `config.yaml`; when exceeded, drop INFO-severity events first (priority-based shedding) and log the drop count as a metric.
- Test SQLite WAL performance under 10,000 events/second burst on target hardware to validate the 5-second SLA before committing to the architecture.

### Risk 5 — Cross-Platform Watcher Behavioral Divergence
- Create a `WatcherCapabilities` struct returned by each platform watcher that declares which fields are populated (e.g., `ProvidesPID: false` for macOS FSEvents read events). Alert payloads must include a `capabilities_mask` so the dashboard and consumers know which fields are authoritative vs. absent.
- Add `file_watcher_windows.go` to the epic scope explicitly, or formally document Windows as unsupported and gate the Windows build with a compile-time error or runtime warning.
- Write a cross-platform acceptance test suite validating US-01 criteria on each supported OS — run this in CI on both macOS and Linux runners.

### Risk 6 — WebSocket Broadcaster Single-Point-of-Failure
- Make Redis pub/sub a required dependency for multi-instance deployments and document this clearly in the deployment guide. Include a Redis service (commented out but ready to enable) in `deployments/docker-compose.yml`.
- Add a startup check: if `REPLICA_COUNT > 1` and `REDIS_URL` is unset, refuse to start and log CRITICAL rather than silently delivering incomplete alerts.
- Implement a `broadcaster_mode` field in `/healthz` (`"in_process"` vs `"redis"`) so operators can verify deployment configuration at a glance.

### Risk 7 — Binary Size and RSS Footprint
- Benchmark the statically compiled agent binary size and RSS at idle. If binary size exceeds 30 MB or idle RSS exceeds 40 MB, evaluate replacing `modernc.org/sqlite` with a flat-file queue implementation (append-only JSON lines with compaction on reconnect) to eliminate the largest dependency.
- Use `go build -ldflags="-s -w"` and UPX compression for release binaries.
- Profile goroutine and heap allocation during idle watcher operation using `pprof` before declaring the <50 MB RSS target met; inotify watchers with large watch lists can accumulate significant kernel memory not reflected in RSS.

### Risk 8 — gRPC Protocol Version Skew
- Add an `agent_proto_version` string field to `RegisterRequest`. The dashboard should reject agents declaring an incompatible proto version at registration time with a `FAILED_PRECONDITION` status, rather than allowing the stream to open and failing silently on unexpected field layouts.
- Namespace the proto package with an explicit version path (e.g., `package tripwire.alert.v1;`) and commit to incrementing the major version on breaking field changes.
- Define a `min_supported_agent_proto_version` configuration value on the dashboard; agents below this floor are rejected at `RegisterAgent` with a clear log message instructing the operator to upgrade.
- Write dashboard-side handlers defensively to detect missing required-by-convention fields (e.g., empty `alert_id`) rather than assuming all fields are present.

### Risk 9 — Audit Log Disk Exhaustion on Agent Hosts
- Add a `max_audit_log_size_mb` option to `config.yaml` (default: 500 MB). When the audit log reaches this threshold, rotate to a new file and write a chain-anchor entry at the top of the new file containing `prev_file`, `prev_last_hash`, and `prev_sequence_num` to preserve forensic chain continuity across file boundaries.
- Expose current audit log size and path in the `/healthz` response so orchestration systems can monitor it without logging into the host.
- Log WARN when audit log utilization exceeds 80% of `max_audit_log_size_mb` and CRITICAL at 95%, giving operators a window to act before writes begin failing.
- Document `logrotate` integration in the operator runbook: use `copytruncate` mode to avoid breaking the open file descriptor, and note that `copytruncate` introduces a small race window acceptable given `O_APPEND` semantics.

---

The changes made to the existing ROAM:

**Added (Risks):**
- Risk 8: gRPC Protocol Version Skew — no version field in proto, no capability negotiation in `RegisterResponse`, silent failures when agent/dashboard versions diverge
- Risk 9: Audit Log Disk Exhaustion — `O_APPEND`-only flat file with no rotation or size bound in the epic scope

**Added (Obstacles):**
- Agent `host_id` bootstrap sequencing — `AgentEvent` requires a `host_id` that only exists after `RegisterAgent` succeeds; the orchestrator's handling of this ordering is unspecified

**Added (Assumptions):**
- Assumption 6: Orchestrator enforces `RegisterAgent`-before-`StreamAlerts` sequencing and holds queued events until a valid `host_id` is obtained

**Refined (existing items):**
- Risk 1/7: Added specific file references (`process.bpf.c`, eBPF object) from the epic to sharpen the descriptions
- Risk 2: Flagged that the cert serial/expiry mitigation requires a schema migration not currently in `tripwire-cybersecurity-tool-feat-db-schema`
- Risk 5: Strengthened the Windows gap statement — the epic explicitly confirms no Windows watcher files exist
- Risk 6: Added the specific file `internal/server/websocket/broadcaster.go` for traceability
- All mitigations: preserved in full; added file path references where the epic provided them