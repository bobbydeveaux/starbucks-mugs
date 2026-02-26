// Package grpc provides the gRPC server for the TripWire dashboard.
//
// # mTLS Configuration
//
// The server requires mutual TLS (mTLS): every connecting agent must present a
// valid client certificate signed by the configured CA.  The server itself also
// presents a certificate signed by the same CA so that agents can verify the
// dashboard identity.
//
// Certificate paths are supplied via [Config]:
//
//	Config{
//	    CertPath: "/etc/tripwire/server.crt",
//	    KeyPath:  "/etc/tripwire/server.key",
//	    CAPath:   "/etc/tripwire/ca.crt",
//	    Addr:     ":4443",
//	}
//
// # Agent Identity (Cert CN Extraction)
//
// The Common Name (CN) of the connecting agent's client certificate is the
// authoritative agent identity.  It is extracted from the peer's TLS
// connection state on every RPC call and injected into the request context by
// the [cnInterceptor].
//
// Downstream handlers retrieve the agent identity via [AgentCNFromContext]:
//
//	cn, ok := grpcserver.AgentCNFromContext(ctx)
//	if !ok {
//	    return nil, status.Error(codes.Unauthenticated, "missing agent identity")
//	}
//
// # Graceful Shutdown
//
// Call [Server.GracefulStop] (or the context-aware [Server.Serve]) to drain
// in-flight RPCs before closing the listener.  A hard stop is triggered if the
// context is cancelled before draining completes.
package grpc

import (
	"context"
	"crypto/tls"
	"crypto/x509"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"os"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/peer"
	"google.golang.org/grpc/status"

	alertpb "github.com/tripwire/agent/proto"
)

// contextKey is an unexported type for context keys in this package to avoid
// collisions with keys defined by other packages.
type contextKey int

const agentCNKey contextKey = 0

// AgentCNFromContext retrieves the agent Common Name injected by the CN
// interceptor.  It returns ("", false) when no CN is present (unauthenticated
// request or interceptor not in the chain).
func AgentCNFromContext(ctx context.Context) (string, bool) {
	cn, ok := ctx.Value(agentCNKey).(string)
	return cn, ok && cn != ""
}

// Config holds the TLS certificate and listener configuration for the gRPC
// server.
type Config struct {
	// CertPath is the path to the PEM-encoded server TLS certificate. Required.
	CertPath string

	// KeyPath is the path to the PEM-encoded server TLS private key. Required.
	KeyPath string

	// CAPath is the path to the PEM-encoded CA certificate used to verify
	// client (agent) certificates for mTLS. Required.
	CAPath string

	// Addr is the TCP address the gRPC server listens on (e.g. ":4443").
	// Defaults to ":4443" when empty.
	Addr string
}

// Server wraps a grpc.Server with lifecycle management and mTLS configuration.
type Server struct {
	cfg    Config
	logger *slog.Logger
	grpc   *grpc.Server
}

// New creates a new Server, loading TLS credentials from the paths in cfg and
// registering srv as the AlertService implementation.
//
// If cfg.Addr is empty it defaults to ":4443".
//
// The returned Server has not yet started listening; call [Server.Serve] to
// accept connections.
func New(cfg Config, logger *slog.Logger, srv alertpb.AlertServiceServer) (*Server, error) {
	if cfg.Addr == "" {
		cfg.Addr = ":4443"
	}

	creds, err := loadTLSCredentials(cfg)
	if err != nil {
		return nil, fmt.Errorf("grpc server: load TLS credentials: %w", err)
	}

	gs := grpc.NewServer(
		grpc.Creds(creds),
		grpc.ChainUnaryInterceptor(cnUnaryInterceptor(logger)),
		grpc.ChainStreamInterceptor(cnStreamInterceptor(logger)),
	)

	alertpb.RegisterAlertServiceServer(gs, srv)

	return &Server{
		cfg:    cfg,
		logger: logger,
		grpc:   gs,
	}, nil
}

// Serve starts listening on cfg.Addr and blocks until ctx is cancelled or an
// error occurs.  When ctx is cancelled Serve attempts a graceful drain.
func (s *Server) Serve(ctx context.Context) error {
	lis, err := net.Listen("tcp", s.cfg.Addr)
	if err != nil {
		return fmt.Errorf("grpc server: listen %s: %w", s.cfg.Addr, err)
	}

	s.logger.Info("gRPC server listening",
		slog.String("addr", s.cfg.Addr),
		slog.String("tls", "mTLS"),
	)

	return s.ServeOnListener(ctx, lis)
}

// ServeOnListener accepts gRPC connections on lis and blocks until ctx is
// cancelled or a fatal error occurs.  It is useful in tests where the caller
// controls the listener (e.g. obtained from net.Listen("tcp", "127.0.0.1:0")).
//
// When ctx is cancelled a graceful stop is initiated; the method returns only
// after all in-flight RPCs have completed.
func (s *Server) ServeOnListener(ctx context.Context, lis net.Listener) error {
	// Start the gRPC server in a background goroutine.
	servErrCh := make(chan error, 1)
	go func() {
		if err := s.grpc.Serve(lis); err != nil && !errors.Is(err, grpc.ErrServerStopped) {
			servErrCh <- err
		}
		close(servErrCh)
	}()

	// Wait for context cancellation or a fatal server error.
	select {
	case <-ctx.Done():
		s.logger.Info("gRPC server: context cancelled, initiating graceful stop")
		s.grpc.GracefulStop()
	case err := <-servErrCh:
		if err != nil {
			return fmt.Errorf("grpc server: serve: %w", err)
		}
		return nil
	}

	// Wait for the graceful stop to complete.
	if err := <-servErrCh; err != nil {
		return fmt.Errorf("grpc server: serve after graceful stop: %w", err)
	}
	return nil
}

// GracefulStop signals the gRPC server to stop accepting new connections and
// blocks until all active RPCs have finished.
func (s *Server) GracefulStop() {
	s.grpc.GracefulStop()
}

// Stop forcefully terminates all active RPCs and closes the listener.
// Prefer GracefulStop for clean shutdowns.
func (s *Server) Stop() {
	s.grpc.Stop()
}

// ─── TLS helpers ─────────────────────────────────────────────────────────────

// loadTLSCredentials reads the server certificate+key and CA certificate from
// the paths in cfg and returns gRPC transport credentials configured for mTLS.
//
// The returned credentials require every client (agent) to present a
// certificate signed by the CA; connections without a valid client cert are
// rejected at the TLS handshake.
func loadTLSCredentials(cfg Config) (credentials.TransportCredentials, error) {
	// Load server certificate and private key.
	serverCert, err := tls.LoadX509KeyPair(cfg.CertPath, cfg.KeyPath)
	if err != nil {
		return nil, fmt.Errorf("load server cert/key (%s, %s): %w", cfg.CertPath, cfg.KeyPath, err)
	}

	// Load the CA certificate for verifying client (agent) certificates.
	caPEM, err := os.ReadFile(cfg.CAPath)
	if err != nil {
		return nil, fmt.Errorf("read CA cert %s: %w", cfg.CAPath, err)
	}
	caPool := x509.NewCertPool()
	if !caPool.AppendCertsFromPEM(caPEM) {
		return nil, fmt.Errorf("parse CA cert from %s: no certificates found", cfg.CAPath)
	}

	tlsConfig := &tls.Config{
		// Present the server certificate to connecting agents.
		Certificates: []tls.Certificate{serverCert},

		// Require clients to present a certificate (mTLS).
		ClientAuth: tls.RequireAndVerifyClientCert,

		// Verify client certificates against our CA pool.
		ClientCAs: caPool,

		// Enforce TLS 1.2 minimum for security.
		MinVersion: tls.VersionTLS12,
	}

	return credentials.NewTLS(tlsConfig), nil
}

// ─── CN extraction interceptors ──────────────────────────────────────────────

// extractCN retrieves the client certificate Common Name from the TLS peer
// information stored in ctx by the gRPC transport.
//
// It returns ("", errNoCert) when the peer has no client certificate, which
// should not happen when mTLS is properly enforced at the transport layer but
// is guarded against here for defence-in-depth.
func extractCN(ctx context.Context) (string, error) {
	p, ok := peer.FromContext(ctx)
	if !ok {
		return "", errors.New("no peer in context")
	}

	tlsInfo, ok := p.AuthInfo.(credentials.TLSInfo)
	if !ok {
		return "", errors.New("peer auth info is not TLSInfo")
	}

	if len(tlsInfo.State.VerifiedChains) == 0 || len(tlsInfo.State.VerifiedChains[0]) == 0 {
		return "", errors.New("no verified client certificate chain")
	}

	leaf := tlsInfo.State.VerifiedChains[0][0]
	if leaf.Subject.CommonName == "" {
		return "", errors.New("client certificate has empty Common Name")
	}

	return leaf.Subject.CommonName, nil
}

// cnUnaryInterceptor is a gRPC unary server interceptor that extracts the
// client certificate CN and injects it into the request context.  If the CN
// cannot be extracted the RPC is rejected with codes.Unauthenticated.
func cnUnaryInterceptor(logger *slog.Logger) grpc.UnaryServerInterceptor {
	return func(ctx context.Context, req any, info *grpc.UnaryServerInfo, handler grpc.UnaryHandler) (any, error) {
		cn, err := extractCN(ctx)
		if err != nil {
			logger.Warn("gRPC: failed to extract client cert CN",
				slog.String("method", info.FullMethod),
				slog.String("error", err.Error()),
			)
			return nil, status.Errorf(codes.Unauthenticated, "client certificate CN extraction failed: %v", err)
		}

		logger.Debug("gRPC: authenticated agent",
			slog.String("method", info.FullMethod),
			slog.String("agent_cn", cn),
		)

		ctx = context.WithValue(ctx, agentCNKey, cn)
		return handler(ctx, req)
	}
}

// cnStreamInterceptor is a gRPC streaming server interceptor that extracts the
// client certificate CN and injects it into the stream context.  If the CN
// cannot be extracted the stream is rejected with codes.Unauthenticated.
func cnStreamInterceptor(logger *slog.Logger) grpc.StreamServerInterceptor {
	return func(srv any, ss grpc.ServerStream, info *grpc.StreamServerInfo, handler grpc.StreamHandler) error {
		ctx := ss.Context()
		cn, err := extractCN(ctx)
		if err != nil {
			logger.Warn("gRPC: failed to extract client cert CN",
				slog.String("method", info.FullMethod),
				slog.String("error", err.Error()),
			)
			return status.Errorf(codes.Unauthenticated, "client certificate CN extraction failed: %v", err)
		}

		logger.Debug("gRPC: authenticated agent stream",
			slog.String("method", info.FullMethod),
			slog.String("agent_cn", cn),
		)

		wrapped := &cnServerStream{ServerStream: ss, ctx: context.WithValue(ctx, agentCNKey, cn)}
		return handler(srv, wrapped)
	}
}

// cnServerStream wraps a grpc.ServerStream with a context that carries the
// agent CN.
type cnServerStream struct {
	grpc.ServerStream
	ctx context.Context
}

func (s *cnServerStream) Context() context.Context { return s.ctx }
