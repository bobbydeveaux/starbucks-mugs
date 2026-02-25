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
	"syscall"
	"time"

	"github.com/tripwire/agent/internal/agent"
	"github.com/tripwire/agent/internal/config"
)

func main() {
	configPath := flag.String("config", "/etc/tripwire/config.yaml", "path to the TripWire agent YAML configuration file")
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

	// Create agent orchestrator.
	// Real watcher/queue/transport implementations are registered here as
	// they are developed in subsequent sprints. For now the agent runs
	// without watchers (no-op mode) which is valid for the healthz check.
	ag := agent.New(cfg, logger)

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
