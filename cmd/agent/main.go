// Command agent is the TripWire agent binary. It loads a YAML configuration
// file, starts all monitoring components (watchers, local alert queue, and
// gRPC transport), exposes a /healthz liveness endpoint, and shuts down
// gracefully on SIGTERM or SIGINT.
package main

import (
	"context"
	"flag"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"runtime"
	"syscall"
	"time"

	"github.com/tripwire/agent/internal/agent"
	"github.com/tripwire/agent/internal/config"
	"github.com/tripwire/agent/internal/queue"
	"github.com/tripwire/agent/internal/transport"
	"github.com/tripwire/agent/internal/watcher"
)

// networkPollInterval is how frequently the NetworkWatcher polls /proc/net/*.
const networkPollInterval = time.Second

func main() {
	configPath := flag.String("config", "/etc/tripwire/config.yaml", "path to the TripWire agent YAML configuration file")
	queuePath := flag.String("queue-path", "/var/lib/tripwire/queue.db", "path to the local SQLite alert queue database")
	flag.Parse()

	// Load and validate configuration.
	cfg, err := config.LoadConfig(*configPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "tripwire-agent: %v\n", err)
		os.Exit(1)
	}

	// Initialise structured slog logger from config log level.
	logger := newLogger(cfg.LogLevel)
	slog.SetDefault(logger)

	logger.Info("configuration loaded",
		slog.String("config_path", *configPath),
		slog.String("dashboard_addr", cfg.DashboardAddr),
		slog.String("log_level", cfg.LogLevel),
		slog.String("health_addr", cfg.HealthAddr),
	)

	// Open the local SQLite alert queue.  The queue persists events across
	// restarts so that alerts are not lost if the transport is temporarily
	// unavailable.
	q, err := queue.New(*queuePath)
	if err != nil {
		logger.Error("failed to open alert queue", slog.String("path", *queuePath), slog.Any("error", err))
		os.Exit(1)
	}
	logger.Info("alert queue opened", slog.String("path", *queuePath), slog.Int("pending", q.Depth()))

	// Create the gRPC transport client.  It dials with mTLS, calls
	// RegisterAgent on each connect, drains the queue before forwarding live
	// events, and reconnects automatically on stream errors.
	grpcTransport := transport.New(
		transport.ClientConfig{
			Addr:         cfg.DashboardAddr,
			CertPath:     cfg.TLS.CertPath,
			KeyPath:      cfg.TLS.KeyPath,
			CAPath:       cfg.TLS.CAPath,
			Platform:     runtime.GOOS,
			AgentVersion: cfg.AgentVersion,
		},
		q,
		logger,
	)

	// Create agent orchestrator with all registered watchers.
	var agentOpts []agent.Option

	agentOpts = append(agentOpts, agent.WithQueue(q))
	agentOpts = append(agentOpts, agent.WithTransport(grpcTransport))

	// Instantiate a NetworkWatcher for all NETWORK-type rules.  The watcher
	// silently filters non-NETWORK rules, so it is always safe to create.
	netWatcher, err := agent.NewNetworkWatcher(cfg.Rules, logger, networkPollInterval)
	if err != nil {
		logger.Error("failed to create network watcher", slog.Any("error", err))
		os.Exit(1)
	}
	agentOpts = append(agentOpts, agent.WithWatchers(netWatcher))

	// Build the list of file watchers from configured rules and register them.
	if fileWatchers := buildFileWatchers(cfg, logger); len(fileWatchers) > 0 {
		agentOpts = append(agentOpts, agent.WithWatchers(fileWatchers...))
	}

	ag := agent.New(cfg, logger, agentOpts...)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Start the agent (wires together watchers, queue, transport).
	if err := ag.Start(ctx); err != nil {
		logger.Error("failed to start agent", slog.Any("error", err))
		os.Exit(1)
	}

	// Start the /healthz HTTP server.
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", ag.HealthzHandler)

	healthServer := &http.Server{
		Addr:         cfg.HealthAddr,
		Handler:      mux,
		ReadTimeout:  5 * time.Second,
		WriteTimeout: 5 * time.Second,
	}

	go func() {
		logger.Info("healthz server listening", slog.String("addr", cfg.HealthAddr))
		if err := healthServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			logger.Error("healthz server error", slog.Any("error", err))
		}
	}()

	// Block until SIGTERM or SIGINT.
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGTERM, syscall.SIGINT)
	sig := <-sigCh

	logger.Info("received shutdown signal", slog.String("signal", sig.String()))

	// Graceful shutdown: stop the agent first, then the HTTP server.
	ag.Stop()

	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer shutdownCancel()

	if err := healthServer.Shutdown(shutdownCtx); err != nil {
		logger.Warn("healthz server shutdown error", slog.Any("error", err))
	}

	logger.Info("tripwire agent exited cleanly")
}

// buildFileWatchers creates a FileWatcher for every FILE-type rule in the
// configuration. If no FILE rules are configured, an empty slice is returned.
func buildFileWatchers(cfg *config.Config, logger *slog.Logger) []agent.Watcher {
	var watchers []agent.Watcher
	for _, rule := range cfg.Rules {
		if rule.Type != "FILE" {
			continue
		}
		fw := watcher.NewFileWatcher(rule, logger)
		watchers = append(watchers, fw)
		logger.Info("registered file watcher",
			slog.String("rule", rule.Name),
			slog.String("target", rule.Target),
			slog.String("severity", rule.Severity),
		)
	}
	return watchers
}

// newLogger constructs a *slog.Logger that writes JSON-structured log records
// to stderr at the requested minimum level.
func newLogger(level string) *slog.Logger {
	var l slog.Level
	switch level {
	case "debug":
		l = slog.LevelDebug
	case "warn":
		l = slog.LevelWarn
	case "error":
		l = slog.LevelError
	default:
		l = slog.LevelInfo
	}
	return slog.New(slog.NewJSONHandler(os.Stderr, &slog.HandlerOptions{Level: l}))
}
