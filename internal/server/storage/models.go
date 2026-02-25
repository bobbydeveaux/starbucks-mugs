// Package storage provides the PostgreSQL-backed persistence layer for the
// TripWire dashboard server. It exposes typed model structs for all four
// database tables (hosts, alerts, tripwire_rules, audit_entries) and a Store
// that wraps a pgxpool connection pool with a batched alert-insert path.
package storage

import (
	"encoding/json"
	"time"
)

// TripwireType is the category of the sensor that produced an alert.
type TripwireType string

const (
	TripwireTypeFile    TripwireType = "FILE"
	TripwireTypeNetwork TripwireType = "NETWORK"
	TripwireTypeProcess TripwireType = "PROCESS"
)

// Severity is the operator-configured urgency level of an alert or rule.
type Severity string

const (
	SeverityInfo     Severity = "INFO"
	SeverityWarn     Severity = "WARN"
	SeverityCritical Severity = "CRITICAL"
)

// HostStatus represents the liveness state of a monitored host as seen by the
// dashboard.
type HostStatus string

const (
	HostStatusOnline   HostStatus = "ONLINE"
	HostStatusOffline  HostStatus = "OFFLINE"
	HostStatusDegraded HostStatus = "DEGRADED"
)

// Host maps to the `hosts` table.
//
// IPAddress is the dotted-decimal or CIDR text representation of the agent's
// primary network address.  An empty string is stored as SQL NULL.
// LastSeen is nil when the host has never sent a heartbeat.
type Host struct {
	HostID       string     `json:"host_id"`
	Hostname     string     `json:"hostname"`
	IPAddress    string     `json:"ip_address,omitempty"`
	Platform     string     `json:"platform,omitempty"`
	AgentVersion string     `json:"agent_version,omitempty"`
	LastSeen     *time.Time `json:"last_seen,omitempty"`
	Status       HostStatus `json:"status"`
}

// Alert maps to the `alerts` partitioned table.
//
// EventDetail carries the raw JSONB payload from the database.  It round-trips
// without modification: bytes written to the DB are returned verbatim on read.
// A nil EventDetail is stored as SQL NULL and returned as a nil json.RawMessage.
type Alert struct {
	AlertID      string          `json:"alert_id"`
	HostID       string          `json:"host_id"`
	Timestamp    time.Time       `json:"timestamp"`
	TripwireType TripwireType    `json:"tripwire_type"`
	RuleName     string          `json:"rule_name"`
	EventDetail  json.RawMessage `json:"event_detail,omitempty"`
	Severity     Severity        `json:"severity"`
	ReceivedAt   time.Time       `json:"received_at"`
}

// TripwireRule maps to the `tripwire_rules` table.
//
// A nil HostID (empty string) means the rule applies globally to every host.
type TripwireRule struct {
	RuleID   string       `json:"rule_id"`
	HostID   string       `json:"host_id,omitempty"` // empty == global
	RuleType TripwireType `json:"rule_type"`
	Target   string       `json:"target"`
	Severity Severity     `json:"severity"`
	Enabled  bool         `json:"enabled"`
}

// AuditEntry maps to the `audit_entries` table.
//
// EventHash is the SHA-256 hex digest of this entry.
// PrevHash is the SHA-256 hex digest of the previous entry; for the genesis
// entry this is a string of 64 zeros.
// Payload holds the full event data as a JSONB value.
type AuditEntry struct {
	EntryID     string          `json:"entry_id"`
	HostID      string          `json:"host_id"`
	SequenceNum int64           `json:"sequence_num"`
	EventHash   string          `json:"event_hash"`
	PrevHash    string          `json:"prev_hash"`
	Payload     json.RawMessage `json:"payload"`
	CreatedAt   time.Time       `json:"created_at"`
}

// AlertQuery carries the filter and pagination parameters for QueryAlerts.
//
// From and To are mandatory and bracket the received_at column, enabling
// PostgreSQL partition pruning. Limit defaults to 100 when ≤ 0. A nil Severity
// means no severity filter is applied. An empty HostID matches all hosts.
type AlertQuery struct {
	HostID   string
	Severity *Severity
	From     time.Time
	To       time.Time
	Limit    int
	Offset   int
}
