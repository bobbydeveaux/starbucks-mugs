# CI/CD — GitHub Actions Build Matrix

## Overview

The `.github/workflows/build.yml` workflow compiles statically-linked TripWire
agent binaries for all supported platforms automatically on every push to `main`
and on every semver release tag.

## Supported Platforms

| `GOOS`   | `GOARCH` | Binary name                   |
|----------|----------|-------------------------------|
| `linux`  | `amd64`  | `tripwire-linux-amd64`        |
| `linux`  | `arm64`  | `tripwire-linux-arm64`        |
| `darwin` | `amd64`  | `tripwire-darwin-amd64`       |
| `darwin` | `arm64`  | `tripwire-darwin-arm64`       |

All four targets are compiled from a single `ubuntu-latest` runner using Go's
built-in cross-compilation.  `CGO_ENABLED=0` ensures no C runtime dependency,
producing fully self-contained static binaries.

## Workflow Triggers

| Event | Jobs run | Outcome |
|---|---|---|
| `push` to `main` | `build` | Binaries uploaded as workflow artifacts (7-day retention) |
| `push` of `v*.*.*` tag | `build` + `release` | GitHub Release created with all four binaries attached |

## Build Job

Each matrix combination runs in parallel (`fail-fast: false`).  Steps:

1. **Checkout** — `actions/checkout@v4`
2. **Setup Go** — version from `agent/go.mod`; `go.sum` cache keyed to `agent/go.sum`
3. **Determine version string** — tag name for release builds; short SHA for branch builds
4. **Build static binary** — `CGO_ENABLED=0 go build -ldflags="-s -w -X main.Version=<ver>"` from the `agent/` subdirectory
5. **Verify static linking** (Linux only) — asserts the ELF binary has no dynamic interpreter
6. **Upload artifact** — stored as `tripwire-<goos>-<goarch>` for 7 days

## Release Job

Runs only when the triggering ref is a `v*.*.*` tag (i.e. `startsWith(github.ref, 'refs/tags/')`).

1. Downloads all four artifacts using `actions/download-artifact@v4` with `merge-multiple: true`
2. Publishes a GitHub Release via `softprops/action-gh-release@v2` with auto-generated release notes

## Static-Linking Guarantee

`CGO_ENABLED=0` disables cgo entirely.  The agent already uses `modernc.org/sqlite`
(pure-Go SQLite) so there is no C library dependency anywhere in the build graph.
Linux binaries will satisfy:

```bash
ldd tripwire-linux-amd64
# → not a dynamic executable
```

## Concurrency

Concurrent pushes to `main` cancel the previous in-progress build (saves minutes
of runner time).  Release tag builds are never cancelled (`cancel-in-progress`
is `false` for `refs/tags/*` refs) so no release is partially uploaded.

## Embedding the Version

The build injects the version string into the binary at link time:

```
-X main.Version=<version>
```

Consumers can query the embedded version with:

```bash
./tripwire-linux-amd64 version
```

## Adding a New Platform

Add a new entry to the `matrix.include` list in `.github/workflows/build.yml`:

```yaml
- goos: windows
  goarch: amd64
```

No other changes are required; the artifact upload and release steps are
parameterised on `matrix.goos` / `matrix.goarch`.
