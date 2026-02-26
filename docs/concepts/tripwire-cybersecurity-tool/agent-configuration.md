# TripWire Agent Configuration Reference

This document describes every field in the TripWire agent YAML configuration
file.  The agent reads this file on startup via the `--config` flag:

```
tripwire start    --config /etc/tripwire/config.yaml
tripwire validate --config /etc/tripwire/config.yaml   # dry-run check
```

The reference implementation lives in
`agent/internal/config/config.go` with accompanying tests in
`agent/internal/config/config_test.go`.

---

## Quick start

Copy `agent/config.example.yaml` to `/etc/tripwire/config.yaml`, adjust
the dashboard endpoint and TLS paths, then add at least one tripwire rule.

---

## Top-level fields

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `hostname` | string | no | `os.Hostname()` | Agent identity sent in every alert.  Override when the system hostname is not meaningful (containers, cloud instances). |
| `agent_version` | string | no | set at build time | Surfaced in `RegisterAgent` RPCs.  Rarely overridden manually. |
| `dashboard` | object | yes | — | Connection settings for the central dashboard. |
| `rules` | object | yes | — | Tripwire rule lists (at least one rule required). |
| `queue` | object | no | see below | Local SQLite alert queue settings. |
| `audit` | object | no | see below | Append-only SHA-256 chained audit log settings. |
| `logging` | object | no | see below | Structured logger settings. |
| `health` | object | no | see below | `/healthz` HTTP endpoint settings. |

---

## `dashboard`

```yaml
dashboard:
  endpoint: "dashboard.example.com:9443"
  tls:
    ca_cert:    /etc/tripwire/certs/ca.crt
    agent_cert: /etc/tripwire/certs/agent.crt
    agent_key:  /etc/tripwire/certs/agent.key
  reconnect_delay:     5s
  reconnect_max_delay: 5m
  dial_timeout:        30s
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `endpoint` | string | **yes** | — | gRPC server address in `host:port` form. |
| `tls.ca_cert` | path | **yes** | — | PEM file for the operator CA certificate. |
| `tls.agent_cert` | path | **yes** | — | PEM file for this agent's mTLS client certificate. |
| `tls.agent_key` | path | **yes** | — | PEM file for this agent's private key (mode 0600). |
| `reconnect_delay` | duration | no | `5s` | Initial backoff before first reconnection attempt. Doubles on each failure up to `reconnect_max_delay`. |
| `reconnect_max_delay` | duration | no | `5m` | Upper bound for exponential backoff.  Must be ≥ `reconnect_delay`. |
| `dial_timeout` | duration | no | `30s` | Maximum time allowed for a single connection attempt. |

---

## `rules`

At least one rule in any category must be defined.  Rule names must be unique
within each rule type (`files`, `networks`, `processes`).

### `rules.files` — Filesystem tripwires

```yaml
rules:
  files:
    - name: etc-passwd-watch
      path: /etc/passwd
      recursive: false
      events: [read, write]
      severity: CRITICAL
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | string | **yes** | — | Unique rule identifier (used in alert `rule_name` field). |
| `path` | string | **yes** | — | File or directory path to monitor. |
| `recursive` | bool | no | `false` | When `true` and `path` is a directory, monitor all files within the tree. |
| `events` | []string | no | `[write, create, delete]` | Which filesystem operations trigger an alert.  Valid values: `read`, `write`, `create`, `delete`, `rename`, `chmod`. |
| `severity` | string | no | `WARN` | Alert severity: `INFO`, `WARN`, or `CRITICAL`. |

> **Note:** inotify `IN_ACCESS` (used for `read` events) does not fire for
> `mmap`-based reads or kernel-initiated reads (e.g. exec loader).  The
> `read` event is most reliable for user-space `open(2)` + `read(2)` patterns.

### `NETWORK` rules — TCP/UDP port tripwires

NETWORK rules monitor TCP and UDP traffic on specific ports.  The agent polls
`/proc/net/tcp`, `/proc/net/tcp6`, `/proc/net/udp`, and `/proc/net/udp6` at
a configurable interval (default 1 s) and emits an alert the first time a
connection matching the rule's filters is observed.

```yaml
rules:
  - name: ssh-honeypot
    type: NETWORK
    target: "2222"
    protocol: tcp
    direction: inbound
    severity: CRITICAL
  - name: dns-monitor
    type: NETWORK
    target: "53"
    protocol: udp
    direction: both
    severity: WARN
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | string | **yes** | — | Unique rule identifier (appears in every alert). |
| `type` | string | **yes** | — | Must be `NETWORK`. |
| `target` | string | **yes** | — | Port number to monitor (1–65535). |
| `severity` | string | **yes** | — | Alert severity: `INFO`, `WARN`, or `CRITICAL`. |
| `protocol` | string | no | `both` | Transport protocol to match: `tcp`, `udp`, or `both`. `tcp` also matches IPv6 TCP (`tcp6`); `udp` also matches IPv6 UDP (`udp6`). |
| `direction` | string | no | `inbound` | Connection direction: `inbound` (match on local port), `outbound` (match on remote port), or `both`. |

**Protocol notes:**

- **TCP** monitoring detects ESTABLISHED connections (state `0x01` in `/proc/net/tcp`).
- **UDP** monitoring detects active bound sockets (state `0x07`) and connected sockets (state `0x01`) in `/proc/net/udp`.  Because most UDP services are unconnected, the remote address in alerts may be `0.0.0.0:0`.

**Direction notes:**

- `inbound` – fires when the rule's port equals the *local* port (a remote client connected to this host).
- `outbound` – fires when the rule's port equals the *remote* port (this host initiated a connection to that port on another machine).
- `both` – fires in either case.

**Alert Detail fields** emitted by a NETWORK rule:

| Detail key | Example value | Description |
|---|---|---|
| `local_addr` | `"0.0.0.0:22"` | Local address of the connection. |
| `remote_addr` | `"10.0.0.5:54321"` | Remote address (may be `0.0.0.0:0` for unconnected UDP). |
| `protocol` | `"tcp"` / `"udp"` / `"tcp6"` / `"udp6"` | Transport protocol detected. |

### `rules.processes` — Process execution tripwires

```yaml
rules:
  processes:
    - name: netcat-watch
      process_name: nc
      match_args: ""
      severity: CRITICAL
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `name` | string | **yes** | — | Unique rule identifier. |
| `process_name` | string | **yes** | — | Executable basename to monitor (e.g. `nc`, `python3`). |
| `match_args` | string | no | `""` | If non-empty, the tripwire fires only when the process command line contains this substring. |
| `severity` | string | no | `WARN` | Alert severity: `INFO`, `WARN`, or `CRITICAL`. |

---

## `queue`

```yaml
queue:
  path: /var/lib/tripwire/queue.db
  max_depth: 10000
  flush_interval: 5s
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | no | `/var/lib/tripwire/queue.db` | SQLite database file for buffering alerts during dashboard outages. |
| `max_depth` | integer | no | `0` | Maximum queued alerts before shedding.  `0` = unlimited; INFO events shed first. |
| `flush_interval` | duration | no | `5s` | How often the flush goroutine attempts to drain the queue. |

---

## `audit`

```yaml
audit:
  path: /var/log/tripwire/audit.log
  max_size_bytes: 104857600   # 100 MiB
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `path` | string | no | `/var/log/tripwire/audit.log` | Append-only file with SHA-256 chained entries for tamper detection. |
| `max_size_bytes` | integer | no | `0` | Log size at which a WARN is emitted.  `0` = unlimited (the log is never automatically truncated). |

---

## `logging`

```yaml
logging:
  level: info
  format: json
  file_path: /var/log/tripwire/agent.log
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `level` | string | no | `info` | Minimum log level: `debug`, `info`, `warn`, `error`. |
| `format` | string | no | `json` | Output encoding: `json` (structured) or `console` (human-readable). |
| `file_path` | string | no | — | Optional additional log destination.  Logs always go to stdout. |

---

## `health`

```yaml
health:
  enabled: true
  address: "127.0.0.1:9090"
```

| Field | Type | Required | Default | Description |
|---|---|---|---|---|
| `enabled` | bool | no | `false` | Whether to serve the `/healthz` liveness endpoint. |
| `address` | string | no | `127.0.0.1:9090` | Listen address in `host:port` form.  Only validated when `enabled: true`. |

The `/healthz` response:

```json
{
  "status": "ok",
  "uptime_s": 3600,
  "queue_depth": 0,
  "last_alert_at": "2026-02-25T19:00:00Z"
}
```

---

## Validation rules

The config loader (`config.ParseFile` / `config.Parse`) applies all validation
rules together and reports every error at once rather than stopping at the
first failure.  Key constraints:

- `dashboard.endpoint` must be a valid `host:port`.
- All three TLS cert/key files must exist and be readable by the agent process.
- `reconnect_max_delay` must be ≥ `reconnect_delay`.
- `queue.max_depth` and `audit.max_size_bytes` must be ≥ 0.
- At least one rule (files, networks, or processes) must be defined.
- Rule names must be unique within each rule type.
- File rule events must be one of `read`, `write`, `create`, `delete`, `rename`, `chmod`.
- Network rule ports must be in the range 1–65535.
- Severity values are case-insensitive and normalised to uppercase at parse time.

---

## Example: minimal configuration

```yaml
dashboard:
  endpoint: "dashboard.corp:9443"
  tls:
    ca_cert:    /etc/tripwire/certs/ca.crt
    agent_cert: /etc/tripwire/certs/agent.crt
    agent_key:  /etc/tripwire/certs/agent.key

rules:
  files:
    - name: etc-passwd-watch
      path: /etc/passwd
      events: [read, write]
      severity: CRITICAL
```

All unspecified fields receive the defaults documented above.
