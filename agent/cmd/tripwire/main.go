// Command tripwire is the TripWire agent binary.
// It reads a YAML configuration file and starts monitoring the host for
// tripwire events, forwarding alerts to the central dashboard.
//
// Usage:
//
//	tripwire start --config /etc/tripwire/config.yaml
//	tripwire validate --config /etc/tripwire/config.yaml
package main

import (
	"flag"
	"fmt"
	"os"

	"github.com/tripwire/agent/internal/config"
)

// Version is set at build time via -ldflags.
var Version = "dev"

func main() {
	if err := run(os.Args[1:]); err != nil {
		fmt.Fprintf(os.Stderr, "tripwire: %v\n", err)
		os.Exit(1)
	}
}

func run(args []string) error {
	if len(args) == 0 {
		return fmt.Errorf("usage: tripwire <start|validate> --config <path>")
	}

	sub := args[0]
	rest := args[1:]

	switch sub {
	case "start":
		return cmdStart(rest)
	case "validate":
		return cmdValidate(rest)
	case "version":
		fmt.Println(Version)
		return nil
	default:
		return fmt.Errorf("unknown command %q; use start, validate, or version", sub)
	}
}

func cmdStart(args []string) error {
	cfg, err := parseFlags(args)
	if err != nil {
		return err
	}
	fmt.Printf("tripwire %s starting on host %q\n", Version, cfg.Hostname)
	fmt.Printf("dashboard endpoint: %s\n", cfg.Dashboard.Endpoint)
	fmt.Printf("file rules: %d, network rules: %d, process rules: %d\n",
		len(cfg.Rules.Files), len(cfg.Rules.Networks), len(cfg.Rules.Processes))

	// TODO(sprint-1): wire up Agent orchestrator once implemented.
	fmt.Println("agent core not yet implemented — configuration loaded successfully")
	return nil
}

func cmdValidate(args []string) error {
	cfg, err := parseFlags(args)
	if err != nil {
		return err
	}
	fmt.Printf("configuration is valid (host: %s, rules: %d file / %d network / %d process)\n",
		cfg.Hostname,
		len(cfg.Rules.Files),
		len(cfg.Rules.Networks),
		len(cfg.Rules.Processes))
	return nil
}

func parseFlags(args []string) (*config.AgentConfig, error) {
	fs := flag.NewFlagSet("tripwire", flag.ContinueOnError)
	configPath := fs.String("config", "", "path to YAML configuration file (required)")
	if err := fs.Parse(args); err != nil {
		return nil, err
	}
	if *configPath == "" {
		return nil, fmt.Errorf("--config is required")
	}
	return config.ParseFile(*configPath)
}
