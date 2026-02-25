package config_test

import (
	"os"
	"path/filepath"
	"strings"
	"testing"

	"github.com/tripwire/agent/internal/config"
)

// writeTemp writes content to a temp file and returns its path.
func writeTemp(t *testing.T, content string) string {
	t.Helper()
	f, err := os.CreateTemp(t.TempDir(), "config-*.yaml")
	if err != nil {
		t.Fatalf("create temp file: %v", err)
	}
	if _, err := f.WriteString(content); err != nil {
		t.Fatalf("write temp file: %v", err)
	}
	f.Close()
	return f.Name()
}

const validYAML = `
dashboard_addr: "dashboard.example.com:4443"
tls:
  cert_path: "/etc/tripwire/agent.crt"
  key_path:  "/etc/tripwire/agent.key"
  ca_path:   "/etc/tripwire/ca.crt"
log_level: debug
health_addr: "127.0.0.1:9001"
agent_version: "v0.1.0"
rules:
  - name: etc-passwd-watch
    type: FILE
    target: "/etc/passwd"
    severity: CRITICAL
  - name: ssh-port-watch
    type: NETWORK
    target: "22"
    severity: WARN
`

func TestLoadConfig_Valid(t *testing.T) {
	path := writeTemp(t, validYAML)
	cfg, err := config.LoadConfig(path)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if cfg.DashboardAddr != "dashboard.example.com:4443" {
		t.Errorf("DashboardAddr = %q, want %q", cfg.DashboardAddr, "dashboard.example.com:4443")
	}
	if cfg.TLS.CertPath != "/etc/tripwire/agent.crt" {
		t.Errorf("TLS.CertPath = %q", cfg.TLS.CertPath)
	}
	if cfg.TLS.KeyPath != "/etc/tripwire/agent.key" {
		t.Errorf("TLS.KeyPath = %q", cfg.TLS.KeyPath)
	}
	if cfg.TLS.CAPath != "/etc/tripwire/ca.crt" {
		t.Errorf("TLS.CAPath = %q", cfg.TLS.CAPath)
	}
	if cfg.LogLevel != "debug" {
		t.Errorf("LogLevel = %q, want %q", cfg.LogLevel, "debug")
	}
	if cfg.HealthAddr != "127.0.0.1:9001" {
		t.Errorf("HealthAddr = %q, want %q", cfg.HealthAddr, "127.0.0.1:9001")
	}
	if cfg.AgentVersion != "v0.1.0" {
		t.Errorf("AgentVersion = %q", cfg.AgentVersion)
	}
	if len(cfg.Rules) != 2 {
		t.Fatalf("len(Rules) = %d, want 2", len(cfg.Rules))
	}
	if cfg.Rules[0].Name != "etc-passwd-watch" || cfg.Rules[0].Type != "FILE" {
		t.Errorf("Rules[0] = %+v", cfg.Rules[0])
	}
}

func TestLoadConfig_Defaults(t *testing.T) {
	// Omit log_level and health_addr to exercise default application.
	yaml := `
dashboard_addr: "dashboard.example.com:4443"
tls:
  cert_path: "/etc/tripwire/agent.crt"
  key_path:  "/etc/tripwire/agent.key"
  ca_path:   "/etc/tripwire/ca.crt"
`
	path := writeTemp(t, yaml)
	cfg, err := config.LoadConfig(path)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if cfg.LogLevel != "info" {
		t.Errorf("default LogLevel = %q, want %q", cfg.LogLevel, "info")
	}
	if cfg.HealthAddr != "127.0.0.1:9000" {
		t.Errorf("default HealthAddr = %q, want %q", cfg.HealthAddr, "127.0.0.1:9000")
	}
}

func TestLoadConfig_MissingDashboardAddr(t *testing.T) {
	yaml := `
tls:
  cert_path: "/etc/tripwire/agent.crt"
  key_path:  "/etc/tripwire/agent.key"
  ca_path:   "/etc/tripwire/ca.crt"
`
	path := writeTemp(t, yaml)
	_, err := config.LoadConfig(path)
	if err == nil {
		t.Fatal("expected error for missing dashboard_addr, got nil")
	}
	if !strings.Contains(err.Error(), "dashboard_addr") {
		t.Errorf("error %q does not mention dashboard_addr", err.Error())
	}
}

func TestLoadConfig_MissingCertPath(t *testing.T) {
	yaml := `
dashboard_addr: "dashboard.example.com:4443"
tls:
  key_path:  "/etc/tripwire/agent.key"
  ca_path:   "/etc/tripwire/ca.crt"
`
	path := writeTemp(t, yaml)
	_, err := config.LoadConfig(path)
	if err == nil {
		t.Fatal("expected error for missing tls.cert_path, got nil")
	}
	if !strings.Contains(err.Error(), "cert_path") {
		t.Errorf("error %q does not mention cert_path", err.Error())
	}
}

func TestLoadConfig_MissingKeyPath(t *testing.T) {
	yaml := `
dashboard_addr: "dashboard.example.com:4443"
tls:
  cert_path: "/etc/tripwire/agent.crt"
  ca_path:   "/etc/tripwire/ca.crt"
`
	path := writeTemp(t, yaml)
	_, err := config.LoadConfig(path)
	if err == nil {
		t.Fatal("expected error for missing tls.key_path, got nil")
	}
	if !strings.Contains(err.Error(), "key_path") {
		t.Errorf("error %q does not mention key_path", err.Error())
	}
}

func TestLoadConfig_MissingCAPath(t *testing.T) {
	yaml := `
dashboard_addr: "dashboard.example.com:4443"
tls:
  cert_path: "/etc/tripwire/agent.crt"
  key_path:  "/etc/tripwire/agent.key"
`
	path := writeTemp(t, yaml)
	_, err := config.LoadConfig(path)
	if err == nil {
		t.Fatal("expected error for missing tls.ca_path, got nil")
	}
	if !strings.Contains(err.Error(), "ca_path") {
		t.Errorf("error %q does not mention ca_path", err.Error())
	}
}

func TestLoadConfig_InvalidLogLevel(t *testing.T) {
	yaml := `
dashboard_addr: "dashboard.example.com:4443"
tls:
  cert_path: "/etc/tripwire/agent.crt"
  key_path:  "/etc/tripwire/agent.key"
  ca_path:   "/etc/tripwire/ca.crt"
log_level: "verbose"
`
	path := writeTemp(t, yaml)
	_, err := config.LoadConfig(path)
	if err == nil {
		t.Fatal("expected error for invalid log_level, got nil")
	}
	if !strings.Contains(err.Error(), "log_level") {
		t.Errorf("error %q does not mention log_level", err.Error())
	}
}

func TestLoadConfig_InvalidRuleType(t *testing.T) {
	yaml := `
dashboard_addr: "dashboard.example.com:4443"
tls:
  cert_path: "/etc/tripwire/agent.crt"
  key_path:  "/etc/tripwire/agent.key"
  ca_path:   "/etc/tripwire/ca.crt"
rules:
  - name: bad-rule
    type: DISK
    target: "/dev/sda"
    severity: INFO
`
	path := writeTemp(t, yaml)
	_, err := config.LoadConfig(path)
	if err == nil {
		t.Fatal("expected error for invalid rule type, got nil")
	}
	if !strings.Contains(err.Error(), "DISK") {
		t.Errorf("error %q does not mention invalid type %q", err.Error(), "DISK")
	}
}

func TestLoadConfig_FileNotFound(t *testing.T) {
	missingPath := filepath.Join(t.TempDir(), "nonexistent.yaml")
	_, err := config.LoadConfig(missingPath)
	if err == nil {
		t.Fatal("expected error for missing file, got nil")
	}
}

func TestLoadConfig_InvalidYAML(t *testing.T) {
	path := writeTemp(t, ":::invalid yaml:::")
	_, err := config.LoadConfig(path)
	if err == nil {
		t.Fatal("expected error for invalid YAML, got nil")
	}
}

func TestLoadConfig_RulesUnmarshalledCorrectly(t *testing.T) {
	yaml := `
dashboard_addr: "dashboard.example.com:4443"
tls:
  cert_path: "/etc/tripwire/agent.crt"
  key_path:  "/etc/tripwire/agent.key"
  ca_path:   "/etc/tripwire/ca.crt"
rules:
  - name: proc-watch
    type: PROCESS
    target: "bash"
    severity: INFO
  - name: net-watch
    type: NETWORK
    target: "443"
    severity: CRITICAL
`
	path := writeTemp(t, yaml)
	cfg, err := config.LoadConfig(path)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
	if len(cfg.Rules) != 2 {
		t.Fatalf("len(Rules) = %d, want 2", len(cfg.Rules))
	}
	r0 := cfg.Rules[0]
	if r0.Type != "PROCESS" || r0.Target != "bash" || r0.Severity != "INFO" {
		t.Errorf("Rules[0] = %+v", r0)
	}
	r1 := cfg.Rules[1]
	if r1.Type != "NETWORK" || r1.Target != "443" || r1.Severity != "CRITICAL" {
		t.Errorf("Rules[1] = %+v", r1)
	}
}
