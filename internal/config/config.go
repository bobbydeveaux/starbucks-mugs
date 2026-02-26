// Package config provides YAML configuration loading and validation for the
// TripWire agent.
package config

import (
	"errors"
	"fmt"
	"os"

	"gopkg.in/yaml.v3"
)

// Config is the top-level configuration structure for the TripWire agent.
type Config struct {
	// DashboardAddr is the gRPC endpoint of the TripWire dashboard server
	// (e.g. "dashboard.example.com:4443"). Required.
	DashboardAddr string `yaml:"dashboard_addr"`

	// TLS holds the paths to the agent certificate, private key, and CA
	// certificate used for mTLS. Required.
	TLS TLSConfig `yaml:"tls"`

	// Rules is the list of tripwire rules the agent should enforce.
	Rules []TripwireRule `yaml:"rules"`

	// LogLevel sets the minimum log severity: "debug", "info", "warn", or
	// "error". Defaults to "info" when omitted.
	LogLevel string `yaml:"log_level"`

	// HealthAddr is the listen address for the /healthz HTTP server
	// (e.g. "127.0.0.1:9000"). Defaults to "127.0.0.1:9000" when omitted.
	HealthAddr string `yaml:"health_addr"`

	// AgentVersion is an optional human-readable version string sent to the
	// dashboard during agent registration (e.g. "v0.1.0").
	AgentVersion string `yaml:"agent_version"`
}

// TLSConfig holds certificate and key paths for mTLS.
type TLSConfig struct {
	// CertPath is the path to the agent's PEM-encoded client certificate.
	// Required.
	CertPath string `yaml:"cert_path"`

	// KeyPath is the path to the agent's PEM-encoded private key. Required.
	KeyPath string `yaml:"key_path"`

	// CAPath is the path to the PEM-encoded CA certificate used to verify
	// the dashboard server's certificate. Required.
	CAPath string `yaml:"ca_path"`
}

// TripwireRule describes a single file, network, or process tripwire to
// monitor.
type TripwireRule struct {
	// Name is a human-readable identifier for this rule (e.g.
	// "etc-passwd-watch"). Required.
	Name string `yaml:"name"`

	// Type is one of "FILE", "NETWORK", or "PROCESS". Required.
	Type string `yaml:"type"`

	// Target is the rule-specific target: a glob path for FILE rules, a
	// port number ("8080") for NETWORK rules, or a process name for PROCESS
	// rules. Required.
	Target string `yaml:"target"`

	// Severity is one of "INFO", "WARN", or "CRITICAL". Required.
	Severity string `yaml:"severity"`

	// Protocol restricts a NETWORK rule to a specific transport-layer
	// protocol. Accepted values: "tcp", "udp", "both". Defaults to "both"
	// when omitted. Ignored for non-NETWORK rules.
	Protocol string `yaml:"protocol,omitempty"`

	// Direction restricts a NETWORK rule to connections travelling in a
	// specific direction. Accepted values: "inbound", "outbound", "both".
	// Defaults to "inbound" when omitted. Ignored for non-NETWORK rules.
	Direction string `yaml:"direction,omitempty"`
}

// validLogLevels is the set of accepted log level strings.
var validLogLevels = map[string]bool{
	"debug": true,
	"info":  true,
	"warn":  true,
	"error": true,
}

// validRuleTypes is the set of accepted rule type strings.
var validRuleTypes = map[string]bool{
	"FILE":    true,
	"NETWORK": true,
	"PROCESS": true,
}

// validSeverities is the set of accepted severity strings.
var validSeverities = map[string]bool{
	"INFO":     true,
	"WARN":     true,
	"CRITICAL": true,
}

// validProtocols is the set of accepted protocol values for NETWORK rules.
var validProtocols = map[string]bool{
	"tcp":  true,
	"udp":  true,
	"both": true,
}

// validDirections is the set of accepted direction values for NETWORK rules.
var validDirections = map[string]bool{
	"inbound":  true,
	"outbound": true,
	"both":     true,
}

// LoadConfig reads the YAML file at path, unmarshals it into Config, applies
// defaults, and validates all required fields. It returns a typed error
// describing the first validation failure encountered.
func LoadConfig(path string) (*Config, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("config: cannot read %q: %w", path, err)
	}

	var cfg Config
	if err := yaml.Unmarshal(data, &cfg); err != nil {
		return nil, fmt.Errorf("config: cannot parse %q: %w", path, err)
	}

	applyDefaults(&cfg)

	if err := validate(&cfg); err != nil {
		return nil, fmt.Errorf("config: validation failed for %q: %w", path, err)
	}

	return &cfg, nil
}

// applyDefaults fills in zero-value optional fields with sensible defaults.
func applyDefaults(cfg *Config) {
	if cfg.LogLevel == "" {
		cfg.LogLevel = "info"
	}
	if cfg.HealthAddr == "" {
		cfg.HealthAddr = "127.0.0.1:9000"
	}
	for i := range cfg.Rules {
		if cfg.Rules[i].Type == "NETWORK" {
			if cfg.Rules[i].Protocol == "" {
				cfg.Rules[i].Protocol = "both"
			}
			if cfg.Rules[i].Direction == "" {
				cfg.Rules[i].Direction = "inbound"
			}
		}
	}
}

// validate checks that all required fields are populated and that enumerated
// fields contain only valid values.
func validate(cfg *Config) error {
	var errs []error

	if cfg.DashboardAddr == "" {
		errs = append(errs, errors.New("dashboard_addr is required"))
	}
	if cfg.TLS.CertPath == "" {
		errs = append(errs, errors.New("tls.cert_path is required"))
	}
	if cfg.TLS.KeyPath == "" {
		errs = append(errs, errors.New("tls.key_path is required"))
	}
	if cfg.TLS.CAPath == "" {
		errs = append(errs, errors.New("tls.ca_path is required"))
	}
	if !validLogLevels[cfg.LogLevel] {
		errs = append(errs, fmt.Errorf("log_level %q must be one of: debug, info, warn, error", cfg.LogLevel))
	}

	for i, r := range cfg.Rules {
		prefix := fmt.Sprintf("rules[%d]", i)
		if r.Name == "" {
			errs = append(errs, fmt.Errorf("%s: name is required", prefix))
		}
		if !validRuleTypes[r.Type] {
			errs = append(errs, fmt.Errorf("%s: type %q must be one of: FILE, NETWORK, PROCESS", prefix, r.Type))
		}
		if r.Target == "" {
			errs = append(errs, fmt.Errorf("%s: target is required", prefix))
		}
		if !validSeverities[r.Severity] {
			errs = append(errs, fmt.Errorf("%s: severity %q must be one of: INFO, WARN, CRITICAL", prefix, r.Severity))
		}
		if r.Type == "NETWORK" {
			if !validProtocols[r.Protocol] {
				errs = append(errs, fmt.Errorf("%s: protocol %q must be one of: tcp, udp, both", prefix, r.Protocol))
			}
			if !validDirections[r.Direction] {
				errs = append(errs, fmt.Errorf("%s: direction %q must be one of: inbound, outbound, both", prefix, r.Direction))
			}
		}
	}

	return errors.Join(errs...)
}
