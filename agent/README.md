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

Cross-compile for a specific platform (static binary, no CGo):

```bash
GOOS=linux   GOARCH=amd64 CGO_ENABLED=0 go build -ldflags="-s -w" -o tripwire-linux-amd64   ./cmd/tripwire
GOOS=linux   GOARCH=arm64 CGO_ENABLED=0 go build -ldflags="-s -w" -o tripwire-linux-arm64   ./cmd/tripwire
GOOS=darwin  GOARCH=amd64 CGO_ENABLED=0 go build -ldflags="-s -w" -o tripwire-darwin-amd64  ./cmd/tripwire
GOOS=darwin  GOARCH=arm64 CGO_ENABLED=0 go build -ldflags="-s -w" -o tripwire-darwin-arm64  ./cmd/tripwire
```

Set the embedded version string at build time:

```bash
CGO_ENABLED=0 go build -ldflags="-s -w -X main.Version=v1.2.3" -o tripwire ./cmd/tripwire
```

## CI/CD — GitHub Actions

The workflow at `.github/workflows/build.yml` runs automatically:

| Trigger | Behaviour |
|---|---|
| Push to `main` | Compiles all four binaries and uploads them as workflow artifacts (retained for 7 days) |
| Push of `v*.*.*` tag | Same build, then creates a GitHub Release with all four binaries attached |

Binaries are compiled with `CGO_ENABLED=0` and `-s -w` so every Linux target is
statically linked (`ldd` reports *not a dynamic executable*).

Download the latest release binary for your platform from the
[GitHub Releases](../../releases) page.

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
| 4 | **GitHub Actions build matrix for cross-platform binaries** | ✓ implemented |
