// Command server is the TripWire dashboard server binary. It loads a YAML
// configuration file, opens a PostgreSQL connection pool, starts the gRPC
// alert-ingestion service (with mTLS), exposes a REST API over HTTP/HTTPS,
// and shuts down gracefully on SIGTERM or SIGINT.
package main

import (
	"context"
	"crypto/rsa"
	"flag"
	"fmt"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	grpcserver "github.com/tripwire/agent/internal/server/grpc"
	"github.com/tripwire/agent/internal/server/rest"
	"github.com/tripwire/agent/internal/server/storage"
	alertpb "github.com/tripwire/agent/proto"
)

// serverConfig holds the parsed runtime configuration for the dashboard server.
// In a future sprint this will be loaded from a YAML file; for now flags suffice.
type serverConfig struct {
	// gRPC listener address (mTLS).
	GRPCAddr string

	// HTTP REST API listener address.
	HTTPAddr string

	// TLS certificate paths for the gRPC server (server identity + CA for
	// verifying agent client certs).
	CertPath string
	KeyPath  string
	CAPath   string

	// PostgreSQL DSN.
	DSN string

	// Path to the PEM-encoded RSA public key used to verify JWT tokens on
	// REST API requests.  Leave empty to disable JWT validation (dev only).
	JWTPublicKeyPath string

	// Log level: debug | info | warn | error.
	LogLevel string
}

func main() {
	var cfg serverConfig

	flag.StringVar(&cfg.GRPCAddr, "grpc-addr", ":4443", "gRPC listener address (mTLS)")
	flag.StringVar(&cfg.HTTPAddr, "http-addr", ":8080", "HTTP REST API listener address")
	flag.StringVar(&cfg.CertPath, "tls-cert", "/etc/tripwire/server.crt", "PEM server certificate path")
	flag.StringVar(&cfg.KeyPath, "tls-key", "/etc/tripwire/server.key", "PEM server private key path")
	flag.StringVar(&cfg.CAPath, "tls-ca", "/etc/tripwire/ca.crt", "PEM CA certificate path (verifies agent client certs)")
	flag.StringVar(&cfg.DSN, "dsn", "", "PostgreSQL DSN (e.g. postgres://user:pass@localhost/tripwire)")
	flag.StringVar(&cfg.JWTPublicKeyPath, "jwt-pubkey", "", "Path to PEM RSA public key for JWT validation (optional)")
	flag.StringVar(&cfg.LogLevel, "log-level", "info", "Log level: debug | info | warn | error")
	flag.Parse()

	logger := newLogger(cfg.LogLevel)
	slog.SetDefault(logger)

	logger.Info("tripwire dashboard server starting",
		slog.String("grpc_addr", cfg.GRPCAddr),
		slog.String("http_addr", cfg.HTTPAddr),
	)

	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// ── PostgreSQL storage ────────────────────────────────────────────────────
	var store *storage.Store
	if cfg.DSN != "" {
		var err error
		store, err = storage.New(ctx, cfg.DSN, 0, 0)
		if err != nil {
			logger.Error("failed to open storage", slog.Any("error", err))
			os.Exit(1)
		}
		defer store.Close(context.Background())
		logger.Info("PostgreSQL storage connected")
	} else {
		logger.Warn("no DSN configured; storage layer disabled (dev mode)")
	}

	// ── gRPC server (mTLS) ────────────────────────────────────────────────────
	grpcCfg := grpcserver.Config{
		Addr:     cfg.GRPCAddr,
		CertPath: cfg.CertPath,
		KeyPath:  cfg.KeyPath,
		CAPath:   cfg.CAPath,
	}

	// For now register the unimplemented server stub; the concrete
	// AlertService implementation is added in the next sprint task
	// (task-tripwire-cybersecurity-tool-feat-grpc-server-2).
	var alertSrv alertpb.AlertServiceServer = alertpb.UnimplementedAlertServiceServer{}

	grpcSrv, err := grpcserver.New(grpcCfg, logger, alertSrv)
	if err != nil {
		logger.Error("failed to create gRPC server", slog.Any("error", err))
		os.Exit(1)
	}

	// ── REST API server ───────────────────────────────────────────────────────
	var pubKey *rsa.PublicKey
	if cfg.JWTPublicKeyPath != "" {
		pem, err := os.ReadFile(cfg.JWTPublicKeyPath)
		if err != nil {
			logger.Error("failed to read JWT public key", slog.Any("error", err))
			os.Exit(1)
		}
		pubKey, err = rest.ParseRSAPublicKey(pem)
		if err != nil {
			logger.Error("failed to parse JWT public key", slog.Any("error", err))
			os.Exit(1)
		}
		logger.Info("JWT validation enabled")
	} else {
		logger.Warn("JWT_PUBLIC_KEY not configured; REST API authentication disabled (dev mode)")
	}

	var restStore rest.Store
	if store != nil {
		restStore = store
	}
	restSrv := rest.NewServer(restStore)
	httpHandler := rest.NewRouter(restSrv, pubKey)

	httpServer := &http.Server{
		Addr:         cfg.HTTPAddr,
		Handler:      httpHandler,
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 15 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	// ── Start servers ─────────────────────────────────────────────────────────

	// gRPC server goroutine.
	grpcErrCh := make(chan error, 1)
	go func() {
		if err := grpcSrv.Serve(ctx); err != nil {
			grpcErrCh <- fmt.Errorf("gRPC server: %w", err)
		}
		close(grpcErrCh)
	}()

	// HTTP server goroutine.
	httpErrCh := make(chan error, 1)
	go func() {
		logger.Info("HTTP REST server listening", slog.String("addr", cfg.HTTPAddr))
		if err := httpServer.ListenAndServe(); err != nil && err != http.ErrServerClosed {
			httpErrCh <- fmt.Errorf("HTTP server: %w", err)
		}
		close(httpErrCh)
	}()

	// ── Wait for shutdown signal or fatal error ────────────────────────────────
	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGTERM, syscall.SIGINT)

	select {
	case sig := <-sigCh:
		logger.Info("received shutdown signal", slog.String("signal", sig.String()))
	case err := <-grpcErrCh:
		if err != nil {
			logger.Error("gRPC server error", slog.Any("error", err))
		}
	case err := <-httpErrCh:
		if err != nil {
			logger.Error("HTTP server error", slog.Any("error", err))
		}
	}

	// ── Graceful shutdown ─────────────────────────────────────────────────────
	logger.Info("shutting down servers")
	cancel() // signals gRPC Serve to initiate graceful stop

	shutdownCtx, shutdownCancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer shutdownCancel()

	if err := httpServer.Shutdown(shutdownCtx); err != nil {
		logger.Warn("HTTP server shutdown error", slog.Any("error", err))
	}

	// Wait for gRPC server to drain.
	select {
	case err := <-grpcErrCh:
		if err != nil {
			logger.Warn("gRPC server drain error", slog.Any("error", err))
		}
	case <-shutdownCtx.Done():
		logger.Warn("gRPC graceful stop timed out; forcing stop")
		grpcSrv.Stop()
	}

	logger.Info("tripwire dashboard server exited cleanly")
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
