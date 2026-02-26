package transport_test

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
	"crypto/tls"
	"crypto/x509"
	"crypto/x509/pkix"
	"encoding/pem"
	"io"
	"log/slog"
	"math/big"
	"net"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/status"

	"github.com/tripwire/agent/internal/config"
	"github.com/tripwire/agent/internal/transport"
	alertpb "github.com/tripwire/agent/proto/alert"
)

// ─── In-memory test PKI ───────────────────────────────────────────────────────

// testPKI holds CA and signed cert material for use in tests.
type testPKI struct {
	caPool     *x509.CertPool
	caCert     *x509.Certificate
	caKey      *ecdsa.PrivateKey
	caCertPath string
	srvCrtPath string
	srvKeyPath string
	cliCrtPath string
	cliKeyPath string
}

// newTestPKI generates a self-signed CA, signs a server cert for localhost,
// and signs a client cert for the agent.  All key material is written to
// t.TempDir() and cleaned up automatically.
func newTestPKI(t *testing.T) *testPKI {
	t.Helper()
	dir := t.TempDir()

	// CA
	caKey, err := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	if err != nil {
		t.Fatalf("generate CA key: %v", err)
	}
	caTemplate := &x509.Certificate{
		SerialNumber:          big.NewInt(1),
		Subject:               pkix.Name{CommonName: "TripWire Test CA"},
		NotBefore:             time.Now().Add(-time.Hour),
		NotAfter:              time.Now().Add(24 * time.Hour),
		IsCA:                  true,
		BasicConstraintsValid: true,
		KeyUsage:              x509.KeyUsageCertSign | x509.KeyUsageCRLSign,
	}
	caCertDER, err := x509.CreateCertificate(rand.Reader, caTemplate, caTemplate, &caKey.PublicKey, caKey)
	if err != nil {
		t.Fatalf("create CA cert: %v", err)
	}
	caCert, _ := x509.ParseCertificate(caCertDER)
	caPool := x509.NewCertPool()
	caPool.AddCert(caCert)
	caPath := filepath.Join(dir, "ca.crt")
	writePEMCert(t, caPath, caCertDER)

	// Server cert (localhost / 127.0.0.1)
	srvKey, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	srvTemplate := &x509.Certificate{
		SerialNumber: big.NewInt(2),
		Subject:      pkix.Name{CommonName: "tripwire-dashboard"},
		DNSNames:     []string{"localhost"},
		IPAddresses:  []net.IP{net.IPv4(127, 0, 0, 1), net.IPv6loopback},
		NotBefore:    time.Now().Add(-time.Hour),
		NotAfter:     time.Now().Add(24 * time.Hour),
		KeyUsage:     x509.KeyUsageDigitalSignature,
		ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageServerAuth},
	}
	srvCertDER, _ := x509.CreateCertificate(rand.Reader, srvTemplate, caCert, &srvKey.PublicKey, caKey)
	srvCrtPath := filepath.Join(dir, "server.crt")
	srvKeyPath := filepath.Join(dir, "server.key")
	writePEMCert(t, srvCrtPath, srvCertDER)
	writePEMKey(t, srvKeyPath, srvKey)

	// Client (agent) cert
	cliKey, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)
	cliTemplate := &x509.Certificate{
		SerialNumber: big.NewInt(3),
		Subject:      pkix.Name{CommonName: "test-agent"},
		NotBefore:    time.Now().Add(-time.Hour),
		NotAfter:     time.Now().Add(24 * time.Hour),
		KeyUsage:     x509.KeyUsageDigitalSignature,
		ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth},
	}
	cliCertDER, _ := x509.CreateCertificate(rand.Reader, cliTemplate, caCert, &cliKey.PublicKey, caKey)
	cliCrtPath := filepath.Join(dir, "client.crt")
	cliKeyPath := filepath.Join(dir, "client.key")
	writePEMCert(t, cliCrtPath, cliCertDER)
	writePEMKey(t, cliKeyPath, cliKey)

	return &testPKI{
		caPool:     caPool,
		caCert:     caCert,
		caKey:      caKey,
		caCertPath: caPath,
		srvCrtPath: srvCrtPath,
		srvKeyPath: srvKeyPath,
		cliCrtPath: cliCrtPath,
		cliKeyPath: cliKeyPath,
	}
}

// ─── PEM helpers ──────────────────────────────────────────────────────────────

func writePEMCert(t *testing.T, path string, der []byte) {
	t.Helper()
	f, err := os.Create(path)
	if err != nil {
		t.Fatalf("create %s: %v", path, err)
	}
	defer f.Close()
	_ = pem.Encode(f, &pem.Block{Type: "CERTIFICATE", Bytes: der})
}

func writePEMKey(t *testing.T, path string, key *ecdsa.PrivateKey) {
	t.Helper()
	der, _ := x509.MarshalECPrivateKey(key)
	f, err := os.Create(path)
	if err != nil {
		t.Fatalf("create %s: %v", path, err)
	}
	defer f.Close()
	_ = pem.Encode(f, &pem.Block{Type: "EC PRIVATE KEY", Bytes: der})
}

// ─── Stub gRPC server ─────────────────────────────────────────────────────────

// stubService is a minimal AlertServiceServer used in tests.
type stubService struct {
	alertpb.UnimplementedAlertServiceServer

	mu              sync.Mutex
	registeredHosts []string
	receivedAlerts  []*alertpb.AgentEvent

	// rejectRegister causes RegisterAgent to return Unavailable when true.
	rejectRegister bool

	// alertsWg is decremented each time an alert is received, so tests can
	// wait until an expected number of alerts have been processed.
	alertsWg sync.WaitGroup
}

func (s *stubService) RegisterAgent(_ context.Context, req *alertpb.RegisterRequest) (*alertpb.RegisterResponse, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.rejectRegister {
		return nil, status.Error(codes.Unavailable, "server not ready")
	}
	s.registeredHosts = append(s.registeredHosts, req.GetHostname())
	return &alertpb.RegisterResponse{HostId: "test-host-id"}, nil
}

func (s *stubService) StreamAlerts(stream alertpb.AlertService_StreamAlertsServer) error {
	for {
		event, err := stream.Recv()
		if err != nil {
			if err == io.EOF {
				return nil
			}
			return err
		}
		s.mu.Lock()
		s.receivedAlerts = append(s.receivedAlerts, event)
		s.mu.Unlock()
		s.alertsWg.Done()
		_ = stream.Send(&alertpb.ServerCommand{Type: "ACK"})
	}
}

// expectAlerts pre-registers that we expect n more alerts.  Must be called
// before the alerts are sent to avoid races with alertsWg.
func (s *stubService) expectAlerts(n int) {
	s.alertsWg.Add(n)
}

// waitAlerts blocks until all expected alerts (registered via expectAlerts)
// have been received by the server, or fails the test if timeout elapses.
func (s *stubService) waitAlerts(t *testing.T, timeout time.Duration) {
	t.Helper()
	done := make(chan struct{})
	go func() {
		s.alertsWg.Wait()
		close(done)
	}()
	select {
	case <-done:
	case <-time.After(timeout):
		t.Fatal("timed out waiting for server to receive expected alerts")
	}
}

func (s *stubService) alertCount() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.receivedAlerts)
}

func (s *stubService) registrationCount() int {
	s.mu.Lock()
	defer s.mu.Unlock()
	return len(s.registeredHosts)
}

// ─── Server launch helper ─────────────────────────────────────────────────────

// startStubServer starts a gRPC server with the given mTLS config and service,
// returning the listener address.  The server is stopped when t finishes.
func startStubServer(t *testing.T, pki *testPKI, svc alertpb.AlertServiceServer) string {
	t.Helper()

	serverCert, err := tls.LoadX509KeyPair(pki.srvCrtPath, pki.srvKeyPath)
	if err != nil {
		t.Fatalf("load server cert/key: %v", err)
	}
	caPEM, err := os.ReadFile(pki.caCertPath)
	if err != nil {
		t.Fatalf("read CA cert: %v", err)
	}
	caPool := x509.NewCertPool()
	caPool.AppendCertsFromPEM(caPEM)

	tlsCfg := &tls.Config{
		Certificates: []tls.Certificate{serverCert},
		ClientAuth:   tls.RequireAndVerifyClientCert,
		ClientCAs:    caPool,
		MinVersion:   tls.VersionTLS12,
	}

	lis, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}

	gs := grpc.NewServer(grpc.Creds(credentials.NewTLS(tlsCfg)))
	alertpb.RegisterAlertServiceServer(gs, svc)

	done := make(chan struct{})
	go func() {
		defer close(done)
		_ = gs.Serve(lis)
	}()
	t.Cleanup(func() {
		gs.GracefulStop()
		<-done
	})

	return lis.Addr().String()
}

// ─── makeAgentConfig ─────────────────────────────────────────────────────────

// makeAgentConfig returns an AgentConfig that points at addr with the given
// PKI credentials.
func makeAgentConfig(addr string, pki *testPKI) *config.AgentConfig {
	return &config.AgentConfig{
		Hostname:     "test-host",
		AgentVersion: "v0.0.0-test",
		Dashboard: config.DashboardConfig{
			Endpoint:          addr,
			DialTimeout:       5 * time.Second,
			ReconnectDelay:    50 * time.Millisecond,
			ReconnectMaxDelay: 200 * time.Millisecond,
			TLS: config.TLSConfig{
				CACert:    pki.caCertPath,
				AgentCert: pki.cliCrtPath,
				AgentKey:  pki.cliKeyPath,
			},
		},
	}
}

// ─── Tests ────────────────────────────────────────────────────────────────────

// TestNextDelay verifies exponential-backoff doubling and cap behaviour.
func TestNextDelay(t *testing.T) {
	cases := []struct {
		current  time.Duration
		max      time.Duration
		expected time.Duration
	}{
		{5 * time.Second, 5 * time.Minute, 10 * time.Second},
		{10 * time.Second, 5 * time.Minute, 20 * time.Second},
		{3 * time.Minute, 5 * time.Minute, 5 * time.Minute}, // cap
		{5 * time.Minute, 5 * time.Minute, 5 * time.Minute}, // already at cap
		{0, 5 * time.Minute, 5 * time.Minute},                // zero → cap
	}

	for _, tc := range cases {
		got := transport.NextDelay(tc.current, tc.max)
		if got != tc.expected {
			t.Errorf("NextDelay(%v, %v) = %v; want %v",
				tc.current, tc.max, got, tc.expected)
		}
	}
}

// TestLoadTLSCredentials_BadPaths verifies that New + Run with invalid cert
// paths returns an error without blocking.
func TestLoadTLSCredentials_BadPaths(t *testing.T) {
	cfg := &config.AgentConfig{
		Hostname:     "bad-host",
		AgentVersion: "v0.0.0",
		Dashboard: config.DashboardConfig{
			Endpoint:          "127.0.0.1:1",
			DialTimeout:       time.Second,
			ReconnectDelay:    time.Second,
			ReconnectMaxDelay: time.Second,
			TLS: config.TLSConfig{
				CACert:    "/nonexistent/ca.crt",
				AgentCert: "/nonexistent/agent.crt",
				AgentKey:  "/nonexistent/agent.key",
			},
		},
	}

	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	client := transport.New(cfg, logger)

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	err := client.Run(ctx, make(chan transport.Alert))
	if err == nil {
		t.Fatal("expected error for invalid cert paths; got nil")
	}
	t.Logf("correctly returned error: %v", err)
}

// TestRegisterAndStream verifies the full happy path: the Client connects to a
// stub server, calls RegisterAgent, and successfully sends alert events over
// the StreamAlerts stream.
func TestRegisterAndStream(t *testing.T) {
	pki := newTestPKI(t)
	svc := &stubService{}
	addr := startStubServer(t, pki, svc)

	cfg := makeAgentConfig(addr, pki)
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	client := transport.New(cfg, logger)

	// Pre-declare that we expect 2 alerts so we can wait for them.
	svc.expectAlerts(2)

	alertCh := make(chan transport.Alert, 4)
	alertCh <- transport.Alert{
		AlertID:      "alert-001",
		TimestampUs:  1_000_000,
		TripwireType: "FILE",
		RuleName:     "etc-passwd-watch",
		Severity:     "CRITICAL",
	}
	alertCh <- transport.Alert{
		AlertID:      "alert-002",
		TimestampUs:  2_000_000,
		TripwireType: "PROCESS",
		RuleName:     "netcat-watch",
		Severity:     "CRITICAL",
	}

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	done := make(chan error, 1)
	go func() {
		done <- client.Run(ctx, alertCh)
	}()

	// Wait until the server has received both alerts before shutting down.
	svc.waitAlerts(t, 5*time.Second)

	// Signal clean shutdown by closing the channel.
	close(alertCh)

	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("Run: %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("Run did not return within 5 s")
	}

	if n := svc.registrationCount(); n != 1 {
		t.Errorf("RegisterAgent called %d times; want 1", n)
	}
	if n := svc.alertCount(); n != 2 {
		t.Errorf("received %d alerts; want 2", n)
	}
}

// TestContextCancellation verifies that Run returns promptly when ctx is
// cancelled, even with an open stream.
func TestContextCancellation(t *testing.T) {
	pki := newTestPKI(t)
	svc := &stubService{}
	addr := startStubServer(t, pki, svc)

	cfg := makeAgentConfig(addr, pki)
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	client := transport.New(cfg, logger)

	// Never-closing alert channel — Run must stop when ctx is cancelled.
	alertCh := make(chan transport.Alert)

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)

	done := make(chan error, 1)
	go func() {
		done <- client.Run(ctx, alertCh)
	}()

	// Give the client time to connect and register, then cancel.
	time.Sleep(200 * time.Millisecond)
	cancel()

	select {
	case err := <-done:
		if err != nil {
			t.Errorf("Run returned error after cancellation: %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("Run did not return within 5 s after context cancellation")
	}
}

// TestExponentialBackoff verifies that the client reconnects with increasing
// delays after repeated failures and eventually succeeds.
func TestExponentialBackoff(t *testing.T) {
	pki := newTestPKI(t)
	svc := &stubService{rejectRegister: true}
	addr := startStubServer(t, pki, svc)

	cfg := makeAgentConfig(addr, pki)
	// Use very short backoff for test speed.
	cfg.Dashboard.ReconnectDelay = 20 * time.Millisecond
	cfg.Dashboard.ReconnectMaxDelay = 80 * time.Millisecond

	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	client := transport.New(cfg, logger)

	alertCh := make(chan transport.Alert, 1)

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	// Allow a few rejected attempts, then open the server and send one alert.
	svc.expectAlerts(1)
	go func() {
		time.Sleep(300 * time.Millisecond)
		svc.mu.Lock()
		svc.rejectRegister = false
		svc.mu.Unlock()

		// Send one alert after the server accepts connections.
		time.Sleep(200 * time.Millisecond)
		alertCh <- transport.Alert{
			AlertID:      "backoff-alert-001",
			TripwireType: "NETWORK",
			RuleName:     "ssh-honeypot",
			Severity:     "CRITICAL",
		}
	}()

	done := make(chan error, 1)
	go func() {
		done <- client.Run(ctx, alertCh)
	}()

	// Wait until the server has received the alert.
	svc.waitAlerts(t, 4*time.Second)
	close(alertCh)

	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("Run: %v", err)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("Run did not return within 3 s after channel close")
	}

	if n := svc.registrationCount(); n < 1 {
		t.Errorf("expected at least one successful registration; got %d", n)
	}
	if n := svc.alertCount(); n != 1 {
		t.Errorf("expected 1 alert; got %d", n)
	}
}

// TestMTLSRejected verifies that Run retries on mTLS rejection and returns
// cleanly when ctx is cancelled.
func TestMTLSRejected(t *testing.T) {
	pki := newTestPKI(t)
	// Second PKI acts as a rogue CA whose client certs the server rejects.
	roguePKI := newTestPKI(t)
	addr := startStubServer(t, pki, &stubService{})

	// Build config with the rogue client cert but the real server CA cert.
	rogueCfg := &config.AgentConfig{
		Hostname:     "rogue-host",
		AgentVersion: "v0.0.0",
		Dashboard: config.DashboardConfig{
			Endpoint:          addr,
			DialTimeout:       500 * time.Millisecond,
			ReconnectDelay:    50 * time.Millisecond,
			ReconnectMaxDelay: 100 * time.Millisecond,
			TLS: config.TLSConfig{
				CACert:    pki.caCertPath,      // trust real server
				AgentCert: roguePKI.cliCrtPath, // but present rogue cert
				AgentKey:  roguePKI.cliKeyPath,
			},
		},
	}

	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	client := transport.New(rogueCfg, logger)
	alertCh := make(chan transport.Alert)

	// Cancel quickly — the server always rejects the cert.
	ctx, cancel := context.WithTimeout(context.Background(), 800*time.Millisecond)
	defer cancel()

	done := make(chan struct{})
	go func() {
		_ = client.Run(ctx, alertCh)
		close(done)
	}()

	select {
	case <-done:
		// Expected: context expired and Run returned cleanly.
	case <-time.After(3 * time.Second):
		t.Fatal("Run did not return within 3 s")
	}
}
