# TripWire Agent

The TripWire agent is a self-contained Go binary that runs on monitored hosts,
detects tripwire events (file access, network connections, process execution),
and forwards alerts to the central dashboard.

## Repository layout

```
agent/
├── cmd/tripwire/          # main entry point
│   └── main.go
├── internal/
│   └── config/            # YAML config parsing & validation  ← Sprint 1
│       ├── config.go
│       └── config_test.go
├── config.example.yaml    # annotated configuration reference
├── go.mod
└── go.sum
```

## Building

```bash
go build -o tripwire ./cmd/tripwire
```

Cross-compile for Linux amd64:

```bash
GOOS=linux GOARCH=amd64 go build -ldflags="-s -w" -o tripwire-linux-amd64 ./cmd/tripwire
```

Cross-compile for macOS arm64 (Apple Silicon):

```bash
GOOS=darwin GOARCH=arm64 go build -ldflags="-s -w" -o tripwire-darwin-arm64 ./cmd/tripwire
```

## Usage

```bash
# Validate configuration without starting the agent
tripwire validate --config /etc/tripwire/config.yaml

# Start the agent
tripwire start --config /etc/tripwire/config.yaml

# Print the build version
tripwire version
```

## Configuration

Copy `config.example.yaml` to `/etc/tripwire/config.yaml` and edit it for
your environment.  Full field-level documentation is in
`docs/concepts/tripwire-cybersecurity-tool/agent-configuration.md`.

## Running as a system service

The agent ships with ready-to-use service files for the two major platforms.

### Linux — systemd

```bash
# Install (creates the tripwire user, directories, unit file, and starts the service).
sudo ./deployments/scripts/install-agent-linux.sh ./tripwire-linux-amd64

# Day-to-day operations
sudo systemctl status  tripwire-agent
sudo systemctl restart tripwire-agent
sudo journalctl -u tripwire-agent -f
```

Unit file: `deployments/systemd/tripwire-agent.service`

### macOS — launchd

```bash
# Install (creates directories, copies binary, loads the LaunchDaemon).
sudo ./deployments/scripts/install-agent-macos.sh ./tripwire-darwin-arm64

# Day-to-day operations
sudo launchctl list com.tripwire.agent
sudo launchctl kickstart -k system/com.tripwire.agent   # restart
tail -f /var/log/tripwire/agent.log
```

Plist: `deployments/launchd/com.tripwire.agent.plist`

For the complete deployment guide (capability requirements, certificate setup,
logrotate, upgrade and uninstall procedures) see
`docs/concepts/tripwire-cybersecurity-tool/agent-deployment.md`.

## Running the tests

```bash
go test ./...
```

## Sprint status

| Sprint | Features | Status |
|---|---|---|
| 1 | Agent Core & Configuration — **config parsing/validation** | ✓ implemented |
| 1 | PostgreSQL Schema & Storage Layer | ✓ implemented |
| 1 | mTLS PKI & Certificate Management | ✓ implemented |
| 2 | File watcher (inotify/kqueue) | ✓ implemented |
| 3 | Process watcher (eBPF/ptrace/kqueue) | ✓ implemented |
| 3 | gRPC alert transport + WebSocket fan-out | ✓ implemented |
| 4 | Agent lifecycle unit files (systemd + launchd) | ✓ implemented |
