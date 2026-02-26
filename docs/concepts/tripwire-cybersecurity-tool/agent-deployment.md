# TripWire Agent — Deployment Guide

This document covers the full lifecycle of running the TripWire agent as a
**managed system service** on Linux (systemd) and macOS (launchd).  For the
agent configuration schema, see
[agent-configuration.md](./agent-configuration.md).

---

## Table of Contents

1. [Overview](#overview)
2. [Prerequisites](#prerequisites)
3. [Directory layout](#directory-layout)
4. [Quick start — Linux (systemd)](#quick-start--linux-systemd)
5. [Quick start — macOS (launchd)](#quick-start--macos-launchd)
6. [Manual installation](#manual-installation)
   - [Linux](#linux-manual)
   - [macOS](#macos-manual)
7. [Managing the service](#managing-the-service)
8. [Linux capability requirements](#linux-capability-requirements)
9. [macOS Full Disk Access](#macos-full-disk-access)
10. [Logrotate integration (Linux)](#logrotate-integration-linux)
11. [Upgrade procedure](#upgrade-procedure)
12. [Uninstall](#uninstall)

---

## Overview

The TripWire agent is a single self-contained binary (`tripwire`) that:

- Monitors file system paths for access/modification events.
- Watches for suspicious process executions.
- Detects unexpected network connections.
- Streams alerts to the central dashboard over mTLS-secured gRPC.
- Buffers alerts locally (SQLite) when the dashboard is unreachable.

For production deployments the binary is managed by the operating system's
native service supervisor so it starts at boot and is restarted automatically
on failure.

---

## Prerequisites

| Requirement | Linux | macOS |
|---|---|---|
| OS version | Any systemd-based distribution | macOS 13 Ventura or later |
| Kernel | ≥ 5.8 recommended (eBPF process monitoring) | N/A |
| Root / sudo | Required for installation | Required for installation |
| mTLS certificates | Required | Required |
| Full Disk Access | N/A | Required (macOS 14+) |

---

## Directory layout

After installation the following paths are created:

| Path | Purpose | Owner |
|---|---|---|
| `/usr/local/bin/tripwire` | Agent binary | root |
| `/etc/tripwire/config.yaml` | Main configuration file | root:tripwire (Linux) |
| `/etc/tripwire/certs/ca.crt` | CA certificate for mTLS | root:tripwire (Linux) |
| `/etc/tripwire/certs/agent.crt` | Agent client certificate | root:tripwire (Linux) |
| `/etc/tripwire/certs/agent.key` | Agent private key (0600) | root:tripwire (Linux) |
| `/etc/tripwire/agent.env` | Optional environment overrides | root:tripwire (Linux) |
| `/var/lib/tripwire/queue.db` | SQLite alert queue | tripwire (Linux) / root (macOS) |
| `/var/log/tripwire/audit.log` | SHA-256 chained audit log | tripwire (Linux) / root (macOS) |
| `/var/log/tripwire/agent.log` | Standard output (macOS) | root (macOS) |
| `/var/log/tripwire/agent.err` | Standard error (macOS) | root (macOS) |

On **Linux**, configuration files are group-readable by the `tripwire` group;
private keys must be mode `0600`.

On **macOS**, all paths are owned by root because the LaunchDaemon runs as
root.

---

## Quick start — Linux (systemd)

```bash
# 1. Build the agent binary for the target host.
GOOS=linux GOARCH=amd64 go build -ldflags="-s -w" -o tripwire-linux-amd64 ./cmd/agent

# 2. Copy the binary and run the install script on the target host.
scp tripwire-linux-amd64 root@host:/tmp/
ssh root@host

# 3. (On the target host) Run the installer.
cd /path/to/tripwire-repo
sudo ./deployments/scripts/install-agent-linux.sh /tmp/tripwire-linux-amd64

# 4. Install mTLS certificates.
sudo cp ca.crt         /etc/tripwire/certs/
sudo cp agent.crt      /etc/tripwire/certs/
sudo cp agent.key      /etc/tripwire/certs/
sudo chmod 0600        /etc/tripwire/certs/agent.key
sudo chown root:tripwire /etc/tripwire/certs/agent.key

# 5. Edit configuration.
sudo vi /etc/tripwire/config.yaml

# 6. Validate configuration.
sudo tripwire validate --config /etc/tripwire/config.yaml

# 7. (Re)start the service.
sudo systemctl restart tripwire-agent
sudo systemctl status  tripwire-agent
```

---

## Quick start — macOS (launchd)

```bash
# 1. Build the agent binary for macOS.
GOOS=darwin GOARCH=arm64 go build -ldflags="-s -w" -o tripwire-darwin-arm64 ./cmd/agent
# or for Intel Macs:
# GOOS=darwin GOARCH=amd64 go build -ldflags="-s -w" -o tripwire-darwin-amd64 ./cmd/agent

# 2. Run the installer.
sudo ./deployments/scripts/install-agent-macos.sh ./tripwire-darwin-arm64

# 3. Install mTLS certificates.
sudo cp ca.crt    /etc/tripwire/certs/
sudo cp agent.crt /etc/tripwire/certs/
sudo cp agent.key /etc/tripwire/certs/
sudo chmod 0600   /etc/tripwire/certs/agent.key

# 4. Edit configuration.
sudo vi /etc/tripwire/config.yaml

# 5. Validate configuration.
sudo tripwire validate --config /etc/tripwire/config.yaml

# 6. Restart the daemon.
sudo launchctl kickstart -k system/com.tripwire.agent
```

> **macOS Full Disk Access** — Before the agent can watch system paths
> (`/etc`, `/private`, `/var`, ...) you must grant
> `/usr/local/bin/tripwire` Full Disk Access in
> **System Settings → Privacy & Security → Full Disk Access** (macOS 14+).
> See [macOS Full Disk Access](#macos-full-disk-access) for details.

---

## Manual installation

### Linux (manual) {#linux-manual}

#### 1. Create the system user and group

```bash
sudo groupadd --system tripwire
sudo useradd  --system \
              --gid tripwire \
              --no-create-home \
              --home-dir /var/lib/tripwire \
              --shell /sbin/nologin \
              --comment "TripWire Security Agent" \
              tripwire
```

#### 2. Create directories

```bash
sudo mkdir -p /etc/tripwire/certs \
              /var/lib/tripwire \
              /var/log/tripwire

sudo chown -R root:tripwire /etc/tripwire
sudo chmod 750 /etc/tripwire /etc/tripwire/certs

sudo chown tripwire:tripwire /var/lib/tripwire /var/log/tripwire
sudo chmod 750               /var/lib/tripwire /var/log/tripwire
```

#### 3. Install the binary

```bash
sudo install -m 0755 -o root -g root ./tripwire-linux-amd64 /usr/local/bin/tripwire
```

#### 4. Install configuration

```bash
sudo install -m 0640 -o root -g tripwire agent/config.example.yaml \
     /etc/tripwire/config.yaml
sudo vi /etc/tripwire/config.yaml   # fill in dashboard endpoint + rules
```

#### 5. Install certificates

```bash
sudo install -m 0644 -o root -g tripwire ca.crt    /etc/tripwire/certs/
sudo install -m 0644 -o root -g tripwire agent.crt /etc/tripwire/certs/
sudo install -m 0600 -o root -g tripwire agent.key /etc/tripwire/certs/
```

#### 6. Install the systemd unit

```bash
sudo cp deployments/systemd/tripwire-agent.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tripwire-agent
```

---

### macOS (manual) {#macos-manual}

#### 1. Create directories

```bash
sudo mkdir -p /etc/tripwire/certs \
              /var/lib/tripwire \
              /var/log/tripwire

sudo chown -R root:wheel /etc/tripwire /var/lib/tripwire /var/log/tripwire
sudo chmod 750           /etc/tripwire /etc/tripwire/certs
sudo chmod 750           /var/lib/tripwire /var/log/tripwire
```

#### 2. Install the binary

```bash
sudo mkdir -p /usr/local/bin
sudo install -m 0755 -o root -g wheel ./tripwire-darwin-arm64 \
     /usr/local/bin/tripwire
# Remove Gatekeeper quarantine attribute on downloaded binaries.
sudo xattr -d com.apple.quarantine /usr/local/bin/tripwire 2>/dev/null || true
```

#### 3. Install configuration and certificates

```bash
sudo install -m 0640 -o root -g wheel agent/config.example.yaml \
     /etc/tripwire/config.yaml
sudo vi /etc/tripwire/config.yaml

sudo install -m 0644 -o root -g wheel ca.crt    /etc/tripwire/certs/
sudo install -m 0644 -o root -g wheel agent.crt /etc/tripwire/certs/
sudo install -m 0600 -o root -g wheel agent.key /etc/tripwire/certs/
```

#### 4. Install the launchd plist

```bash
sudo install -m 0644 -o root -g wheel \
     deployments/launchd/com.tripwire.agent.plist \
     /Library/LaunchDaemons/

sudo launchctl bootstrap system \
     /Library/LaunchDaemons/com.tripwire.agent.plist
```

---

## Managing the service

### Linux (systemd)

| Action | Command |
|---|---|
| Start | `sudo systemctl start tripwire-agent` |
| Stop | `sudo systemctl stop tripwire-agent` |
| Restart | `sudo systemctl restart tripwire-agent` |
| Reload config | `sudo systemctl reload tripwire-agent` |
| Status | `sudo systemctl status tripwire-agent` |
| Enable at boot | `sudo systemctl enable tripwire-agent` |
| Disable at boot | `sudo systemctl disable tripwire-agent` |
| View logs | `sudo journalctl -u tripwire-agent -f` |
| View recent logs | `sudo journalctl -u tripwire-agent --since "1 hour ago"` |

### macOS (launchd)

| Action | Command |
|---|---|
| Start / Restart | `sudo launchctl kickstart -k system/com.tripwire.agent` |
| Stop | `sudo launchctl bootout system/com.tripwire.agent` |
| Status | `sudo launchctl list com.tripwire.agent` |
| Load plist | `sudo launchctl bootstrap system /Library/LaunchDaemons/com.tripwire.agent.plist` |
| View stdout log | `tail -f /var/log/tripwire/agent.log` |
| View stderr log | `tail -f /var/log/tripwire/agent.err` |
| Apple Unified Log | `sudo log stream --predicate 'subsystem == "com.tripwire.agent"'` |

---

## Linux capability requirements

The TripWire agent's process watcher can operate in two modes depending on the
kernel version:

| Mode | Kernel | Required capabilities |
|---|---|---|
| eBPF | ≥ 5.8 | `CAP_BPF`, `CAP_PERFMON` |
| eBPF (legacy) | < 5.8 | `CAP_SYS_ADMIN` |
| ptrace (fallback) | Any | `CAP_SYS_PTRACE` |

The network watcher requires `CAP_NET_ADMIN` to attach eBPF programs to
network interfaces.

The systemd unit grants these capabilities via the `AmbientCapabilities`
directive so the `tripwire` user receives them without a setuid wrapper.

**Hardening for kernel ≥ 5.8:** Once you have confirmed eBPF is working,
remove `CAP_SYS_ADMIN` from both `CapabilityBoundingSet` and
`AmbientCapabilities` in the unit file:

```ini
CapabilityBoundingSet=CAP_SYS_PTRACE CAP_BPF CAP_PERFMON CAP_NET_ADMIN
AmbientCapabilities=CAP_SYS_PTRACE CAP_BPF CAP_PERFMON CAP_NET_ADMIN
```

Then reload:

```bash
sudo systemctl daemon-reload && sudo systemctl restart tripwire-agent
```

---

## macOS Full Disk Access

macOS 14+ (Sonoma) enforces Full Disk Access for any process that reads files
outside the user's home directory.  Without it the agent silently receives
permission errors when kqueue watches are placed on `/etc`, `/private/etc`,
`/var`, or `/usr` paths.

**Grant access:**

1. Open **System Settings → Privacy & Security → Full Disk Access**.
2. Click the **+** button.
3. Navigate to `/usr/local/bin/` and select `tripwire`.
4. Restart the daemon: `sudo launchctl kickstart -k system/com.tripwire.agent`

**Verify:** After granting access, the audit log (`/var/log/tripwire/audit.log`)
should show `file_watch: registered` entries for each configured path.

---

## Logrotate integration (Linux)

The agent writes structured JSON logs to `journald` by default (captured via
`StandardOutput=journal`).  If you additionally configure a
`logging.file_path` in `config.yaml`, create a logrotate rule:

```
/var/log/tripwire/agent.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    postrotate
        systemctl reload tripwire-agent
    endscript
}
```

Install:

```bash
sudo cp /path/to/above/snippet /etc/logrotate.d/tripwire-agent
```

The `systemctl reload` sends `SIGHUP` to the agent (`ExecReload=/bin/kill -HUP
$MAINPID` in the unit file), which causes it to re-open the log file at the
new path.

---

## Upgrade procedure

### Linux

```bash
# 1. Build or obtain the new binary.
GOOS=linux GOARCH=amd64 go build -ldflags="-s -w" -o tripwire-linux-amd64 ./cmd/agent

# 2. Validate configuration against the new binary (optional but recommended).
sudo tripwire validate --config /etc/tripwire/config.yaml

# 3. Replace the binary.
sudo install -m 0755 -o root -g root ./tripwire-linux-amd64 /usr/local/bin/tripwire

# 4. Restart the service.
sudo systemctl restart tripwire-agent
```

### macOS

```bash
# 1. Build or obtain the new binary.
GOOS=darwin GOARCH=arm64 go build -ldflags="-s -w" -o tripwire-darwin-arm64 ./cmd/agent

# 2. Validate configuration.
sudo tripwire validate --config /etc/tripwire/config.yaml

# 3. Replace the binary.
sudo install -m 0755 -o root -g wheel ./tripwire-darwin-arm64 /usr/local/bin/tripwire
sudo xattr -d com.apple.quarantine /usr/local/bin/tripwire 2>/dev/null || true

# 4. Restart the daemon.
sudo launchctl kickstart -k system/com.tripwire.agent
```

---

## Uninstall

### Linux

```bash
sudo systemctl stop    tripwire-agent
sudo systemctl disable tripwire-agent
sudo rm /etc/systemd/system/tripwire-agent.service
sudo systemctl daemon-reload

# Remove binary, configuration, data, and logs (irreversible).
sudo rm /usr/local/bin/tripwire
sudo rm -rf /etc/tripwire /var/lib/tripwire /var/log/tripwire

# Remove the system user and group.
sudo userdel  tripwire
sudo groupdel tripwire
```

### macOS

```bash
sudo launchctl bootout system/com.tripwire.agent
sudo rm /Library/LaunchDaemons/com.tripwire.agent.plist

# Remove binary, configuration, data, and logs (irreversible).
sudo rm /usr/local/bin/tripwire
sudo rm -rf /etc/tripwire /var/lib/tripwire /var/log/tripwire
```
