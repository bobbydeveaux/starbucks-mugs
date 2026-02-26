package rest

import (
	"context"
	"time"

	"github.com/tripwire/agent/internal/server/storage"
)

// Store is the subset of storage.Store methods used by the REST handlers.
// Defining an interface allows handlers to be tested with a mock store without
// a live PostgreSQL connection.
type Store interface {
	// QueryAlerts returns alerts matching the given filter and pagination params.
	QueryAlerts(ctx context.Context, q storage.AlertQuery) ([]storage.Alert, error)

	// ListHosts returns all registered hosts ordered alphabetically by hostname.
	ListHosts(ctx context.Context) ([]storage.Host, error)

	// QueryAuditEntries returns audit entries for hostID within [from, to).
	QueryAuditEntries(ctx context.Context, hostID string, from, to time.Time) ([]storage.AuditEntry, error)
}
