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

## Running the tests

```bash
go test ./...
```

## Sprint status

| Sprint | Features | Status |
|---|---|---|
| 1 | Agent Core & Configuration — **config parsing/validation** | ✓ implemented |
| 1 | PostgreSQL Schema & Storage Layer | planned |
| 1 | mTLS PKI & Certificate Management | planned |
| 2–5 | Watchers, gRPC transport, dashboard UI | planned |
