//go:build integration

// Run with:
//
//	go test -tags integration -v ./internal/server/storage/...
//
// Requires Docker (for testcontainers-go) and a reachable Docker socket.
package storage_test

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"runtime"
	"testing"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/testcontainers/testcontainers-go"
	tcpostgres "github.com/testcontainers/testcontainers-go/modules/postgres"
	"github.com/testcontainers/testcontainers-go/wait"

	"github.com/tripwire/tripwire-cybersecurity-tool/internal/server/storage"
)

// migrationsDir returns the absolute path to db/migrations relative to this
// test file, so the tests work regardless of the working directory.
func migrationsDir(t *testing.T) string {
	t.Helper()
	_, thisFile, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("runtime.Caller failed")
	}
	// thisFile is internal/server/storage/postgres_test.go
	return filepath.Join(filepath.Dir(thisFile), "..", "..", "..", "db", "migrations")
}

// setupDB starts a PostgreSQL container, applies all four migration files, and
// returns a Store and a raw pgxpool for schema-level assertions.
func setupDB(t *testing.T) (*storage.Store, *pgxpool.Pool, func()) {
	t.Helper()
	ctx := context.Background()

	pgContainer, err := tcpostgres.RunContainer(ctx,
		testcontainers.WithImage("postgres:15-alpine"),
		tcpostgres.WithDatabase("tripwire_test"),
		tcpostgres.WithUsername("tripwire"),
		tcpostgres.WithPassword("secret"),
		testcontainers.WithWaitStrategy(
			wait.ForLog("database system is ready to accept connections").
				WithOccurrence(2).
				WithStartupTimeout(60*time.Second),
		),
	)
	if err != nil {
		t.Fatalf("start postgres container: %v", err)
	}

	connStr, err := pgContainer.ConnectionString(ctx, "sslmode=disable")
	if err != nil {
		_ = pgContainer.Terminate(ctx)
		t.Fatalf("get connection string: %v", err)
	}

	// Apply migrations in order.
	rawPool, err := pgxpool.New(ctx, connStr)
	if err != nil {
		_ = pgContainer.Terminate(ctx)
		t.Fatalf("connect for migrations: %v", err)
	}
	applyMigrations(t, ctx, rawPool, migrationsDir(t))

	store, err := storage.New(ctx, connStr, 10, 50*time.Millisecond)
	if err != nil {
		rawPool.Close()
		_ = pgContainer.Terminate(ctx)
		t.Fatalf("storage.New: %v", err)
	}

	cleanup := func() {
		store.Close(ctx)
		rawPool.Close()
		_ = pgContainer.Terminate(ctx)
	}
	return store, rawPool, cleanup
}

// applyMigrations executes migration SQL files 001–004 in order.
func applyMigrations(t *testing.T, ctx context.Context, pool *pgxpool.Pool, dir string) {
	t.Helper()
	files := []string{
		"001_hosts.sql",
		"002_alerts.sql",
		"003_rules.sql",
		"004_audit.sql",
	}
	for _, f := range files {
		path := filepath.Join(dir, f)
		sql, err := os.ReadFile(path)
		if err != nil {
			t.Fatalf("read migration %s: %v", f, err)
		}
		if _, err := pool.Exec(ctx, string(sql)); err != nil {
			t.Fatalf("apply migration %s: %v", f, err)
		}
	}
}

// testHost returns a Host struct suitable for use in tests.
func testHost(suffix string) storage.Host {
	now := time.Now().UTC().Truncate(time.Millisecond)
	return storage.Host{
		HostID:       fmt.Sprintf("00000000-0000-0000-0000-%012s", suffix),
		Hostname:     "test-host-" + suffix,
		IPAddress:    "10.0.0.1",
		Platform:     "linux",
		AgentVersion: "0.1.0",
		LastSeen:     &now,
		Status:       storage.HostStatusOnline,
	}
}

// ── Host CRUD ─────────────────────────────────────────────────────────────────

func TestHostUpsertAndGet(t *testing.T) {
	store, _, cleanup := setupDB(t)
	defer cleanup()
	ctx := context.Background()

	h := testHost("000001000001")
	if err := store.UpsertHost(ctx, h); err != nil {
		t.Fatalf("UpsertHost: %v", err)
	}

	got, err := store.GetHost(ctx, h.HostID)
	if err != nil {
		t.Fatalf("GetHost: %v", err)
	}
	if got.Hostname != h.Hostname {
		t.Errorf("hostname: want %q, got %q", h.Hostname, got.Hostname)
	}
	if got.Platform != h.Platform {
		t.Errorf("platform: want %q, got %q", h.Platform, got.Platform)
	}
	if got.Status != h.Status {
		t.Errorf("status: want %q, got %q", h.Status, got.Status)
	}
	if got.IPAddress != h.IPAddress {
		t.Errorf("ip_address: want %q, got %q", h.IPAddress, got.IPAddress)
	}
}

func TestHostUpsertUpdatesExisting(t *testing.T) {
	store, _, cleanup := setupDB(t)
	defer cleanup()
	ctx := context.Background()

	h := testHost("000002000002")
	if err := store.UpsertHost(ctx, h); err != nil {
		t.Fatalf("initial UpsertHost: %v", err)
	}

	// Update agent version and status via upsert on the same hostname.
	h.AgentVersion = "0.2.0"
	h.Status = storage.HostStatusDegraded
	if err := store.UpsertHost(ctx, h); err != nil {
		t.Fatalf("update UpsertHost: %v", err)
	}

	got, err := store.GetHost(ctx, h.HostID)
	if err != nil {
		t.Fatalf("GetHost after update: %v", err)
	}
	if got.AgentVersion != "0.2.0" {
		t.Errorf("agent_version: want 0.2.0, got %q", got.AgentVersion)
	}
	if got.Status != storage.HostStatusDegraded {
		t.Errorf("status: want DEGRADED, got %q", got.Status)
	}
}

func TestListHosts(t *testing.T) {
	store, _, cleanup := setupDB(t)
	defer cleanup()
	ctx := context.Background()

	h1 := testHost("000003000003")
	h2 := testHost("000004000004")
	for _, h := range []storage.Host{h1, h2} {
		if err := store.UpsertHost(ctx, h); err != nil {
			t.Fatalf("UpsertHost: %v", err)
		}
	}

	hosts, err := store.ListHosts(ctx)
	if err != nil {
		t.Fatalf("ListHosts: %v", err)
	}
	if len(hosts) < 2 {
		t.Errorf("want >= 2 hosts, got %d", len(hosts))
	}
}

// ── Alert batch insert & query ─────────────────────────────────────────────────

// testAlert builds an Alert for the given hostID received in 2026-02 (within
// the example child partition created by migration 002).
func testAlert(hostID, alertID string, severity storage.Severity, eventDetail json.RawMessage) storage.Alert {
	ts := time.Date(2026, 2, 15, 10, 0, 0, 0, time.UTC)
	return storage.Alert{
		AlertID:      alertID,
		HostID:       hostID,
		Timestamp:    ts,
		TripwireType: storage.TripwireTypeFile,
		RuleName:     "etc-passwd-watch",
		EventDetail:  eventDetail,
		Severity:     severity,
		ReceivedAt:   ts,
	}
}

func TestBatchInsertAlerts_FlushOnSize(t *testing.T) {
	store, _, cleanup := setupDB(t)
	defer cleanup()
	ctx := context.Background()

	h := testHost("000005000005")
	if err := store.UpsertHost(ctx, h); err != nil {
		t.Fatalf("UpsertHost: %v", err)
	}

	detail := json.RawMessage(`{"path":"/etc/passwd","pid":1234,"user":"root"}`)
	// batchSize is 10 in setupDB; insert 10 alerts to trigger a size-based flush.
	for i := 0; i < 10; i++ {
		alertID := fmt.Sprintf("aaaaaaaa-0000-0000-0000-%012d", i)
		a := testAlert(h.HostID, alertID, storage.SeverityCritical, detail)
		if err := store.BatchInsertAlerts(ctx, a); err != nil {
			t.Fatalf("BatchInsertAlerts[%d]: %v", i, err)
		}
	}

	from := time.Date(2026, 2, 1, 0, 0, 0, 0, time.UTC)
	to := time.Date(2026, 3, 1, 0, 0, 0, 0, time.UTC)
	alerts, err := store.QueryAlerts(ctx, storage.AlertQuery{
		HostID: h.HostID,
		From:   from,
		To:     to,
		Limit:  100,
	})
	if err != nil {
		t.Fatalf("QueryAlerts: %v", err)
	}
	if len(alerts) != 10 {
		t.Errorf("want 10 alerts, got %d", len(alerts))
	}
}

func TestBatchInsertAlerts_FlushOnInterval(t *testing.T) {
	store, _, cleanup := setupDB(t)
	defer cleanup()
	ctx := context.Background()

	h := testHost("000006000006")
	if err := store.UpsertHost(ctx, h); err != nil {
		t.Fatalf("UpsertHost: %v", err)
	}

	detail := json.RawMessage(`{"port":2222,"src_ip":"192.168.1.100","proto":"TCP"}`)
	a := testAlert(h.HostID, "bbbbbbbb-0000-0000-0000-000000000001",
		storage.SeverityWarn, detail)
	a.TripwireType = storage.TripwireTypeNetwork

	// Only 1 alert — the batchSize threshold (10) is not reached.
	if err := store.BatchInsertAlerts(ctx, a); err != nil {
		t.Fatalf("BatchInsertAlerts: %v", err)
	}

	// Wait for the 50 ms flush interval to fire (give 200 ms headroom).
	time.Sleep(200 * time.Millisecond)

	from := time.Date(2026, 2, 1, 0, 0, 0, 0, time.UTC)
	to := time.Date(2026, 3, 1, 0, 0, 0, 0, time.UTC)
	alerts, err := store.QueryAlerts(ctx, storage.AlertQuery{
		HostID: h.HostID,
		From:   from,
		To:     to,
		Limit:  10,
	})
	if err != nil {
		t.Fatalf("QueryAlerts: %v", err)
	}
	if len(alerts) != 1 {
		t.Errorf("want 1 alert, got %d", len(alerts))
	}
}

func TestQueryAlerts_SeverityFilter(t *testing.T) {
	store, _, cleanup := setupDB(t)
	defer cleanup()
	ctx := context.Background()

	h := testHost("000007000007")
	if err := store.UpsertHost(ctx, h); err != nil {
		t.Fatalf("UpsertHost: %v", err)
	}

	detail := json.RawMessage(`{"path":"/etc/shadow"}`)
	alerts := []storage.Alert{
		testAlert(h.HostID, "cccccccc-0000-0000-0000-000000000001", storage.SeverityInfo, detail),
		testAlert(h.HostID, "cccccccc-0000-0000-0000-000000000002", storage.SeverityWarn, detail),
		testAlert(h.HostID, "cccccccc-0000-0000-0000-000000000003", storage.SeverityCritical, detail),
	}
	for _, a := range alerts {
		if err := store.BatchInsertAlerts(ctx, a); err != nil {
			t.Fatalf("BatchInsertAlerts: %v", err)
		}
	}
	if err := store.Flush(ctx); err != nil {
		t.Fatalf("Flush: %v", err)
	}

	from := time.Date(2026, 2, 1, 0, 0, 0, 0, time.UTC)
	to := time.Date(2026, 3, 1, 0, 0, 0, 0, time.UTC)

	sev := storage.SeverityWarn
	got, err := store.QueryAlerts(ctx, storage.AlertQuery{
		HostID:   h.HostID,
		Severity: &sev,
		From:     from,
		To:       to,
		Limit:    100,
	})
	if err != nil {
		t.Fatalf("QueryAlerts(WARN): %v", err)
	}
	if len(got) != 1 {
		t.Errorf("want 1 WARN alert, got %d", len(got))
	}
	if len(got) > 0 && got[0].Severity != storage.SeverityWarn {
		t.Errorf("severity: want WARN, got %q", got[0].Severity)
	}
}

func TestQueryAlerts_EventDetailRoundtrip(t *testing.T) {
	store, _, cleanup := setupDB(t)
	defer cleanup()
	ctx := context.Background()

	h := testHost("000008000008")
	if err := store.UpsertHost(ctx, h); err != nil {
		t.Fatalf("UpsertHost: %v", err)
	}

	detail := json.RawMessage(`{"path":"/etc/passwd","pid":9999,"user":"attacker","extra":{"nested":true}}`)
	a := testAlert(h.HostID, "dddddddd-0000-0000-0000-000000000001", storage.SeverityCritical, detail)
	if err := store.BatchInsertAlerts(ctx, a); err != nil {
		t.Fatalf("BatchInsertAlerts: %v", err)
	}
	if err := store.Flush(ctx); err != nil {
		t.Fatalf("Flush: %v", err)
	}

	from := time.Date(2026, 2, 1, 0, 0, 0, 0, time.UTC)
	to := time.Date(2026, 3, 1, 0, 0, 0, 0, time.UTC)
	got, err := store.QueryAlerts(ctx, storage.AlertQuery{
		HostID: h.HostID,
		From:   from,
		To:     to,
		Limit:  1,
	})
	if err != nil {
		t.Fatalf("QueryAlerts: %v", err)
	}
	if len(got) != 1 {
		t.Fatalf("want 1 alert, got %d", len(got))
	}

	// Verify event_detail round-trips without data loss.
	var origMap, gotMap map[string]any
	if err := json.Unmarshal(detail, &origMap); err != nil {
		t.Fatalf("unmarshal original: %v", err)
	}
	if err := json.Unmarshal(got[0].EventDetail, &gotMap); err != nil {
		t.Fatalf("unmarshal retrieved: %v", err)
	}
	if fmt.Sprintf("%v", origMap) != fmt.Sprintf("%v", gotMap) {
		t.Errorf("event_detail mismatch:\nwant %v\n got %v", origMap, gotMap)
	}
}

// ── TripwireRule CRUD ──────────────────────────────────────────────────────────

func TestRuleCRUD(t *testing.T) {
	store, _, cleanup := setupDB(t)
	defer cleanup()
	ctx := context.Background()

	h := testHost("000009000009")
	if err := store.UpsertHost(ctx, h); err != nil {
		t.Fatalf("UpsertHost: %v", err)
	}

	r := storage.TripwireRule{
		RuleID:   "eeeeeeee-0000-0000-0000-000000000001",
		HostID:   h.HostID,
		RuleType: storage.TripwireTypeFile,
		Target:   "/etc/passwd",
		Severity: storage.SeverityCritical,
		Enabled:  true,
	}

	if err := store.CreateRule(ctx, r); err != nil {
		t.Fatalf("CreateRule: %v", err)
	}

	got, err := store.GetRule(ctx, r.RuleID)
	if err != nil {
		t.Fatalf("GetRule: %v", err)
	}
	if got.Target != r.Target {
		t.Errorf("target: want %q, got %q", r.Target, got.Target)
	}
	if got.Severity != r.Severity {
		t.Errorf("severity: want %q, got %q", r.Severity, got.Severity)
	}

	// Update
	r.Enabled = false
	r.Severity = storage.SeverityWarn
	if err := store.UpdateRule(ctx, r); err != nil {
		t.Fatalf("UpdateRule: %v", err)
	}
	updated, err := store.GetRule(ctx, r.RuleID)
	if err != nil {
		t.Fatalf("GetRule after update: %v", err)
	}
	if updated.Enabled {
		t.Error("rule should be disabled after update")
	}
	if updated.Severity != storage.SeverityWarn {
		t.Errorf("severity after update: want WARN, got %q", updated.Severity)
	}

	// Delete
	if err := store.DeleteRule(ctx, r.RuleID); err != nil {
		t.Fatalf("DeleteRule: %v", err)
	}
	if _, err := store.GetRule(ctx, r.RuleID); err == nil {
		t.Error("expected error after deleting rule, got nil")
	}
}

func TestListRules_GlobalAndHostScoped(t *testing.T) {
	store, _, cleanup := setupDB(t)
	defer cleanup()
	ctx := context.Background()

	h := testHost("000010000010")
	if err := store.UpsertHost(ctx, h); err != nil {
		t.Fatalf("UpsertHost: %v", err)
	}

	globalRule := storage.TripwireRule{
		RuleID:   "ffffffff-0000-0000-0000-000000000001",
		HostID:   "", // global
		RuleType: storage.TripwireTypeNetwork,
		Target:   "22",
		Severity: storage.SeverityCritical,
		Enabled:  true,
	}
	hostRule := storage.TripwireRule{
		RuleID:   "ffffffff-0000-0000-0000-000000000002",
		HostID:   h.HostID,
		RuleType: storage.TripwireTypeFile,
		Target:   "/tmp",
		Severity: storage.SeverityInfo,
		Enabled:  true,
	}
	for _, r := range []storage.TripwireRule{globalRule, hostRule} {
		if err := store.CreateRule(ctx, r); err != nil {
			t.Fatalf("CreateRule: %v", err)
		}
	}

	// ListRules with hostID returns both the host-specific rule and the global one.
	rules, err := store.ListRules(ctx, h.HostID)
	if err != nil {
		t.Fatalf("ListRules: %v", err)
	}
	if len(rules) != 2 {
		t.Errorf("want 2 rules, got %d", len(rules))
	}
}

// ── AuditEntry ─────────────────────────────────────────────────────────────────

func TestAuditEntryInsertAndQuery(t *testing.T) {
	store, _, cleanup := setupDB(t)
	defer cleanup()
	ctx := context.Background()

	h := testHost("000011000011")
	if err := store.UpsertHost(ctx, h); err != nil {
		t.Fatalf("UpsertHost: %v", err)
	}

	now := time.Now().UTC().Truncate(time.Millisecond)
	e1 := storage.AuditEntry{
		EntryID:     "a0000000-0000-0000-0000-000000000001",
		HostID:      h.HostID,
		SequenceNum: 1,
		PrevHash:    "0000000000000000000000000000000000000000000000000000000000000000",
		EventHash:   "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
		Payload:     json.RawMessage(`{"event":"login","user":"root"}`),
		CreatedAt:   now,
	}
	e2 := storage.AuditEntry{
		EntryID:     "a0000000-0000-0000-0000-000000000002",
		HostID:      h.HostID,
		SequenceNum: 2,
		PrevHash:    e1.EventHash,
		EventHash:   "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
		Payload:     json.RawMessage(`{"event":"file_read","path":"/etc/passwd"}`),
		CreatedAt:   now.Add(time.Second),
	}
	for _, e := range []storage.AuditEntry{e1, e2} {
		if err := store.InsertAuditEntry(ctx, e); err != nil {
			t.Fatalf("InsertAuditEntry: %v", err)
		}
	}

	from := now.Add(-time.Minute)
	to := now.Add(time.Minute)
	entries, err := store.QueryAuditEntries(ctx, h.HostID, from, to)
	if err != nil {
		t.Fatalf("QueryAuditEntries: %v", err)
	}
	if len(entries) != 2 {
		t.Fatalf("want 2 audit entries, got %d", len(entries))
	}

	// Verify ordering and chain integrity.
	if entries[0].SequenceNum != 1 || entries[1].SequenceNum != 2 {
		t.Errorf("sequence order wrong: got %d, %d", entries[0].SequenceNum, entries[1].SequenceNum)
	}
	if entries[1].PrevHash != entries[0].EventHash {
		t.Errorf("hash chain broken: entry[1].PrevHash=%q, entry[0].EventHash=%q",
			entries[1].PrevHash, entries[0].EventHash)
	}

	// Verify payload round-trips without data loss.
	var gotPayload map[string]any
	if err := json.Unmarshal(entries[0].Payload, &gotPayload); err != nil {
		t.Fatalf("unmarshal payload: %v", err)
	}
	if gotPayload["event"] != "login" {
		t.Errorf("payload event: want 'login', got %v", gotPayload["event"])
	}
}
