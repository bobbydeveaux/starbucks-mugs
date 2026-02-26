package transport_test

import (
	"context"
	"crypto/ecdsa"
	"crypto/elliptic"
	"crypto/rand"
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

	grpcserver "github.com/tripwire/agent/internal/server/grpc"
	"github.com/tripwire/agent/internal/transport"
	"github.com/tripwire/agent/internal/watcher"
	alertpb "github.com/tripwire/agent/proto/alert"
)

// ─── In-memory test PKI ───────────────────────────────────────────────────────

// testPKI holds an in-memory CA, a signed server certificate, and a signed
// agent (client) certificate written to a temporary directory.
type testPKI struct {
	dir        string
	caPool     *x509.CertPool
	caCert     *x509.Certificate
	caKey      *ecdsa.PrivateKey
	caCertPath string
	srvCrtPath string
	srvKeyPath string
	cliCrtPath string
	cliKeyPath string
}

// newTestPKI generates a self-signed CA, a server certificate (localhost /
// 127.0.0.1), and an agent client certificate.  All PEM files land in
// t.TempDir() and are cleaned up automatically.
func newTestPKI(t *testing.T) *testPKI {
	t.Helper()
	dir := t.TempDir()

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

	// Server certificate for localhost / 127.0.0.1.
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

	// Agent (client) certificate.
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
	cliCrtPath := filepath.Join(dir, "agent.crt")
	cliKeyPath := filepath.Join(dir, "agent.key")
	writePEMCert(t, cliCrtPath, cliCertDER)
	writePEMKey(t, cliKeyPath, cliKey)

	return &testPKI{
		dir:        dir,
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

// ─── PEM helpers ─────────────────────────────────────────────────────────────

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

// ─── Stub AlertService server ─────────────────────────────────────────────────

// captureService is a minimal AlertServiceServer that records everything it
// receives so tests can make assertions on it.
type captureService struct {
	alertpb.UnimplementedAlertServiceServer

	mu      sync.Mutex
	hostID  string            // assigned to every registrant
	lastCN  string            // CN from the most recent RegisterAgent call
	events  []*alertpb.AgentEvent // events received via StreamAlerts
}

func newCaptureService(hostID string) *captureService {
	return &captureService{hostID: hostID}
}

func (s *captureService) RegisterAgent(ctx context.Context, _ *alertpb.RegisterRequest) (*alertpb.RegisterResponse, error) {
	cn, _ := grpcserver.AgentCNFromContext(ctx)
	s.mu.Lock()
	s.lastCN = cn
	s.mu.Unlock()
	return &alertpb.RegisterResponse{HostId: s.hostID}, nil
}

func (s *captureService) StreamAlerts(stream alertpb.AlertService_StreamAlertsServer) error {
	for {
		evt, err := stream.Recv()
		if err == io.EOF {
			return nil
		}
		if err != nil {
			return err
		}
		s.mu.Lock()
		s.events = append(s.events, evt)
		s.mu.Unlock()

		// Send an ACK for every received event.
		if sendErr := stream.Send(&alertpb.ServerCommand{Type: "ACK"}); sendErr != nil {
			return sendErr
		}
	}
}

func (s *captureService) receivedEvents() []*alertpb.AgentEvent {
	s.mu.Lock()
	defer s.mu.Unlock()
	cp := make([]*alertpb.AgentEvent, len(s.events))
	copy(cp, s.events)
	return cp
}

// ─── Test server helpers ──────────────────────────────────────────────────────

// startTestServer starts an in-process gRPC server on a random OS-assigned
// port using the provided PKI and service implementation.  The server is
// stopped when t finishes.  Returns the "host:port" address.
func startTestServer(t *testing.T, pki *testPKI, svc alertpb.AlertServiceServer) string {
	t.Helper()

	lis, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}

	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	cfg := grpcserver.Config{
		CertPath: pki.srvCrtPath,
		KeyPath:  pki.srvKeyPath,
		CAPath:   pki.caCertPath,
	}
	srv, err := grpcserver.New(cfg, logger, svc)
	if err != nil {
		_ = lis.Close()
		t.Fatalf("grpcserver.New: %v", err)
	}

	ctx, cancel := context.WithCancel(context.Background())
	done := make(chan struct{})
	go func() {
		defer close(done)
		_ = srv.ServeOnListener(ctx, lis)
	}()

	t.Cleanup(func() {
		cancel()
		<-done
	})

	return lis.Addr().String()
}

// newTestTransport creates a transport.Config wired to the given PKI and
// dashboard address, with short backoff intervals suitable for tests.
func newTestTransport(t *testing.T, pki *testPKI, addr string) *transport.GRPCTransport {
	t.Helper()
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	cfg := transport.Config{
		DashboardAddr:  addr,
		CertPath:       pki.cliCrtPath,
		KeyPath:        pki.cliKeyPath,
		CAPath:         pki.caCertPath,
		InitialBackoff: 100 * time.Millisecond,
		MaxBackoff:     500 * time.Millisecond,
		DialTimeout:    5 * time.Second,
		AgentVersion:   "v0.0.1-test",
	}
	return transport.New(cfg, logger)
}

// ─── Tests ────────────────────────────────────────────────────────────────────

// TestGRPCTransport_LoadTLSCredentials_BadCert verifies that Start returns an
// error when the certificate files do not exist or are invalid.
func TestGRPCTransport_LoadTLSCredentials_BadCert(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	cfg := transport.Config{
		DashboardAddr: "127.0.0.1:9999",
		CertPath:      "/nonexistent/agent.crt",
		KeyPath:       "/nonexistent/agent.key",
		CAPath:        "/nonexistent/ca.crt",
	}
	tr := transport.New(cfg, logger)

	ctx := context.Background()
	err := tr.Start(ctx)
	if err == nil {
		tr.Stop()
		t.Fatal("expected error for missing cert files; got nil")
	}
	t.Logf("Start returned expected error: %v", err)
}

// TestGRPCTransport_SendBeforeStart verifies that Send returns an error when
// the transport has not yet established a stream.
func TestGRPCTransport_SendBeforeStart(t *testing.T) {
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	cfg := transport.Config{
		DashboardAddr: "127.0.0.1:9999",
		CertPath:      "/nonexistent/agent.crt",
		KeyPath:       "/nonexistent/agent.key",
		CAPath:        "/nonexistent/ca.crt",
	}
	tr := transport.New(cfg, logger)

	evt := watcher.AlertEvent{TripwireType: "FILE", RuleName: "test", Severity: "INFO", Timestamp: time.Now()}
	err := tr.Send(context.Background(), evt)
	if err == nil {
		t.Fatal("expected error from Send before Start; got nil")
	}
}

// TestGRPCTransport_ConnectsAndRegisters verifies that the transport dials
// the dashboard, performs the RegisterAgent handshake, and opens the
// StreamAlerts stream using mTLS.
func TestGRPCTransport_ConnectsAndRegisters(t *testing.T) {
	pki := newTestPKI(t)
	svc := newCaptureService("host-abc-123")
	addr := startTestServer(t, pki, svc)

	tr := newTestTransport(t, pki, addr)
	ctx, cancel := context.WithCancel(context.Background())

	if err := tr.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}

	// Wait for the transport to connect and register.
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		svc.mu.Lock()
		cn := svc.lastCN
		svc.mu.Unlock()
		if cn != "" {
			break
		}
		time.Sleep(50 * time.Millisecond)
	}

	svc.mu.Lock()
	lastCN := svc.lastCN
	svc.mu.Unlock()

	if lastCN == "" {
		t.Fatal("dashboard never received a RegisterAgent call")
	}
	t.Logf("dashboard registered agent with CN=%q", lastCN)

	cancel()
	tr.Stop()
}

// TestGRPCTransport_SendEventReachesServer verifies the full pipeline: Start,
// connect, send an AlertEvent, and confirm the dashboard receives it.
func TestGRPCTransport_SendEventReachesServer(t *testing.T) {
	pki := newTestPKI(t)
	svc := newCaptureService("host-send-test")
	addr := startTestServer(t, pki, svc)

	tr := newTestTransport(t, pki, addr)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := tr.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}
	defer tr.Stop()

	evt := watcher.AlertEvent{
		TripwireType: "FILE",
		RuleName:     "etc-passwd-watch",
		Severity:     "CRITICAL",
		Timestamp:    time.Now(),
		Detail:       map[string]any{"path": "/etc/passwd", "pid": 1234},
	}

	// Retry Send until the stream is established.
	deadline := time.Now().Add(5 * time.Second)
	var sendErr error
	for time.Now().Before(deadline) {
		if sendErr = tr.Send(ctx, evt); sendErr == nil {
			break
		}
		time.Sleep(50 * time.Millisecond)
	}
	if sendErr != nil {
		t.Fatalf("Send failed after waiting for connection: %v", sendErr)
	}

	// Wait for the server to receive the event.
	deadline = time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if len(svc.receivedEvents()) > 0 {
			break
		}
		time.Sleep(50 * time.Millisecond)
	}

	got := svc.receivedEvents()
	if len(got) == 0 {
		t.Fatal("dashboard received 0 events; expected 1")
	}

	e := got[0]
	if e.GetTripwireType() != "FILE" {
		t.Errorf("TripwireType = %q; want %q", e.GetTripwireType(), "FILE")
	}
	if e.GetRuleName() != "etc-passwd-watch" {
		t.Errorf("RuleName = %q; want %q", e.GetRuleName(), "etc-passwd-watch")
	}
	if e.GetSeverity() != "CRITICAL" {
		t.Errorf("Severity = %q; want %q", e.GetSeverity(), "CRITICAL")
	}
	if e.GetHostId() != "host-send-test" {
		t.Errorf("HostId = %q; want %q", e.GetHostId(), "host-send-test")
	}
	if e.GetAlertId() == "" {
		t.Error("AlertId should be non-empty (UUID)")
	}
	if e.GetTimestampUs() == 0 {
		t.Error("TimestampUs should be non-zero")
	}
	if len(e.GetEventDetailJson()) == 0 {
		t.Error("EventDetailJson should be non-empty")
	}
}

// TestGRPCTransport_StopIsClean verifies that Stop() terminates all internal
// goroutines and does not block indefinitely.
func TestGRPCTransport_StopIsClean(t *testing.T) {
	pki := newTestPKI(t)
	svc := newCaptureService("host-stop-test")
	addr := startTestServer(t, pki, svc)

	tr := newTestTransport(t, pki, addr)
	ctx := context.Background()

	if err := tr.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}

	// Let the transport connect.
	time.Sleep(300 * time.Millisecond)

	done := make(chan struct{})
	go func() {
		defer close(done)
		tr.Stop()
	}()

	select {
	case <-done:
		// Stop returned cleanly.
	case <-time.After(5 * time.Second):
		t.Fatal("Stop did not return within 5 seconds")
	}
}

// TestGRPCTransport_ReconnectsAfterServerRestart verifies that the transport
// re-establishes the connection after the server is restarted.
func TestGRPCTransport_ReconnectsAfterServerRestart(t *testing.T) {
	pki := newTestPKI(t)

	// Start first server instance.
	svc1 := newCaptureService("host-reconnect-test")
	lis1, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	addr := lis1.Addr().String()

	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	grpcCfg := grpcserver.Config{
		CertPath: pki.srvCrtPath,
		KeyPath:  pki.srvKeyPath,
		CAPath:   pki.caCertPath,
	}
	srv1, err := grpcserver.New(grpcCfg, logger, svc1)
	if err != nil {
		t.Fatalf("grpcserver.New(srv1): %v", err)
	}

	ctx1, cancel1 := context.WithCancel(context.Background())
	done1 := make(chan struct{})
	go func() {
		defer close(done1)
		_ = srv1.ServeOnListener(ctx1, lis1)
	}()

	// Create and start the transport.
	tr := newTestTransport(t, pki, addr)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := tr.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}
	defer tr.Stop()

	// Wait for the first connection to be established.
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		svc1.mu.Lock()
		cn := svc1.lastCN
		svc1.mu.Unlock()
		if cn != "" {
			break
		}
		time.Sleep(50 * time.Millisecond)
	}
	svc1.mu.Lock()
	firstCN := svc1.lastCN
	svc1.mu.Unlock()
	if firstCN == "" {
		t.Fatal("first server never received a RegisterAgent call")
	}

	// Stop the first server to force a disconnect.
	cancel1()
	<-done1
	t.Log("first server stopped; transport should now reconnect with backoff")

	// Listen on the same address with a second server instance.
	lis2, err := net.Listen("tcp", addr)
	if err != nil {
		t.Fatalf("re-listen on %s: %v", addr, err)
	}
	svc2 := newCaptureService("host-reconnect-test-2")
	srv2, err := grpcserver.New(grpcCfg, logger, svc2)
	if err != nil {
		t.Fatalf("grpcserver.New(srv2): %v", err)
	}
	ctx2, cancel2 := context.WithCancel(context.Background())
	done2 := make(chan struct{})
	go func() {
		defer close(done2)
		_ = srv2.ServeOnListener(ctx2, lis2)
	}()
	t.Cleanup(func() { cancel2(); <-done2 })

	// The transport should reconnect within a few backoff intervals.
	deadline = time.Now().Add(10 * time.Second)
	for time.Now().Before(deadline) {
		svc2.mu.Lock()
		cn := svc2.lastCN
		svc2.mu.Unlock()
		if cn != "" {
			break
		}
		time.Sleep(100 * time.Millisecond)
	}
	svc2.mu.Lock()
	secondCN := svc2.lastCN
	svc2.mu.Unlock()
	if secondCN == "" {
		t.Fatal("transport did not reconnect to the second server within the deadline")
	}
	t.Logf("transport reconnected to second server with CN=%q", secondCN)
}

// TestGRPCTransport_MTLSRejectsRogueClientCert verifies that the dashboard
// rejects a transport whose client certificate is not signed by the trusted CA.
func TestGRPCTransport_MTLSRejectsRogueClientCert(t *testing.T) {
	pki := newTestPKI(t)
	roguePKI := newTestPKI(t) // independent CA — not trusted by the server

	svc := newCaptureService("host-mtls-test")
	addr := startTestServer(t, pki, svc)

	// Build a transport that presents the rogue client cert but trusts the real server CA.
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))

	// We need a mixed CA cert that trusts the real server but uses rogue client cert.
	// Write a combined CA PEM trusted by the client (real CA for server verification).
	// The rogue client cert is not signed by the real CA, so the server will reject it.
	realCABytes, _ := os.ReadFile(pki.caCertPath)
	mixedCAPath := filepath.Join(roguePKI.dir, "mixed-ca.crt")
	if err := os.WriteFile(mixedCAPath, realCABytes, 0o600); err != nil {
		t.Fatalf("write mixed CA: %v", err)
	}

	cfg := transport.Config{
		DashboardAddr:  addr,
		CertPath:       roguePKI.cliCrtPath, // signed by rogue CA
		KeyPath:        roguePKI.cliKeyPath,
		CAPath:         mixedCAPath, // trusts real server CA
		InitialBackoff: 100 * time.Millisecond,
		MaxBackoff:     200 * time.Millisecond,
		DialTimeout:    2 * time.Second,
	}
	tr := transport.New(cfg, logger)

	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()

	if err := tr.Start(ctx); err != nil {
		// If we fail even before connecting that's fine — the test is about rejection.
		t.Logf("Start returned error (acceptable): %v", err)
		return
	}
	defer tr.Stop()

	// Give the transport time to attempt (and fail) registration.
	<-ctx.Done()

	// The server should never have registered a rogue client.
	svc.mu.Lock()
	cn := svc.lastCN
	svc.mu.Unlock()
	if cn != "" {
		t.Errorf("rogue client was incorrectly registered with CN=%q; expected rejection", cn)
	}
	t.Log("rogue client cert was correctly rejected by the mTLS server")
}

// TestGRPCTransport_MultipleEvents verifies that multiple sequential Send
// calls all reach the server.
func TestGRPCTransport_MultipleEvents(t *testing.T) {
	pki := newTestPKI(t)
	svc := newCaptureService("host-multi-test")
	addr := startTestServer(t, pki, svc)

	tr := newTestTransport(t, pki, addr)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	if err := tr.Start(ctx); err != nil {
		t.Fatalf("Start: %v", err)
	}
	defer tr.Stop()

	const numEvents = 5
	evts := make([]watcher.AlertEvent, numEvents)
	for i := range evts {
		evts[i] = watcher.AlertEvent{
			TripwireType: "PROCESS",
			RuleName:     "bash-watch",
			Severity:     "WARN",
			Timestamp:    time.Now(),
			Detail:       map[string]any{"pid": i + 100},
		}
	}

	// Retry until connected, then send all events.
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		if err := tr.Send(ctx, evts[0]); err == nil {
			break
		}
		time.Sleep(50 * time.Millisecond)
	}

	// Send remaining events.
	for _, evt := range evts[1:] {
		if err := tr.Send(ctx, evt); err != nil {
			t.Fatalf("Send failed: %v", err)
		}
	}

	// Wait for the server to receive all events.
	deadline = time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		if len(svc.receivedEvents()) >= numEvents {
			break
		}
		time.Sleep(50 * time.Millisecond)
	}

	if got := len(svc.receivedEvents()); got != numEvents {
		t.Errorf("server received %d events; want %d", got, numEvents)
	}
}

// ─── Compile-time interface check ─────────────────────────────────────────────

// Ensure GRPCTransport satisfies the agent.Transport interface without
// importing the agent package (to avoid a dependency cycle in tests).
// The Transport interface requires Start, Send, and Stop methods with the
// signatures used by the agent orchestrator.
var _ interface {
	Start(ctx context.Context) error
	Send(ctx context.Context, evt watcher.AlertEvent) error
	Stop()
} = (*transport.GRPCTransport)(nil)
