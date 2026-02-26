package rest

import (
	"encoding/json"
	"net/http"
	"strconv"
	"time"

	"github.com/tripwire/agent/internal/server/storage"
)

// writeError writes an HTTP error response with a JSON body containing an
// "error" field. It is a thin wrapper around writeJSONError for use in handler
// functions.
func writeError(w http.ResponseWriter, code int, msg string) {
	writeJSONError(w, code, msg)
}

// Server holds the dependencies needed by the REST handlers.
type Server struct {
	store Store
}

// NewServer creates a new Server with the provided storage layer.
func NewServer(store Store) *Server {
	return &Server{store: store}
}

// handleHealthz responds to GET /healthz.
//
// This endpoint does not require authentication and returns HTTP 200 with a
// simple JSON body so load balancers and orchestrators can verify liveness.
func (s *Server) handleHealthz(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
}

// handleGetAlerts responds to GET /api/v1/alerts.
//
// Supported query parameters:
//
//	host_id   – exact host UUID filter (optional)
//	severity  – one of INFO, WARN, CRITICAL (optional)
//	type      – one of FILE, NETWORK, PROCESS (optional, not yet persisted to DB filter)
//	from      – RFC3339 start of the received_at window (required)
//	to        – RFC3339 end of the received_at window (required)
//	limit     – maximum number of results (default 100, max 1000)
//	offset    – pagination offset (default 0)
//
// Returns HTTP 400 when required parameters are missing or malformed.
// Returns HTTP 200 with a JSON array of Alert objects on success.
func (s *Server) handleGetAlerts(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()

	fromStr := q.Get("from")
	toStr := q.Get("to")
	if fromStr == "" || toStr == "" {
		writeError(w, http.StatusBadRequest, "query parameters 'from' and 'to' are required (RFC3339)")
		return
	}

	from, err := time.Parse(time.RFC3339, fromStr)
	if err != nil {
		writeError(w, http.StatusBadRequest, "'from' must be a valid RFC3339 timestamp")
		return
	}
	to, err := time.Parse(time.RFC3339, toStr)
	if err != nil {
		writeError(w, http.StatusBadRequest, "'to' must be a valid RFC3339 timestamp")
		return
	}
	if !to.After(from) {
		writeError(w, http.StatusBadRequest, "'to' must be after 'from'")
		return
	}

	aq := storage.AlertQuery{
		From: from,
		To:   to,
	}

	if hostID := q.Get("host_id"); hostID != "" {
		aq.HostID = hostID
	}

	if sev := q.Get("severity"); sev != "" {
		switch storage.Severity(sev) {
		case storage.SeverityInfo, storage.SeverityWarn, storage.SeverityCritical:
			s := storage.Severity(sev)
			aq.Severity = &s
		default:
			writeError(w, http.StatusBadRequest, "'severity' must be one of INFO, WARN, CRITICAL")
			return
		}
	}

	if limitStr := q.Get("limit"); limitStr != "" {
		limit, err := strconv.Atoi(limitStr)
		if err != nil || limit <= 0 {
			writeError(w, http.StatusBadRequest, "'limit' must be a positive integer")
			return
		}
		if limit > 1000 {
			limit = 1000
		}
		aq.Limit = limit
	}

	if offsetStr := q.Get("offset"); offsetStr != "" {
		offset, err := strconv.Atoi(offsetStr)
		if err != nil || offset < 0 {
			writeError(w, http.StatusBadRequest, "'offset' must be a non-negative integer")
			return
		}
		aq.Offset = offset
	}

	alerts, err := s.store.QueryAlerts(r.Context(), aq)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "failed to query alerts")
		return
	}

	// Ensure we always return a JSON array, not null.
	if alerts == nil {
		alerts = []storage.Alert{}
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(alerts)
}

// handleGetHosts responds to GET /api/v1/hosts.
//
// Returns HTTP 200 with a JSON array of all registered Host objects ordered
// alphabetically by hostname.
func (s *Server) handleGetHosts(w http.ResponseWriter, r *http.Request) {
	hosts, err := s.store.ListHosts(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "failed to list hosts")
		return
	}

	if hosts == nil {
		hosts = []storage.Host{}
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(hosts)
}

// handleGetAudit responds to GET /api/v1/audit.
//
// Supported query parameters:
//
//	host_id – exact host UUID (required)
//	from    – RFC3339 start of the created_at window (required)
//	to      – RFC3339 end of the created_at window (required)
//
// Returns HTTP 400 when required parameters are missing or malformed.
// Returns HTTP 200 with a JSON array of AuditEntry objects on success.
func (s *Server) handleGetAudit(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()

	hostID := q.Get("host_id")
	if hostID == "" {
		writeError(w, http.StatusBadRequest, "query parameter 'host_id' is required")
		return
	}

	fromStr := q.Get("from")
	toStr := q.Get("to")
	if fromStr == "" || toStr == "" {
		writeError(w, http.StatusBadRequest, "query parameters 'from' and 'to' are required (RFC3339)")
		return
	}

	from, err := time.Parse(time.RFC3339, fromStr)
	if err != nil {
		writeError(w, http.StatusBadRequest, "'from' must be a valid RFC3339 timestamp")
		return
	}
	to, err := time.Parse(time.RFC3339, toStr)
	if err != nil {
		writeError(w, http.StatusBadRequest, "'to' must be a valid RFC3339 timestamp")
		return
	}
	if !to.After(from) {
		writeError(w, http.StatusBadRequest, "'to' must be after 'from'")
		return
	}

	entries, err := s.store.QueryAuditEntries(r.Context(), hostID, from, to)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "failed to query audit entries")
		return
	}

	if entries == nil {
		entries = []storage.AuditEntry{}
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_ = json.NewEncoder(w).Encode(entries)
}
