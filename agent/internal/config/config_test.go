package config_test

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/tripwire/agent/internal/config"
)

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

// writeTempFile creates a temporary file with the given contents and returns
// its path.  The file is removed when the test finishes.
func writeTempFile(t *testing.T, name, content string) string {
	t.Helper()
	dir := t.TempDir()
	path := filepath.Join(dir, name)
	if err := os.WriteFile(path, []byte(content), 0o600); err != nil {
		t.Fatalf("writeTempFile: %v", err)
	}
	return path
}

// minimalValidYAML returns a YAML snippet that passes all validations.
// Callers provide real paths to the three cert files via caPath, certPath, keyPath.
func minimalValidYAML(caPath, certPath, keyPath string) string {
	return `
dashboard:
  endpoint: "dashboard.example.com:443"
  tls:
    ca_cert: "` + caPath + `"
    agent_cert: "` + certPath + `"
    agent_key: "` + keyPath + `"

rules:
  files:
    - name: watch-passwd
      path: /etc/passwd
      severity: CRITICAL
`
}

// createCertFiles creates three empty placeholder files to satisfy file-
// readable validation without requiring a real PKI during tests.
func createCertFiles(t *testing.T) (ca, cert, key string) {
	t.Helper()
	ca = writeTempFile(t, "ca.crt", "placeholder")
	cert = writeTempFile(t, "agent.crt", "placeholder")
	key = writeTempFile(t, "agent.key", "placeholder")
	return
}

// ---------------------------------------------------------------------------
// Parse – golden-path
// ---------------------------------------------------------------------------

func TestParse_MinimalValid(t *testing.T) {
	ca, cert, key := createCertFiles(t)
	yaml := minimalValidYAML(ca, cert, key)

	cfg, err := config.Parse([]byte(yaml))
	if err != nil {
		t.Fatalf("expected no error, got: %v", err)
	}
	if cfg == nil {
		t.Fatal("expected non-nil config")
	}
}

func TestParse_DefaultsApplied(t *testing.T) {
	ca, cert, key := createCertFiles(t)
	yaml := minimalValidYAML(ca, cert, key)

	cfg, err := config.Parse([]byte(yaml))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	// Hostname should be populated from os.Hostname()
	if cfg.Hostname == "" {
		t.Error("expected Hostname to be defaulted from os.Hostname(), got empty string")
	}

	// Dashboard timing defaults
	if cfg.Dashboard.ReconnectDelay != 5*time.Second {
		t.Errorf("reconnect_delay: got %v, want 5s", cfg.Dashboard.ReconnectDelay)
	}
	if cfg.Dashboard.ReconnectMaxDelay != 5*time.Minute {
		t.Errorf("reconnect_max_delay: got %v, want 5m", cfg.Dashboard.ReconnectMaxDelay)
	}
	if cfg.Dashboard.DialTimeout != 30*time.Second {
		t.Errorf("dial_timeout: got %v, want 30s", cfg.Dashboard.DialTimeout)
	}

	// Queue defaults
	if cfg.Queue.Path == "" {
		t.Error("queue.path should have a default")
	}
	if cfg.Queue.FlushInterval != 5*time.Second {
		t.Errorf("queue.flush_interval: got %v, want 5s", cfg.Queue.FlushInterval)
	}

	// Audit default
	if cfg.Audit.Path == "" {
		t.Error("audit.path should have a default")
	}

	// Logging defaults
	if cfg.Logging.Level != config.LogLevelInfo {
		t.Errorf("logging.level: got %q, want %q", cfg.Logging.Level, config.LogLevelInfo)
	}
	if cfg.Logging.Format != config.LogFormatJSON {
		t.Errorf("logging.format: got %q, want %q", cfg.Logging.Format, config.LogFormatJSON)
	}

	// Health address default
	if cfg.Health.Address != "127.0.0.1:9090" {
		t.Errorf("health.address: got %q, want 127.0.0.1:9090", cfg.Health.Address)
	}
}

func TestParse_FileRuleDefaults(t *testing.T) {
	ca, cert, key := createCertFiles(t)
	yaml := `
dashboard:
  endpoint: "dashboard.example.com:443"
  tls:
    ca_cert: "` + ca + `"
    agent_cert: "` + cert + `"
    agent_key: "` + key + `"
rules:
  files:
    - name: no-severity-no-events
      path: /tmp/test
`
	cfg, err := config.Parse([]byte(yaml))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	r := cfg.Rules.Files[0]
	if r.Severity != config.SeverityWarn {
		t.Errorf("file rule severity default: got %q, want WARN", r.Severity)
	}
	if len(r.Events) == 0 {
		t.Error("file rule events should default to [write, create, delete]")
	}
}

func TestParse_NetworkRuleDefaults(t *testing.T) {
	ca, cert, key := createCertFiles(t)
	yaml := `
dashboard:
  endpoint: "dashboard.example.com:443"
  tls:
    ca_cert: "` + ca + `"
    agent_cert: "` + cert + `"
    agent_key: "` + key + `"
rules:
  networks:
    - name: ssh-honeypot
      port: 2222
`
	cfg, err := config.Parse([]byte(yaml))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	r := cfg.Rules.Networks[0]
	if r.Protocol != config.NetworkProtocolTCP {
		t.Errorf("network rule protocol default: got %q, want tcp", r.Protocol)
	}
	if r.Direction != "inbound" {
		t.Errorf("network rule direction default: got %q, want inbound", r.Direction)
	}
	if r.Severity != config.SeverityWarn {
		t.Errorf("network rule severity default: got %q, want WARN", r.Severity)
	}
}

func TestParse_ProcessRuleDefaults(t *testing.T) {
	ca, cert, key := createCertFiles(t)
	yaml := `
dashboard:
  endpoint: "dashboard.example.com:443"
  tls:
    ca_cert: "` + ca + `"
    agent_cert: "` + cert + `"
    agent_key: "` + key + `"
rules:
  processes:
    - name: netcat-watch
      process_name: nc
`
	cfg, err := config.Parse([]byte(yaml))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	r := cfg.Rules.Processes[0]
	if r.Severity != config.SeverityWarn {
		t.Errorf("process rule severity default: got %q, want WARN", r.Severity)
	}
}

func TestParse_ExplicitValues(t *testing.T) {
	ca, cert, key := createCertFiles(t)
	yaml := `
hostname: my-server
agent_version: "1.2.3"

dashboard:
  endpoint: "dashboard.corp:9443"
  tls:
    ca_cert: "` + ca + `"
    agent_cert: "` + cert + `"
    agent_key: "` + key + `"
  reconnect_delay: 10s
  reconnect_max_delay: 10m
  dial_timeout: 60s

queue:
  path: /var/lib/tripwire/q.db
  max_depth: 5000
  flush_interval: 2s

audit:
  path: /var/log/tripwire/audit.log
  max_size_bytes: 104857600

logging:
  level: debug
  format: console
  file_path: /var/log/tripwire/agent.log

health:
  enabled: true
  address: "0.0.0.0:9090"

rules:
  files:
    - name: passwd-watch
      path: /etc/passwd
      recursive: false
      events: [read, write]
      severity: CRITICAL
  networks:
    - name: honeypot-ssh
      port: 2222
      protocol: tcp
      direction: inbound
      severity: CRITICAL
  processes:
    - name: netcat
      process_name: nc
      match_args: "-e"
      severity: CRITICAL
`
	cfg, err := config.Parse([]byte(yaml))
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if cfg.Hostname != "my-server" {
		t.Errorf("hostname: got %q, want my-server", cfg.Hostname)
	}
	if cfg.Dashboard.Endpoint != "dashboard.corp:9443" {
		t.Errorf("endpoint: got %q", cfg.Dashboard.Endpoint)
	}
	if cfg.Dashboard.ReconnectDelay != 10*time.Second {
		t.Errorf("reconnect_delay: got %v, want 10s", cfg.Dashboard.ReconnectDelay)
	}
	if cfg.Queue.MaxDepth != 5000 {
		t.Errorf("queue.max_depth: got %d, want 5000", cfg.Queue.MaxDepth)
	}
	if cfg.Logging.Level != config.LogLevelDebug {
		t.Errorf("logging.level: got %q, want debug", cfg.Logging.Level)
	}
	if cfg.Health.Address != "0.0.0.0:9090" {
		t.Errorf("health.address: got %q", cfg.Health.Address)
	}
	if cfg.Rules.Files[0].Severity != config.SeverityCritical {
		t.Errorf("file rule severity: got %q", cfg.Rules.Files[0].Severity)
	}
	if cfg.Rules.Processes[0].MatchArgs != "-e" {
		t.Errorf("process rule match_args: got %q", cfg.Rules.Processes[0].MatchArgs)
	}
}

// ---------------------------------------------------------------------------
// Parse – invalid YAML
// ---------------------------------------------------------------------------

func TestParse_InvalidYAML(t *testing.T) {
	_, err := config.Parse([]byte("}{invalid yaml{"))
	if err == nil {
		t.Fatal("expected error for invalid YAML, got nil")
	}
}

func TestParse_UnknownField(t *testing.T) {
	_, err := config.Parse([]byte(`unknown_field: oops`))
	if err == nil {
		t.Fatal("expected error for unknown field, got nil")
	}
}

// ---------------------------------------------------------------------------
// ParseFile – file I/O
// ---------------------------------------------------------------------------

func TestParseFile_MissingFile(t *testing.T) {
	_, err := config.ParseFile("/does/not/exist/config.yaml")
	if err == nil {
		t.Fatal("expected error for missing file, got nil")
	}
}

func TestParseFile_ValidFile(t *testing.T) {
	ca, cert, key := createCertFiles(t)
	path := writeTempFile(t, "config.yaml", minimalValidYAML(ca, cert, key))

	cfg, err := config.ParseFile(path)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg == nil {
		t.Fatal("expected non-nil config")
	}
}

// ---------------------------------------------------------------------------
// Validation – dashboard
// ---------------------------------------------------------------------------

func TestValidate_MissingDashboardEndpoint(t *testing.T) {
	ca, cert, key := createCertFiles(t)
	yaml := `
dashboard:
  endpoint: ""
  tls:
    ca_cert: "` + ca + `"
    agent_cert: "` + cert + `"
    agent_key: "` + key + `"
rules:
  files:
    - name: test
      path: /etc/passwd
`
	_, err := config.Parse([]byte(yaml))
	assertContainsError(t, err, "dashboard.endpoint")
}

func TestValidate_InvalidDashboardEndpoint(t *testing.T) {
	ca, cert, key := createCertFiles(t)
	yaml := `
dashboard:
  endpoint: "not-a-valid-endpoint"
  tls:
    ca_cert: "` + ca + `"
    agent_cert: "` + cert + `"
    agent_key: "` + key + `"
rules:
  files:
    - name: test
      path: /etc/passwd
`
	_, err := config.Parse([]byte(yaml))
	assertContainsError(t, err, "dashboard.endpoint")
}

func TestValidate_MissingCACert(t *testing.T) {
	_, cert, key := createCertFiles(t)
	yaml := `
dashboard:
  endpoint: "dashboard.example.com:443"
  tls:
    ca_cert: ""
    agent_cert: "` + cert + `"
    agent_key: "` + key + `"
rules:
  files:
    - name: test
      path: /etc/passwd
`
	_, err := config.Parse([]byte(yaml))
	assertContainsError(t, err, "dashboard.tls.ca_cert")
}

func TestValidate_NonExistentCertFile(t *testing.T) {
	_, cert, key := createCertFiles(t)
	yaml := `
dashboard:
  endpoint: "dashboard.example.com:443"
  tls:
    ca_cert: "/does/not/exist/ca.crt"
    agent_cert: "` + cert + `"
    agent_key: "` + key + `"
rules:
  files:
    - name: test
      path: /etc/passwd
`
	_, err := config.Parse([]byte(yaml))
	assertContainsError(t, err, "dashboard.tls.ca_cert")
}

func TestValidate_ReconnectMaxLessThanDelay(t *testing.T) {
	ca, cert, key := createCertFiles(t)
	yaml := `
dashboard:
  endpoint: "dashboard.example.com:443"
  tls:
    ca_cert: "` + ca + `"
    agent_cert: "` + cert + `"
    agent_key: "` + key + `"
  reconnect_delay: 60s
  reconnect_max_delay: 10s
rules:
  files:
    - name: test
      path: /etc/passwd
`
	_, err := config.Parse([]byte(yaml))
	assertContainsError(t, err, "reconnect_max_delay")
}

// ---------------------------------------------------------------------------
// Validation – rules
// ---------------------------------------------------------------------------

func TestValidate_NoRules(t *testing.T) {
	ca, cert, key := createCertFiles(t)
	yaml := `
dashboard:
  endpoint: "dashboard.example.com:443"
  tls:
    ca_cert: "` + ca + `"
    agent_cert: "` + cert + `"
    agent_key: "` + key + `"
rules: {}
`
	_, err := config.Parse([]byte(yaml))
	assertContainsError(t, err, "at least one tripwire rule")
}

func TestValidate_FileRule_EmptyName(t *testing.T) {
	ca, cert, key := createCertFiles(t)
	yaml := `
dashboard:
  endpoint: "dashboard.example.com:443"
  tls:
    ca_cert: "` + ca + `"
    agent_cert: "` + cert + `"
    agent_key: "` + key + `"
rules:
  files:
    - name: ""
      path: /etc/passwd
`
	_, err := config.Parse([]byte(yaml))
	assertContainsError(t, err, "name must not be empty")
}

func TestValidate_FileRule_EmptyPath(t *testing.T) {
	ca, cert, key := createCertFiles(t)
	yaml := `
dashboard:
  endpoint: "dashboard.example.com:443"
  tls:
    ca_cert: "` + ca + `"
    agent_cert: "` + cert + `"
    agent_key: "` + key + `"
rules:
  files:
    - name: test
      path: ""
`
	_, err := config.Parse([]byte(yaml))
	assertContainsError(t, err, "path must not be empty")
}

func TestValidate_FileRule_DuplicateName(t *testing.T) {
	ca, cert, key := createCertFiles(t)
	yaml := `
dashboard:
  endpoint: "dashboard.example.com:443"
  tls:
    ca_cert: "` + ca + `"
    agent_cert: "` + cert + `"
    agent_key: "` + key + `"
rules:
  files:
    - name: dupe
      path: /etc/passwd
    - name: dupe
      path: /etc/shadow
`
	_, err := config.Parse([]byte(yaml))
	assertContainsError(t, err, "duplicated")
}

func TestValidate_FileRule_InvalidEvent(t *testing.T) {
	ca, cert, key := createCertFiles(t)
	yaml := `
dashboard:
  endpoint: "dashboard.example.com:443"
  tls:
    ca_cert: "` + ca + `"
    agent_cert: "` + cert + `"
    agent_key: "` + key + `"
rules:
  files:
    - name: test
      path: /etc/passwd
      events: [explode]
`
	_, err := config.Parse([]byte(yaml))
	assertContainsError(t, err, "events[0]")
}

func TestValidate_FileRule_InvalidSeverityAtParseTime(t *testing.T) {
	ca, cert, key := createCertFiles(t)
	yaml := `
dashboard:
  endpoint: "dashboard.example.com:443"
  tls:
    ca_cert: "` + ca + `"
    agent_cert: "` + cert + `"
    agent_key: "` + key + `"
rules:
  files:
    - name: test
      path: /etc/passwd
      severity: BANANA
`
	_, err := config.Parse([]byte(yaml))
	if err == nil {
		t.Fatal("expected error for invalid severity BANANA, got nil")
	}
}

func TestValidate_NetworkRule_InvalidPort_Zero(t *testing.T) {
	ca, cert, key := createCertFiles(t)
	yaml := `
dashboard:
  endpoint: "dashboard.example.com:443"
  tls:
    ca_cert: "` + ca + `"
    agent_cert: "` + cert + `"
    agent_key: "` + key + `"
rules:
  networks:
    - name: bad-port
      port: 0
`
	_, err := config.Parse([]byte(yaml))
	assertContainsError(t, err, "port")
}

func TestValidate_NetworkRule_InvalidPort_TooLarge(t *testing.T) {
	ca, cert, key := createCertFiles(t)
	yaml := `
dashboard:
  endpoint: "dashboard.example.com:443"
  tls:
    ca_cert: "` + ca + `"
    agent_cert: "` + cert + `"
    agent_key: "` + key + `"
rules:
  networks:
    - name: bad-port
      port: 99999
`
	_, err := config.Parse([]byte(yaml))
	assertContainsError(t, err, "port")
}

func TestValidate_NetworkRule_InvalidProtocol(t *testing.T) {
	ca, cert, key := createCertFiles(t)
	yaml := `
dashboard:
  endpoint: "dashboard.example.com:443"
  tls:
    ca_cert: "` + ca + `"
    agent_cert: "` + cert + `"
    agent_key: "` + key + `"
rules:
  networks:
    - name: test
      port: 8080
      protocol: icmp
`
	_, err := config.Parse([]byte(yaml))
	assertContainsError(t, err, "protocol")
}

func TestValidate_NetworkRule_InvalidDirection(t *testing.T) {
	ca, cert, key := createCertFiles(t)
	yaml := `
dashboard:
  endpoint: "dashboard.example.com:443"
  tls:
    ca_cert: "` + ca + `"
    agent_cert: "` + cert + `"
    agent_key: "` + key + `"
rules:
  networks:
    - name: test
      port: 8080
      direction: sideways
`
	_, err := config.Parse([]byte(yaml))
	assertContainsError(t, err, "direction")
}

func TestValidate_ProcessRule_EmptyProcessName(t *testing.T) {
	ca, cert, key := createCertFiles(t)
	yaml := `
dashboard:
  endpoint: "dashboard.example.com:443"
  tls:
    ca_cert: "` + ca + `"
    agent_cert: "` + cert + `"
    agent_key: "` + key + `"
rules:
  processes:
    - name: test
      process_name: ""
`
	_, err := config.Parse([]byte(yaml))
	assertContainsError(t, err, "process_name must not be empty")
}

func TestValidate_ProcessRule_DuplicateName(t *testing.T) {
	ca, cert, key := createCertFiles(t)
	yaml := `
dashboard:
  endpoint: "dashboard.example.com:443"
  tls:
    ca_cert: "` + ca + `"
    agent_cert: "` + cert + `"
    agent_key: "` + key + `"
rules:
  processes:
    - name: dupe
      process_name: nc
    - name: dupe
      process_name: ncat
`
	_, err := config.Parse([]byte(yaml))
	assertContainsError(t, err, "duplicated")
}

// ---------------------------------------------------------------------------
// Validate – multiple errors reported together
// ---------------------------------------------------------------------------

func TestValidate_MultipleErrors(t *testing.T) {
	cfg := &config.AgentConfig{
		// deliberately leave many required fields blank to collect multiple errors
		Dashboard: config.DashboardConfig{
			Endpoint:          "",              // missing
			ReconnectDelay:    5 * time.Second, // valid
			ReconnectMaxDelay: 5 * time.Minute, // valid
			DialTimeout:       30 * time.Second,
		},
		Queue: config.QueueConfig{
			Path:          "/tmp/q.db",
			FlushInterval: 5 * time.Second,
			MaxDepth:      -1, // invalid
		},
		Logging: config.LoggingConfig{
			Level:  config.LogLevelInfo,
			Format: config.LogFormatJSON,
		},
		Health: config.HealthConfig{
			Enabled: false,
			Address: "127.0.0.1:9090",
		},
		Audit: config.AuditConfig{Path: "/tmp/audit.log"},
	}
	errs := config.Validate(cfg)
	if len(errs) < 2 {
		t.Fatalf("expected multiple validation errors, got %d: %v", len(errs), errs)
	}
}

// ---------------------------------------------------------------------------
// Severity – case normalisation
// ---------------------------------------------------------------------------

func TestSeverity_CaseNormalisation(t *testing.T) {
	cases := []struct {
		input string
		want  config.Severity
	}{
		{"info", config.SeverityInfo},
		{"INFO", config.SeverityInfo},
		{"Info", config.SeverityInfo},
		{"warn", config.SeverityWarn},
		{"WARN", config.SeverityWarn},
		{"critical", config.SeverityCritical},
		{"CRITICAL", config.SeverityCritical},
	}
	for _, tc := range cases {
		t.Run(tc.input, func(t *testing.T) {
			ca, cert, key := createCertFiles(t)
			yaml := `
dashboard:
  endpoint: "dashboard.example.com:443"
  tls:
    ca_cert: "` + ca + `"
    agent_cert: "` + cert + `"
    agent_key: "` + key + `"
rules:
  files:
    - name: test
      path: /etc/passwd
      severity: ` + tc.input + `
`
			cfg, err := config.Parse([]byte(yaml))
			if err != nil {
				t.Fatalf("unexpected error for severity %q: %v", tc.input, err)
			}
			if cfg.Rules.Files[0].Severity != tc.want {
				t.Errorf("severity: got %q, want %q", cfg.Rules.Files[0].Severity, tc.want)
			}
		})
	}
}

// ---------------------------------------------------------------------------
// Health address validation
// ---------------------------------------------------------------------------

func TestValidate_Health_InvalidAddress(t *testing.T) {
	ca, cert, key := createCertFiles(t)
	yaml := `
dashboard:
  endpoint: "dashboard.example.com:443"
  tls:
    ca_cert: "` + ca + `"
    agent_cert: "` + cert + `"
    agent_key: "` + key + `"
health:
  enabled: true
  address: "not-valid"
rules:
  files:
    - name: test
      path: /etc/passwd
`
	_, err := config.Parse([]byte(yaml))
	assertContainsError(t, err, "health.address")
}

func TestValidate_Health_DisabledSkipsAddressCheck(t *testing.T) {
	ca, cert, key := createCertFiles(t)
	yaml := `
dashboard:
  endpoint: "dashboard.example.com:443"
  tls:
    ca_cert: "` + ca + `"
    agent_cert: "` + cert + `"
    agent_key: "` + key + `"
health:
  enabled: false
  address: "not-valid"
rules:
  files:
    - name: test
      path: /etc/passwd
`
	_, err := config.Parse([]byte(yaml))
	if err != nil {
		t.Fatalf("unexpected error (health disabled so bad address should be ignored): %v", err)
	}
}

// ---------------------------------------------------------------------------
// helper
// ---------------------------------------------------------------------------

func assertContainsError(t *testing.T, err error, substr string) {
	t.Helper()
	if err == nil {
		t.Fatalf("expected error containing %q, got nil", substr)
	}
	if !strings.Contains(err.Error(), substr) {
		t.Fatalf("expected error to contain %q, got: %v", substr, err)
	}
}
