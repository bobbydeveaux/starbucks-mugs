// Package config provides YAML configuration parsing and validation for the
// TripWire agent. Configuration is loaded from a YAML file specified via the
// --config flag and governs all agent behaviour: which tripwires to watch,
// how to reach the dashboard, and where to store local state.
package config

import (
	"errors"
	"fmt"
	"net"
	"os"
	"strings"
	"time"

	"gopkg.in/yaml.v3"
)

// ---------------------------------------------------------------------------
// Severity
// ---------------------------------------------------------------------------

// Severity represents the alert severity level for a tripwire rule.
type Severity string

const (
	SeverityInfo     Severity = "INFO"
	SeverityWarn     Severity = "WARN"
	SeverityCritical Severity = "CRITICAL"
)

// validSeverities is the authoritative set of accepted severity strings.
var validSeverities = map[Severity]struct{}{
	SeverityInfo:     {},
	SeverityWarn:     {},
	SeverityCritical: {},
}

// UnmarshalYAML implements yaml.Unmarshaler so severity values are
// case-normalised and validated at parse time.
func (s *Severity) UnmarshalYAML(value *yaml.Node) error {
	var raw string
	if err := value.Decode(&raw); err != nil {
		return err
	}
	normalised := Severity(strings.ToUpper(strings.TrimSpace(raw)))
	if _, ok := validSeverities[normalised]; !ok {
		return fmt.Errorf("invalid severity %q: must be one of INFO, WARN, CRITICAL", raw)
	}
	*s = normalised
	return nil
}

// ---------------------------------------------------------------------------
// TLS
// ---------------------------------------------------------------------------

// TLSConfig holds the mTLS certificate material paths for the agent.
// All three files must exist and be readable by the agent process.
type TLSConfig struct {
	// CACert is the path to the operator CA certificate (PEM).
	CACert string `yaml:"ca_cert"`
	// AgentCert is the path to this agent's client certificate (PEM).
	AgentCert string `yaml:"agent_cert"`
	// AgentKey is the path to this agent's private key (PEM, mode 0600).
	AgentKey string `yaml:"agent_key"`
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

// DashboardConfig configures the connection to the central dashboard server.
type DashboardConfig struct {
	// Endpoint is the gRPC server address in "host:port" form.
	Endpoint string `yaml:"endpoint"`
	// TLS holds the mTLS credential file paths.
	TLS TLSConfig `yaml:"tls"`
	// ReconnectDelay is the initial backoff before the first reconnection
	// attempt (doubles on each attempt, capped at ReconnectMaxDelay).
	ReconnectDelay time.Duration `yaml:"reconnect_delay"`
	// ReconnectMaxDelay is the upper bound for exponential backoff.
	ReconnectMaxDelay time.Duration `yaml:"reconnect_max_delay"`
	// DialTimeout is the maximum time allowed for a single dial attempt.
	DialTimeout time.Duration `yaml:"dial_timeout"`
}

// ---------------------------------------------------------------------------
// File Tripwire
// ---------------------------------------------------------------------------

// FileEvent specifies which filesystem operations to monitor.
type FileEvent string

const (
	FileEventRead   FileEvent = "read"
	FileEventWrite  FileEvent = "write"
	FileEventCreate FileEvent = "create"
	FileEventDelete FileEvent = "delete"
	FileEventRename FileEvent = "rename"
	FileEventChmod  FileEvent = "chmod"
)

var validFileEvents = map[FileEvent]struct{}{
	FileEventRead:   {},
	FileEventWrite:  {},
	FileEventCreate: {},
	FileEventDelete: {},
	FileEventRename: {},
	FileEventChmod:  {},
}

// FileRule defines a filesystem tripwire.
type FileRule struct {
	// Name is a unique human-readable identifier for this rule.
	Name string `yaml:"name"`
	// Path is the filesystem path to monitor (file or directory).
	Path string `yaml:"path"`
	// Recursive enables monitoring of all files within a directory tree.
	// Ignored when Path is a regular file.
	Recursive bool `yaml:"recursive"`
	// Events is the list of filesystem operations that trigger an alert.
	// Defaults to [write, create, delete] when omitted.
	Events []FileEvent `yaml:"events"`
	// Severity is the alert severity level.  Defaults to WARN when omitted.
	Severity Severity `yaml:"severity"`
}

// ---------------------------------------------------------------------------
// Network Tripwire
// ---------------------------------------------------------------------------

// NetworkProtocol specifies the transport protocol to monitor.
type NetworkProtocol string

const (
	NetworkProtocolTCP  NetworkProtocol = "tcp"
	NetworkProtocolUDP  NetworkProtocol = "udp"
	NetworkProtocolBoth NetworkProtocol = "both"
)

var validNetworkProtocols = map[NetworkProtocol]struct{}{
	NetworkProtocolTCP:  {},
	NetworkProtocolUDP:  {},
	NetworkProtocolBoth: {},
}

// NetworkRule defines a network port tripwire.
type NetworkRule struct {
	// Name is a unique human-readable identifier for this rule.
	Name string `yaml:"name"`
	// Port is the port number to monitor (1–65535).
	Port int `yaml:"port"`
	// Protocol specifies tcp, udp, or both.  Defaults to "tcp" when omitted.
	Protocol NetworkProtocol `yaml:"protocol"`
	// Direction is "inbound", "outbound", or "both".  Defaults to "inbound".
	Direction string `yaml:"direction"`
	// Severity is the alert severity level.  Defaults to WARN when omitted.
	Severity Severity `yaml:"severity"`
}

// ---------------------------------------------------------------------------
// Process Tripwire
// ---------------------------------------------------------------------------

// ProcessRule defines a process execution tripwire.
type ProcessRule struct {
	// Name is a unique human-readable identifier for this rule.
	Name string `yaml:"name"`
	// ProcessName is the executable name (basename) to watch, e.g. "nc".
	ProcessName string `yaml:"process_name"`
	// MatchArgs optionally restricts the tripwire to processes whose
	// command-line arguments contain the given substring.
	MatchArgs string `yaml:"match_args"`
	// Severity is the alert severity level.  Defaults to WARN when omitted.
	Severity Severity `yaml:"severity"`
}

// ---------------------------------------------------------------------------
// Queue
// ---------------------------------------------------------------------------

// QueueConfig controls the local SQLite alert queue that buffers events when
// the dashboard is unreachable.
type QueueConfig struct {
	// Path is the filesystem location of the SQLite database file.
	Path string `yaml:"path"`
	// MaxDepth is the maximum number of undelivered alerts the queue will
	// hold before shedding lower-priority events.  0 = unlimited.
	MaxDepth int `yaml:"max_depth"`
	// FlushInterval is how frequently the flush goroutine attempts to drain
	// queued alerts to the dashboard.
	FlushInterval time.Duration `yaml:"flush_interval"`
}

// ---------------------------------------------------------------------------
// Audit
// ---------------------------------------------------------------------------

// AuditConfig controls the append-only SHA-256 chained audit log.
type AuditConfig struct {
	// Path is the filesystem location of the audit log file.
	Path string `yaml:"path"`
	// MaxSizeBytes is the maximum size before a warning is emitted.
	// 0 = no limit.  Note: the log is never automatically truncated.
	MaxSizeBytes int64 `yaml:"max_size_bytes"`
}

// ---------------------------------------------------------------------------
// Logging
// ---------------------------------------------------------------------------

// LogLevel specifies the minimum level of messages emitted by the agent's
// structured logger (zap).
type LogLevel string

const (
	LogLevelDebug LogLevel = "debug"
	LogLevelInfo  LogLevel = "info"
	LogLevelWarn  LogLevel = "warn"
	LogLevelError LogLevel = "error"
)

var validLogLevels = map[LogLevel]struct{}{
	LogLevelDebug: {},
	LogLevelInfo:  {},
	LogLevelWarn:  {},
	LogLevelError: {},
}

// LogFormat controls the output encoding of the logger.
type LogFormat string

const (
	LogFormatJSON    LogFormat = "json"
	LogFormatConsole LogFormat = "console"
)

var validLogFormats = map[LogFormat]struct{}{
	LogFormatJSON:    {},
	LogFormatConsole: {},
}

// LoggingConfig controls the agent's structured logger.
type LoggingConfig struct {
	// Level is the minimum log level.  Defaults to "info".
	Level LogLevel `yaml:"level"`
	// Format is "json" or "console".  Defaults to "json" for production use.
	Format LogFormat `yaml:"format"`
	// FilePath is an optional path to write logs to in addition to stdout.
	FilePath string `yaml:"file_path"`
}

// ---------------------------------------------------------------------------
// Health
// ---------------------------------------------------------------------------

// HealthConfig controls the /healthz HTTP endpoint.
type HealthConfig struct {
	// Enabled controls whether the /healthz endpoint is served.
	Enabled bool `yaml:"enabled"`
	// Address is the listen address in "host:port" form.
	// Defaults to "127.0.0.1:9090".
	Address string `yaml:"address"`
}

// ---------------------------------------------------------------------------
// Agent (top-level)
// ---------------------------------------------------------------------------

// AgentConfig is the root configuration for the TripWire agent.  It is
// populated by parsing a YAML file with ParseFile.
type AgentConfig struct {
	// Hostname overrides the system hostname used in alert payloads.
	// Defaults to os.Hostname() when empty.
	Hostname string `yaml:"hostname"`
	// AgentVersion is set at build time and surfaced in RegisterAgent RPCs.
	AgentVersion string `yaml:"agent_version"`

	// Dashboard holds connection settings for the central dashboard server.
	Dashboard DashboardConfig `yaml:"dashboard"`

	// Rules contains all tripwire rules active on this agent.
	Rules RulesConfig `yaml:"rules"`

	// Queue configures the local SQLite alert queue.
	Queue QueueConfig `yaml:"queue"`

	// Audit configures the SHA-256 chained audit log.
	Audit AuditConfig `yaml:"audit"`

	// Logging configures the structured logger.
	Logging LoggingConfig `yaml:"logging"`

	// Health configures the /healthz HTTP endpoint.
	Health HealthConfig `yaml:"health"`
}

// RulesConfig groups the three tripwire rule lists.
type RulesConfig struct {
	// Files contains filesystem tripwire rules.
	Files []FileRule `yaml:"files"`
	// Networks contains network port tripwire rules.
	Networks []NetworkRule `yaml:"networks"`
	// Processes contains process execution tripwire rules.
	Processes []ProcessRule `yaml:"processes"`
}

// ---------------------------------------------------------------------------
// Defaults
// ---------------------------------------------------------------------------

// applyDefaults fills in omitted fields with sensible production values.
// It is called by ParseFile before validation so that validation can rely on
// defaults being present.
func applyDefaults(cfg *AgentConfig) error {
	// Hostname
	if cfg.Hostname == "" {
		h, err := os.Hostname()
		if err != nil {
			return fmt.Errorf("resolving system hostname: %w", err)
		}
		cfg.Hostname = h
	}

	// Dashboard defaults
	if cfg.Dashboard.ReconnectDelay == 0 {
		cfg.Dashboard.ReconnectDelay = 5 * time.Second
	}
	if cfg.Dashboard.ReconnectMaxDelay == 0 {
		cfg.Dashboard.ReconnectMaxDelay = 5 * time.Minute
	}
	if cfg.Dashboard.DialTimeout == 0 {
		cfg.Dashboard.DialTimeout = 30 * time.Second
	}

	// Queue defaults
	if cfg.Queue.Path == "" {
		cfg.Queue.Path = "/var/lib/tripwire/queue.db"
	}
	if cfg.Queue.FlushInterval == 0 {
		cfg.Queue.FlushInterval = 5 * time.Second
	}

	// Audit defaults
	if cfg.Audit.Path == "" {
		cfg.Audit.Path = "/var/log/tripwire/audit.log"
	}

	// Logging defaults
	if cfg.Logging.Level == "" {
		cfg.Logging.Level = LogLevelInfo
	}
	if cfg.Logging.Format == "" {
		cfg.Logging.Format = LogFormatJSON
	}

	// Health defaults
	if cfg.Health.Address == "" {
		cfg.Health.Address = "127.0.0.1:9090"
	}

	// Per-rule defaults
	for i := range cfg.Rules.Files {
		r := &cfg.Rules.Files[i]
		if r.Severity == "" {
			r.Severity = SeverityWarn
		}
		if len(r.Events) == 0 {
			r.Events = []FileEvent{FileEventWrite, FileEventCreate, FileEventDelete}
		}
	}
	for i := range cfg.Rules.Networks {
		r := &cfg.Rules.Networks[i]
		if r.Severity == "" {
			r.Severity = SeverityWarn
		}
		if r.Protocol == "" {
			r.Protocol = NetworkProtocolTCP
		}
		if r.Direction == "" {
			r.Direction = "inbound"
		}
	}
	for i := range cfg.Rules.Processes {
		r := &cfg.Rules.Processes[i]
		if r.Severity == "" {
			r.Severity = SeverityWarn
		}
	}

	return nil
}

// ---------------------------------------------------------------------------
// ParseFile
// ---------------------------------------------------------------------------

// ParseFile reads the YAML file at path, applies defaults, and validates the
// resulting configuration.  It returns the validated AgentConfig or an error
// that describes every validation failure (not just the first one).
func ParseFile(path string) (*AgentConfig, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("reading config file %q: %w", path, err)
	}
	return Parse(data)
}

// Parse decodes YAML bytes, applies defaults, and validates the configuration.
// Callers who already have the YAML in memory (e.g. tests) should use this
// function directly.
func Parse(data []byte) (*AgentConfig, error) {
	var cfg AgentConfig
	decoder := yaml.NewDecoder(strings.NewReader(string(data)))
	decoder.KnownFields(true) // reject unrecognised YAML keys
	if err := decoder.Decode(&cfg); err != nil {
		return nil, fmt.Errorf("parsing YAML: %w", err)
	}

	if err := applyDefaults(&cfg); err != nil {
		return nil, err
	}

	if errs := Validate(&cfg); len(errs) > 0 {
		msgs := make([]string, len(errs))
		for i, e := range errs {
			msgs[i] = e.Error()
		}
		return nil, fmt.Errorf("invalid configuration:\n  - %s", strings.Join(msgs, "\n  - "))
	}

	return &cfg, nil
}

// ---------------------------------------------------------------------------
// Validate
// ---------------------------------------------------------------------------

// Validate checks cfg for semantic errors and returns all of them at once so
// operators can see and fix every problem in a single run.  An empty slice
// means the configuration is valid.
func Validate(cfg *AgentConfig) []error {
	var errs []error
	add := func(format string, args ...any) {
		errs = append(errs, fmt.Errorf(format, args...))
	}

	// ── Dashboard ─────────────────────────────────────────────────────────
	if cfg.Dashboard.Endpoint == "" {
		add("dashboard.endpoint must not be empty")
	} else if _, _, err := net.SplitHostPort(cfg.Dashboard.Endpoint); err != nil {
		add("dashboard.endpoint %q is not a valid host:port address: %v",
			cfg.Dashboard.Endpoint, err)
	}

	if cfg.Dashboard.TLS.CACert == "" {
		add("dashboard.tls.ca_cert must not be empty")
	} else if err := checkFileReadable(cfg.Dashboard.TLS.CACert); err != nil {
		add("dashboard.tls.ca_cert: %v", err)
	}

	if cfg.Dashboard.TLS.AgentCert == "" {
		add("dashboard.tls.agent_cert must not be empty")
	} else if err := checkFileReadable(cfg.Dashboard.TLS.AgentCert); err != nil {
		add("dashboard.tls.agent_cert: %v", err)
	}

	if cfg.Dashboard.TLS.AgentKey == "" {
		add("dashboard.tls.agent_key must not be empty")
	} else if err := checkFileReadable(cfg.Dashboard.TLS.AgentKey); err != nil {
		add("dashboard.tls.agent_key: %v", err)
	}

	if cfg.Dashboard.ReconnectDelay <= 0 {
		add("dashboard.reconnect_delay must be positive")
	}
	if cfg.Dashboard.ReconnectMaxDelay <= 0 {
		add("dashboard.reconnect_max_delay must be positive")
	}
	if cfg.Dashboard.ReconnectMaxDelay < cfg.Dashboard.ReconnectDelay {
		add("dashboard.reconnect_max_delay (%v) must be >= reconnect_delay (%v)",
			cfg.Dashboard.ReconnectMaxDelay, cfg.Dashboard.ReconnectDelay)
	}
	if cfg.Dashboard.DialTimeout <= 0 {
		add("dashboard.dial_timeout must be positive")
	}

	// ── Queue ─────────────────────────────────────────────────────────────
	if cfg.Queue.Path == "" {
		add("queue.path must not be empty")
	}
	if cfg.Queue.MaxDepth < 0 {
		add("queue.max_depth must be >= 0 (use 0 for unlimited)")
	}
	if cfg.Queue.FlushInterval <= 0 {
		add("queue.flush_interval must be positive")
	}

	// ── Audit ─────────────────────────────────────────────────────────────
	if cfg.Audit.Path == "" {
		add("audit.path must not be empty")
	}
	if cfg.Audit.MaxSizeBytes < 0 {
		add("audit.max_size_bytes must be >= 0 (use 0 for unlimited)")
	}

	// ── Logging ───────────────────────────────────────────────────────────
	if _, ok := validLogLevels[cfg.Logging.Level]; !ok {
		add("logging.level %q is invalid; must be one of debug, info, warn, error",
			cfg.Logging.Level)
	}
	if _, ok := validLogFormats[cfg.Logging.Format]; !ok {
		add("logging.format %q is invalid; must be one of json, console",
			cfg.Logging.Format)
	}

	// ── Health ────────────────────────────────────────────────────────────
	if cfg.Health.Enabled {
		if cfg.Health.Address == "" {
			add("health.address must not be empty when health endpoint is enabled")
		} else if _, _, err := net.SplitHostPort(cfg.Health.Address); err != nil {
			add("health.address %q is not a valid host:port address: %v",
				cfg.Health.Address, err)
		}
	}

	// ── File rules ────────────────────────────────────────────────────────
	fileNames := map[string]struct{}{}
	for i, r := range cfg.Rules.Files {
		prefix := fmt.Sprintf("rules.files[%d]", i)
		if r.Name == "" {
			add("%s.name must not be empty", prefix)
		} else if _, dup := fileNames[r.Name]; dup {
			add("%s.name %q is duplicated; rule names must be unique", prefix, r.Name)
		} else {
			fileNames[r.Name] = struct{}{}
		}
		if r.Path == "" {
			add("%s.path must not be empty", prefix)
		}
		for j, ev := range r.Events {
			if _, ok := validFileEvents[ev]; !ok {
				add("%s.events[%d] %q is invalid; must be one of read, write, create, delete, rename, chmod",
					prefix, j, ev)
			}
		}
		if _, ok := validSeverities[r.Severity]; !ok {
			add("%s.severity %q is invalid; must be one of INFO, WARN, CRITICAL", prefix, r.Severity)
		}
	}

	// ── Network rules ─────────────────────────────────────────────────────
	netNames := map[string]struct{}{}
	for i, r := range cfg.Rules.Networks {
		prefix := fmt.Sprintf("rules.networks[%d]", i)
		if r.Name == "" {
			add("%s.name must not be empty", prefix)
		} else if _, dup := netNames[r.Name]; dup {
			add("%s.name %q is duplicated; rule names must be unique", prefix, r.Name)
		} else {
			netNames[r.Name] = struct{}{}
		}
		if r.Port < 1 || r.Port > 65535 {
			add("%s.port %d is out of range; must be between 1 and 65535", prefix, r.Port)
		}
		if _, ok := validNetworkProtocols[r.Protocol]; !ok {
			add("%s.protocol %q is invalid; must be one of tcp, udp, both", prefix, r.Protocol)
		}
		switch r.Direction {
		case "inbound", "outbound", "both":
			// valid
		default:
			add("%s.direction %q is invalid; must be one of inbound, outbound, both", prefix, r.Direction)
		}
		if _, ok := validSeverities[r.Severity]; !ok {
			add("%s.severity %q is invalid; must be one of INFO, WARN, CRITICAL", prefix, r.Severity)
		}
	}

	// ── Process rules ─────────────────────────────────────────────────────
	procNames := map[string]struct{}{}
	for i, r := range cfg.Rules.Processes {
		prefix := fmt.Sprintf("rules.processes[%d]", i)
		if r.Name == "" {
			add("%s.name must not be empty", prefix)
		} else if _, dup := procNames[r.Name]; dup {
			add("%s.name %q is duplicated; rule names must be unique", prefix, r.Name)
		} else {
			procNames[r.Name] = struct{}{}
		}
		if r.ProcessName == "" {
			add("%s.process_name must not be empty", prefix)
		}
		if _, ok := validSeverities[r.Severity]; !ok {
			add("%s.severity %q is invalid; must be one of INFO, WARN, CRITICAL", prefix, r.Severity)
		}
	}

	// ── At least one rule ─────────────────────────────────────────────────
	if len(cfg.Rules.Files) == 0 && len(cfg.Rules.Networks) == 0 && len(cfg.Rules.Processes) == 0 {
		errs = append(errs, errors.New("at least one tripwire rule (files, networks, or processes) must be defined"))
	}

	return errs
}

// checkFileReadable returns an error if path does not exist or is not readable.
// It does not validate the file's content.
func checkFileReadable(path string) error {
	f, err := os.Open(path)
	if err != nil {
		return err
	}
	f.Close()
	return nil
}
