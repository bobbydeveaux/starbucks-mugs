package storage

import (
	"context"
	"fmt"
	"sync"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	// DefaultBatchSize is the maximum number of alert rows held in-memory before
	// an automatic flush is triggered.
	DefaultBatchSize = 100

	// DefaultFlushInterval is how often the background goroutine flushes pending
	// alerts even when the batch has not yet reached DefaultBatchSize.
	DefaultFlushInterval = 100 * time.Millisecond
)

// Store is the PostgreSQL-backed storage layer for the TripWire dashboard.
//
// Alert ingestion is batched: callers enqueue individual Alert values via
// BatchInsertAlerts, which accumulates them in memory and flushes to the
// database either when the buffer reaches batchSize or when the background
// ticker fires, whichever comes first.  All other operations (hosts, rules,
// audit entries) are executed immediately.
type Store struct {
	pool          *pgxpool.Pool
	mu            sync.Mutex
	batch         []Alert
	batchSize     int
	flushInterval time.Duration
	stopCh        chan struct{}
	doneCh        chan struct{}
}

// New opens a pgxpool connection to connStr, pings the database, and starts
// the background flush goroutine.
//
// batchSize ≤ 0 is replaced with DefaultBatchSize.
// flushInterval ≤ 0 is replaced with DefaultFlushInterval.
func New(ctx context.Context, connStr string, batchSize int, flushInterval time.Duration) (*Store, error) {
	if batchSize <= 0 {
		batchSize = DefaultBatchSize
	}
	if flushInterval <= 0 {
		flushInterval = DefaultFlushInterval
	}

	pool, err := pgxpool.New(ctx, connStr)
	if err != nil {
		return nil, fmt.Errorf("pgxpool.New: %w", err)
	}
	if err := pool.Ping(ctx); err != nil {
		pool.Close()
		return nil, fmt.Errorf("pool.Ping: %w", err)
	}

	s := &Store{
		pool:          pool,
		batch:         make([]Alert, 0, batchSize),
		batchSize:     batchSize,
		flushInterval: flushInterval,
		stopCh:        make(chan struct{}),
		doneCh:        make(chan struct{}),
	}
	go s.flushLoop()
	return s, nil
}

// Close stops the background flush goroutine, flushes any remaining buffered
// alerts, and closes the connection pool.  It is safe to call Close more than
// once; subsequent calls are no-ops.
func (s *Store) Close(ctx context.Context) {
	select {
	case <-s.stopCh:
		// already closed
	default:
		close(s.stopCh)
		<-s.doneCh
		// Best-effort final flush; errors are not propagated on close.
		_ = s.Flush(ctx)
	}
	s.pool.Close()
}

// flushLoop is the background goroutine that ticks on flushInterval and calls
// Flush.  It exits when stopCh is closed.
func (s *Store) flushLoop() {
	defer close(s.doneCh)
	ticker := time.NewTicker(s.flushInterval)
	defer ticker.Stop()
	for {
		select {
		case <-s.stopCh:
			return
		case <-ticker.C:
			_ = s.Flush(context.Background())
		}
	}
}

// BatchInsertAlerts enqueues alert for deferred batch insertion.
//
// If the internal buffer reaches batchSize after appending, Flush is called
// synchronously before returning so that the caller observes back-pressure
// rather than unbounded memory growth.
func (s *Store) BatchInsertAlerts(ctx context.Context, alert Alert) error {
	s.mu.Lock()
	s.batch = append(s.batch, alert)
	full := len(s.batch) >= s.batchSize
	s.mu.Unlock()

	if full {
		return s.Flush(ctx)
	}
	return nil
}

// Flush drains the current alert buffer and sends all rows to PostgreSQL in a
// single pgx.Batch round-trip.  Rows that conflict on the primary key are
// silently ignored (idempotent replay support).
//
// Flush is safe to call concurrently: a mutex swap ensures each call drains a
// distinct snapshot of the buffer.
func (s *Store) Flush(ctx context.Context) error {
	s.mu.Lock()
	if len(s.batch) == 0 {
		s.mu.Unlock()
		return nil
	}
	toInsert := s.batch
	s.batch = make([]Alert, 0, s.batchSize)
	s.mu.Unlock()

	const query = `
		INSERT INTO alerts
			(alert_id, host_id, timestamp, tripwire_type, rule_name, event_detail, severity, received_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
		ON CONFLICT DO NOTHING`

	b := &pgx.Batch{}
	for i := range toInsert {
		a := &toInsert[i]
		detail := []byte(a.EventDetail)
		if detail == nil {
			detail = []byte("null")
		}
		b.Queue(query,
			a.AlertID, a.HostID, a.Timestamp,
			string(a.TripwireType), a.RuleName,
			detail,
			string(a.Severity), a.ReceivedAt,
		)
	}

	br := s.pool.SendBatch(ctx, b)
	defer br.Close()

	for range toInsert {
		if _, err := br.Exec(); err != nil {
			return fmt.Errorf("batch exec alert: %w", err)
		}
	}
	return nil
}

// QueryAlerts returns paginated alerts that fall within [q.From, q.To) on the
// received_at column.  The time-range constraint enables PostgreSQL partition
// pruning so only the relevant monthly partitions are scanned.
//
// Optional filters: q.HostID (exact match), q.Severity (exact match).
// q.Limit defaults to 100; q.Offset enables cursor-style pagination.
// Results are ordered by received_at DESC, alert_id ASC.
func (s *Store) QueryAlerts(ctx context.Context, q AlertQuery) ([]Alert, error) {
	if q.Limit <= 0 {
		q.Limit = 100
	}

	// Base args: $1=from, $2=to, $3=limit, $4=offset
	args := []any{q.From, q.To, q.Limit, q.Offset}
	where := "WHERE received_at >= $1 AND received_at < $2"
	argIdx := 5

	if q.HostID != "" {
		where += fmt.Sprintf(" AND host_id = $%d", argIdx)
		args = append(args, q.HostID)
		argIdx++
	}
	if q.Severity != nil {
		where += fmt.Sprintf(" AND severity = $%d", argIdx)
		args = append(args, string(*q.Severity))
		argIdx++ //nolint:ineffassign // reserved for future filters
	}

	sql := fmt.Sprintf(`
		SELECT alert_id, host_id, timestamp, tripwire_type, rule_name,
		       event_detail, severity, received_at
		FROM   alerts
		%s
		ORDER  BY received_at DESC, alert_id
		LIMIT  $3 OFFSET $4`, where)

	rows, err := s.pool.Query(ctx, sql, args...)
	if err != nil {
		return nil, fmt.Errorf("query alerts: %w", err)
	}
	defer rows.Close()

	var alerts []Alert
	for rows.Next() {
		var a Alert
		var detail []byte
		var tripwireType, severity string
		err := rows.Scan(
			&a.AlertID, &a.HostID, &a.Timestamp,
			&tripwireType, &a.RuleName,
			&detail,
			&severity, &a.ReceivedAt,
		)
		if err != nil {
			return nil, fmt.Errorf("scan alert: %w", err)
		}
		a.TripwireType = TripwireType(tripwireType)
		a.Severity = Severity(severity)
		a.EventDetail = detail
		alerts = append(alerts, a)
	}
	return alerts, rows.Err()
}

// --- Host CRUD ---

// UpsertHost inserts a new host or, on hostname conflict, updates all mutable
// fields.  It returns the effective host_id that is persisted in the database:
// on a clean insert this equals h.HostID; on a hostname conflict the existing
// host_id is returned unchanged, so callers always receive a stable identifier
// that correlates with historical alerts even across agent reconnects.
func (s *Store) UpsertHost(ctx context.Context, h Host) (string, error) {
	var effectiveHostID string
	err := s.pool.QueryRow(ctx, `
		INSERT INTO hosts
			(host_id, hostname, ip_address, platform, agent_version, last_seen, status)
		VALUES ($1, $2, $3::inet, $4, $5, $6, $7)
		ON CONFLICT (hostname) DO UPDATE SET
			ip_address    = EXCLUDED.ip_address,
			platform      = EXCLUDED.platform,
			agent_version = EXCLUDED.agent_version,
			last_seen     = EXCLUDED.last_seen,
			status        = EXCLUDED.status
		RETURNING host_id`,
		h.HostID,
		h.Hostname,
		nullableStr(h.IPAddress),
		nullableStr(h.Platform),
		nullableStr(h.AgentVersion),
		h.LastSeen,
		string(h.Status),
	).Scan(&effectiveHostID)
	if err != nil {
		return "", fmt.Errorf("upsert host: %w", err)
	}
	return effectiveHostID, nil
}

// GetHost returns the host with the given UUID, or an error wrapping
// pgx.ErrNoRows when not found.
func (s *Store) GetHost(ctx context.Context, hostID string) (*Host, error) {
	row := s.pool.QueryRow(ctx, `
		SELECT host_id, hostname, ip_address::text, platform, agent_version, last_seen, status
		FROM   hosts
		WHERE  host_id = $1`, hostID)
	h, err := scanHost(row)
	if err != nil {
		return nil, fmt.Errorf("get host %s: %w", hostID, err)
	}
	return h, nil
}

// ListHosts returns all registered hosts ordered alphabetically by hostname.
func (s *Store) ListHosts(ctx context.Context) ([]Host, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT host_id, hostname, ip_address::text, platform, agent_version, last_seen, status
		FROM   hosts
		ORDER  BY hostname`)
	if err != nil {
		return nil, fmt.Errorf("list hosts: %w", err)
	}
	defer rows.Close()

	var hosts []Host
	for rows.Next() {
		h, err := scanHost(rows)
		if err != nil {
			return nil, fmt.Errorf("scan host: %w", err)
		}
		hosts = append(hosts, *h)
	}
	return hosts, rows.Err()
}

// --- TripwireRule CRUD ---

// CreateRule inserts a new tripwire rule.  The caller is responsible for
// generating rule.RuleID (e.g. a UUID string); the database default is not
// used so that the ID is available immediately in the caller's context.
func (s *Store) CreateRule(ctx context.Context, r TripwireRule) error {
	_, err := s.pool.Exec(ctx, `
		INSERT INTO tripwire_rules (rule_id, host_id, rule_type, target, severity, enabled)
		VALUES ($1, $2, $3, $4, $5, $6)`,
		r.RuleID,
		nullableStr(r.HostID),
		string(r.RuleType),
		r.Target,
		string(r.Severity),
		r.Enabled,
	)
	if err != nil {
		return fmt.Errorf("create rule: %w", err)
	}
	return nil
}

// GetRule fetches a single tripwire rule by its UUID.
func (s *Store) GetRule(ctx context.Context, ruleID string) (*TripwireRule, error) {
	row := s.pool.QueryRow(ctx, `
		SELECT rule_id, host_id, rule_type, target, severity, enabled
		FROM   tripwire_rules
		WHERE  rule_id = $1`, ruleID)
	r, err := scanRule(row)
	if err != nil {
		return nil, fmt.Errorf("get rule %s: %w", ruleID, err)
	}
	return r, nil
}

// ListRules returns tripwire rules.  When hostID is non-empty, only rules
// explicitly assigned to that host or with a NULL host_id (global rules) are
// returned.  When hostID is empty, all rules are returned.
func (s *Store) ListRules(ctx context.Context, hostID string) ([]TripwireRule, error) {
	var (
		rows pgx.Rows
		err  error
	)
	if hostID != "" {
		rows, err = s.pool.Query(ctx, `
			SELECT rule_id, host_id, rule_type, target, severity, enabled
			FROM   tripwire_rules
			WHERE  host_id = $1 OR host_id IS NULL
			ORDER  BY rule_id`, hostID)
	} else {
		rows, err = s.pool.Query(ctx, `
			SELECT rule_id, host_id, rule_type, target, severity, enabled
			FROM   tripwire_rules
			ORDER  BY rule_id`)
	}
	if err != nil {
		return nil, fmt.Errorf("list rules: %w", err)
	}
	defer rows.Close()

	var rules []TripwireRule
	for rows.Next() {
		r, err := scanRule(rows)
		if err != nil {
			return nil, fmt.Errorf("scan rule: %w", err)
		}
		rules = append(rules, *r)
	}
	return rules, rows.Err()
}

// UpdateRule replaces all mutable fields of an existing tripwire rule.
func (s *Store) UpdateRule(ctx context.Context, r TripwireRule) error {
	_, err := s.pool.Exec(ctx, `
		UPDATE tripwire_rules
		SET    host_id   = $2,
		       rule_type = $3,
		       target    = $4,
		       severity  = $5,
		       enabled   = $6
		WHERE  rule_id = $1`,
		r.RuleID,
		nullableStr(r.HostID),
		string(r.RuleType),
		r.Target,
		string(r.Severity),
		r.Enabled,
	)
	if err != nil {
		return fmt.Errorf("update rule %s: %w", r.RuleID, err)
	}
	return nil
}

// DeleteRule removes the tripwire rule identified by ruleID.
func (s *Store) DeleteRule(ctx context.Context, ruleID string) error {
	_, err := s.pool.Exec(ctx, `DELETE FROM tripwire_rules WHERE rule_id = $1`, ruleID)
	if err != nil {
		return fmt.Errorf("delete rule %s: %w", ruleID, err)
	}
	return nil
}

// --- AuditEntry operations ---

// InsertAuditEntry persists a single tamper-evident audit log entry.
// The caller must populate EntryID, EventHash, PrevHash, and SequenceNum.
func (s *Store) InsertAuditEntry(ctx context.Context, e AuditEntry) error {
	_, err := s.pool.Exec(ctx, `
		INSERT INTO audit_entries
			(entry_id, host_id, sequence_num, event_hash, prev_hash, payload, created_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7)`,
		e.EntryID,
		e.HostID,
		e.SequenceNum,
		e.EventHash,
		e.PrevHash,
		[]byte(e.Payload),
		e.CreatedAt,
	)
	if err != nil {
		return fmt.Errorf("insert audit entry: %w", err)
	}
	return nil
}

// QueryAuditEntries returns audit entries for hostID with created_at in
// [from, to), ordered by sequence_num ascending.
func (s *Store) QueryAuditEntries(ctx context.Context, hostID string, from, to time.Time) ([]AuditEntry, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT entry_id, host_id, sequence_num, event_hash, prev_hash, payload, created_at
		FROM   audit_entries
		WHERE  host_id = $1 AND created_at >= $2 AND created_at < $3
		ORDER  BY sequence_num ASC`,
		hostID, from, to,
	)
	if err != nil {
		return nil, fmt.Errorf("query audit entries: %w", err)
	}
	defer rows.Close()

	var entries []AuditEntry
	for rows.Next() {
		var e AuditEntry
		var payload []byte
		err := rows.Scan(
			&e.EntryID, &e.HostID, &e.SequenceNum,
			&e.EventHash, &e.PrevHash,
			&payload,
			&e.CreatedAt,
		)
		if err != nil {
			return nil, fmt.Errorf("scan audit entry: %w", err)
		}
		e.Payload = payload
		entries = append(entries, e)
	}
	return entries, rows.Err()
}

// --- internal helpers ---

// scanner is satisfied by both pgx.Row and pgx.Rows, allowing shared scan
// helpers across single-row and multi-row queries.
type scanner interface {
	Scan(dest ...any) error
}

// scanHost reads one host row from s.  The ip_address column must be projected
// as ::text by the caller.
func scanHost(s scanner) (*Host, error) {
	var h Host
	var ip, platform, agentVersion *string
	var status string
	err := s.Scan(
		&h.HostID, &h.Hostname,
		&ip, &platform, &agentVersion,
		&h.LastSeen,
		&status,
	)
	if err != nil {
		return nil, err
	}
	h.Status = HostStatus(status)
	if ip != nil {
		h.IPAddress = *ip
	}
	if platform != nil {
		h.Platform = *platform
	}
	if agentVersion != nil {
		h.AgentVersion = *agentVersion
	}
	return &h, nil
}

// scanRule reads one tripwire_rule row from s.
func scanRule(s scanner) (*TripwireRule, error) {
	var r TripwireRule
	var hostID *string
	var ruleType, severity string
	err := s.Scan(&r.RuleID, &hostID, &ruleType, &r.Target, &severity, &r.Enabled)
	if err != nil {
		return nil, err
	}
	r.RuleType = TripwireType(ruleType)
	r.Severity = Severity(severity)
	if hostID != nil {
		r.HostID = *hostID
	}
	return &r, nil
}

// nullableStr converts an empty string to a nil pointer, which pgx stores as
// SQL NULL.  A non-empty string is returned as-is.
func nullableStr(s string) *string {
	if s == "" {
		return nil
	}
	return &s
}
