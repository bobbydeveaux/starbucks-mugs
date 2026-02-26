# Agent Lifecycle Management

This document describes how to install and manage the TripWire agent as a system service on Linux (systemd) and macOS (launchd).  Both service definitions live under `deployments/` and are designed to start the agent automatically at boot, restart it within 5 seconds on crash, and integrate with the platform's native logging infrastructure.

---

## Prerequisites

1. **Agent binary installed** at `/usr/local/bin/tripwire` (mode `0755`).
2. **Configuration file** at `/etc/tripwire/config.yaml` (copy from `deployments/config/config.example.yaml`).
3. **mTLS certificates** at the paths referenced in the config (`/etc/tripwire/agent.crt`, `/etc/tripwire/agent.key`, `/etc/tripwire/ca.crt`).  See `deployments/certs/README.md` for how to generate them.

---

## Linux — systemd

### Unit file location

The service unit is defined in `deployments/systemd/tripwire.service`.  Install it to the system unit directory and enable it with:

```bash
# 1. Create a dedicated unprivileged service account (one-time setup)
sudo useradd --system --no-create-home --shell /sbin/nologin tripwire

# 2. Create directories the agent writes to at runtime
sudo mkdir -p /var/lib/tripwire /run/tripwire
sudo chown tripwire:tripwire /var/lib/tripwire /run/tripwire

# 3. Install the unit file
sudo cp deployments/systemd/tripwire.service /etc/systemd/system/

# 4. Reload the manager and enable + start the service
sudo systemctl daemon-reload
sudo systemctl enable --now tripwire
```

### Verify the service is running

```bash
systemctl status tripwire
```

### View logs

```bash
# Live log stream
journalctl -u tripwire -f

# Last 100 lines
journalctl -u tripwire -n 100
```

### Validate the unit file

```bash
systemd-analyze verify /etc/systemd/system/tripwire.service
```

### Restart behaviour

| Scenario                      | Behaviour                              |
|-------------------------------|----------------------------------------|
| Clean exit (status 0)         | Service stops; **not** restarted       |
| Non-zero exit / signal kill   | Restarted after 5 seconds (`RestartSec=5s`) |
| > 5 crashes in 60 seconds     | Unit enters failed state; manual intervention required |

### Security hardening

The unit file includes the following systemd sandboxing directives:

- `NoNewPrivileges=true` — prevents `setuid` or capability escalation.
- `ProtectSystem=strict` — mounts `/`, `/usr`, and `/boot` read-only.
- `ProtectHome=read-only` — home directories are read-only.
- `PrivateTmp=true` — private `/tmp` and `/var/tmp` namespaces.
- `ReadWritePaths` — only `/var/lib/tripwire` and `/run/tripwire` are writable.
- `CPUQuota=50%` / `MemoryMax=256M` — limits resource consumption.

---

## macOS — launchd

### Plist file location

The launchd job definition is at `deployments/launchd/com.tripwire.agent.plist`.  It should be installed as a **LaunchDaemon** (system-wide, runs as root or a dedicated user) rather than a LaunchAgent (per-user session), so that monitoring continues even when no user is logged in.

```bash
# 1. Create log directory
sudo mkdir -p /var/log/tripwire /var/lib/tripwire
sudo chown root:wheel /var/log/tripwire /var/lib/tripwire

# 2. Install the plist
sudo cp deployments/launchd/com.tripwire.agent.plist /Library/LaunchDaemons/

# 3. Set correct ownership (LaunchDaemons must be owned by root)
sudo chown root:wheel /Library/LaunchDaemons/com.tripwire.agent.plist
sudo chmod 644 /Library/LaunchDaemons/com.tripwire.agent.plist

# 4. Load and start the daemon
sudo launchctl load /Library/LaunchDaemons/com.tripwire.agent.plist
```

### Verify the service is running

```bash
sudo launchctl list com.tripwire.agent
```

A `PID` value other than `-` confirms the agent is running.

### Unload the daemon

```bash
sudo launchctl unload /Library/LaunchDaemons/com.tripwire.agent.plist
```

### View logs

Stdout and stderr are redirected to `/var/log/tripwire/`:

```bash
tail -f /var/log/tripwire/agent.log
tail -f /var/log/tripwire/agent-error.log
```

### Validate the plist

```bash
plutil -lint /Library/LaunchDaemons/com.tripwire.agent.plist
```

### Restart behaviour

| Scenario                      | Behaviour                              |
|-------------------------------|----------------------------------------|
| Clean exit (status 0)         | Daemon stops; **not** restarted (`KeepAlive.Crashed=true`) |
| Non-zero exit / signal kill   | Restarted after 5 seconds (`ThrottleInterval=5`) |

---

## Installed paths reference

| Path                              | Description                                          |
|-----------------------------------|------------------------------------------------------|
| `/usr/local/bin/tripwire`         | Agent binary                                         |
| `/etc/tripwire/config.yaml`       | YAML configuration (see `deployments/config/`)       |
| `/etc/tripwire/agent.crt`         | Agent mTLS certificate                               |
| `/etc/tripwire/agent.key`         | Agent mTLS private key                               |
| `/etc/tripwire/ca.crt`            | CA certificate for verifying the dashboard           |
| `/var/lib/tripwire/`              | Runtime state directory (SQLite alert queue)         |
| `/var/log/tripwire/` (macOS)      | Log files written by launchd redirection             |

---

## Further reading

- `deployments/certs/README.md` — PKI setup and certificate management.
- `deployments/config/config.example.yaml` — Annotated configuration template.
- `docs/concepts/tripwire-cybersecurity-tool/agent-configuration.md` — All configuration options.
