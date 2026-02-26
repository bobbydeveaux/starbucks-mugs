package rest

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/tripwire/agent/internal/server/storage"
)

// mockStore is a test double for the Store interface.
type mockStore struct {
	alerts      []storage.Alert
	alertsErr   error
	hosts       []storage.Host
	hostsErr    error
	auditResult []storage.AuditEntry
	auditErr    error
}

func (m *mockStore) QueryAlerts(_ context.Context, _ storage.AlertQuery) ([]storage.Alert, error) {
	return m.alerts, m.alertsErr
}

func (m *mockStore) ListHosts(_ context.Context) ([]storage.Host, error) {
	return m.hosts, m.hostsErr
}

func (m *mockStore) QueryAuditEntries(_ context.Context, _ string, _, _ time.Time) ([]storage.AuditEntry, error) {
	return m.auditResult, m.auditErr
}

// newTestServer creates a Server backed by the mock store and returns its HTTP
// handler with JWT middleware disabled (pubKey = nil).
func newTestServer(ms *mockStore) http.Handler {
	srv := NewServer(ms)
	return NewRouter(srv, nil)
}

// ---- /healthz ---------------------------------------------------------------

func TestHandleHealthz_Returns200(t *testing.T) {
	h := newTestServer(&mockStore{})
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	var body map[string]string
	if err := json.NewDecoder(rec.Body).Decode(&body); err != nil {
		t.Fatalf("body is not valid JSON: %v", err)
	}
	if body["status"] != "ok" {
		t.Errorf("expected status=ok, got %q", body["status"])
	}
}

// ---- GET /api/v1/alerts -----------------------------------------------------

func TestHandleGetAlerts_MissingFrom_Returns400(t *testing.T) {
	h := newTestServer(&mockStore{})
	req := httptest.NewRequest(http.MethodGet, "/api/v1/alerts?to=2026-01-02T00:00:00Z", nil)
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", rec.Code)
	}
}

func TestHandleGetAlerts_MissingTo_Returns400(t *testing.T) {
	h := newTestServer(&mockStore{})
	req := httptest.NewRequest(http.MethodGet, "/api/v1/alerts?from=2026-01-01T00:00:00Z", nil)
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", rec.Code)
	}
}

func TestHandleGetAlerts_InvalidFromFormat_Returns400(t *testing.T) {
	h := newTestServer(&mockStore{})
	req := httptest.NewRequest(http.MethodGet, "/api/v1/alerts?from=not-a-time&to=2026-01-02T00:00:00Z", nil)
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", rec.Code)
	}
}

func TestHandleGetAlerts_ToNotAfterFrom_Returns400(t *testing.T) {
	h := newTestServer(&mockStore{})
	req := httptest.NewRequest(http.MethodGet,
		"/api/v1/alerts?from=2026-01-02T00:00:00Z&to=2026-01-01T00:00:00Z", nil)
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", rec.Code)
	}
}

func TestHandleGetAlerts_InvalidSeverity_Returns400(t *testing.T) {
	h := newTestServer(&mockStore{})
	req := httptest.NewRequest(http.MethodGet,
		"/api/v1/alerts?from=2026-01-01T00:00:00Z&to=2026-01-02T00:00:00Z&severity=UNKNOWN", nil)
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", rec.Code)
	}
}

func TestHandleGetAlerts_InvalidLimit_Returns400(t *testing.T) {
	h := newTestServer(&mockStore{})
	req := httptest.NewRequest(http.MethodGet,
		"/api/v1/alerts?from=2026-01-01T00:00:00Z&to=2026-01-02T00:00:00Z&limit=abc", nil)
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", rec.Code)
	}
}

func TestHandleGetAlerts_InvalidOffset_Returns400(t *testing.T) {
	h := newTestServer(&mockStore{})
	req := httptest.NewRequest(http.MethodGet,
		"/api/v1/alerts?from=2026-01-01T00:00:00Z&to=2026-01-02T00:00:00Z&offset=-1", nil)
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", rec.Code)
	}
}

func TestHandleGetAlerts_ValidRequest_Returns200WithArray(t *testing.T) {
	now := time.Now().UTC()
	ms := &mockStore{
		alerts: []storage.Alert{
			{
				AlertID:      "alert-1",
				HostID:       "host-1",
				Timestamp:    now,
				TripwireType: storage.TripwireTypeFile,
				RuleName:     "rule-a",
				Severity:     storage.SeverityCritical,
				ReceivedAt:   now,
			},
		},
	}
	h := newTestServer(ms)
	req := httptest.NewRequest(http.MethodGet,
		"/api/v1/alerts?from=2026-01-01T00:00:00Z&to=2026-02-01T00:00:00Z", nil)
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d; body: %s", rec.Code, rec.Body)
	}
	var alerts []storage.Alert
	if err := json.NewDecoder(rec.Body).Decode(&alerts); err != nil {
		t.Fatalf("cannot decode response: %v", err)
	}
	if len(alerts) != 1 {
		t.Fatalf("expected 1 alert, got %d", len(alerts))
	}
	if alerts[0].AlertID != "alert-1" {
		t.Errorf("unexpected alert ID: %s", alerts[0].AlertID)
	}
}

func TestHandleGetAlerts_EmptyResult_ReturnsEmptyArray(t *testing.T) {
	h := newTestServer(&mockStore{alerts: nil})
	req := httptest.NewRequest(http.MethodGet,
		"/api/v1/alerts?from=2026-01-01T00:00:00Z&to=2026-02-01T00:00:00Z", nil)
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	var alerts []storage.Alert
	if err := json.NewDecoder(rec.Body).Decode(&alerts); err != nil {
		t.Fatalf("cannot decode response: %v", err)
	}
	if len(alerts) != 0 {
		t.Errorf("expected empty array, got %v", alerts)
	}
}

func TestHandleGetAlerts_WithSeverityFilter_Returns200(t *testing.T) {
	now := time.Now().UTC()
	ms := &mockStore{
		alerts: []storage.Alert{
			{AlertID: "a1", Severity: storage.SeverityWarn, ReceivedAt: now, Timestamp: now},
		},
	}
	h := newTestServer(ms)
	req := httptest.NewRequest(http.MethodGet,
		"/api/v1/alerts?from=2026-01-01T00:00:00Z&to=2026-02-01T00:00:00Z&severity=WARN", nil)
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d; body: %s", rec.Code, rec.Body)
	}
}

func TestHandleGetAlerts_WithHostID_Returns200(t *testing.T) {
	now := time.Now().UTC()
	ms := &mockStore{
		alerts: []storage.Alert{
			{AlertID: "a1", HostID: "host-42", ReceivedAt: now, Timestamp: now},
		},
	}
	h := newTestServer(ms)
	req := httptest.NewRequest(http.MethodGet,
		"/api/v1/alerts?from=2026-01-01T00:00:00Z&to=2026-02-01T00:00:00Z&host_id=host-42", nil)
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d; body: %s", rec.Code, rec.Body)
	}
}

// ---- GET /api/v1/hosts ------------------------------------------------------

func TestHandleGetHosts_Returns200WithArray(t *testing.T) {
	ms := &mockStore{
		hosts: []storage.Host{
			{HostID: "h1", Hostname: "agent-01", Status: storage.HostStatusOnline},
			{HostID: "h2", Hostname: "agent-02", Status: storage.HostStatusOffline},
		},
	}
	h := newTestServer(ms)
	req := httptest.NewRequest(http.MethodGet, "/api/v1/hosts", nil)
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	var hosts []storage.Host
	if err := json.NewDecoder(rec.Body).Decode(&hosts); err != nil {
		t.Fatalf("cannot decode response: %v", err)
	}
	if len(hosts) != 2 {
		t.Fatalf("expected 2 hosts, got %d", len(hosts))
	}
}

func TestHandleGetHosts_EmptyResult_ReturnsEmptyArray(t *testing.T) {
	h := newTestServer(&mockStore{hosts: nil})
	req := httptest.NewRequest(http.MethodGet, "/api/v1/hosts", nil)
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	var hosts []storage.Host
	if err := json.NewDecoder(rec.Body).Decode(&hosts); err != nil {
		t.Fatalf("cannot decode response: %v", err)
	}
	if len(hosts) != 0 {
		t.Errorf("expected empty array, got %v", hosts)
	}
}

// ---- GET /api/v1/audit ------------------------------------------------------

func TestHandleGetAudit_MissingHostID_Returns400(t *testing.T) {
	h := newTestServer(&mockStore{})
	req := httptest.NewRequest(http.MethodGet,
		"/api/v1/audit?from=2026-01-01T00:00:00Z&to=2026-02-01T00:00:00Z", nil)
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", rec.Code)
	}
}

func TestHandleGetAudit_MissingFrom_Returns400(t *testing.T) {
	h := newTestServer(&mockStore{})
	req := httptest.NewRequest(http.MethodGet,
		"/api/v1/audit?host_id=host-1&to=2026-02-01T00:00:00Z", nil)
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", rec.Code)
	}
}

func TestHandleGetAudit_InvalidFrom_Returns400(t *testing.T) {
	h := newTestServer(&mockStore{})
	req := httptest.NewRequest(http.MethodGet,
		"/api/v1/audit?host_id=host-1&from=bad&to=2026-02-01T00:00:00Z", nil)
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", rec.Code)
	}
}

func TestHandleGetAudit_ToNotAfterFrom_Returns400(t *testing.T) {
	h := newTestServer(&mockStore{})
	req := httptest.NewRequest(http.MethodGet,
		"/api/v1/audit?host_id=host-1&from=2026-02-01T00:00:00Z&to=2026-01-01T00:00:00Z", nil)
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusBadRequest {
		t.Fatalf("expected 400, got %d", rec.Code)
	}
}

func TestHandleGetAudit_ValidRequest_Returns200WithArray(t *testing.T) {
	now := time.Now().UTC()
	ms := &mockStore{
		auditResult: []storage.AuditEntry{
			{
				EntryID:     "e1",
				HostID:      "host-1",
				SequenceNum: 1,
				EventHash:   "abc",
				PrevHash:    "000",
				CreatedAt:   now,
			},
		},
	}
	h := newTestServer(ms)
	req := httptest.NewRequest(http.MethodGet,
		"/api/v1/audit?host_id=host-1&from=2026-01-01T00:00:00Z&to=2026-02-01T00:00:00Z", nil)
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d; body: %s", rec.Code, rec.Body)
	}
	var entries []storage.AuditEntry
	if err := json.NewDecoder(rec.Body).Decode(&entries); err != nil {
		t.Fatalf("cannot decode response: %v", err)
	}
	if len(entries) != 1 {
		t.Fatalf("expected 1 entry, got %d", len(entries))
	}
	if entries[0].EntryID != "e1" {
		t.Errorf("unexpected entry ID: %s", entries[0].EntryID)
	}
}

func TestHandleGetAudit_EmptyResult_ReturnsEmptyArray(t *testing.T) {
	h := newTestServer(&mockStore{auditResult: nil})
	req := httptest.NewRequest(http.MethodGet,
		"/api/v1/audit?host_id=host-1&from=2026-01-01T00:00:00Z&to=2026-02-01T00:00:00Z", nil)
	rec := httptest.NewRecorder()

	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	var entries []storage.AuditEntry
	if err := json.NewDecoder(rec.Body).Decode(&entries); err != nil {
		t.Fatalf("cannot decode response: %v", err)
	}
	if len(entries) != 0 {
		t.Errorf("expected empty array, got %v", entries)
	}
}
