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