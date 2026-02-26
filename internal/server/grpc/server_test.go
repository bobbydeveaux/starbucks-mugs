package grpc_test

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
	"testing"
	"time"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials"
	"google.golang.org/grpc/status"

	grpcserver "github.com/tripwire/agent/internal/server/grpc"
	alertpb "github.com/tripwire/agent/proto"
)

// ─── In-memory test PKI ───────────────────────────────────────────────────────

// testPKI holds an in-memory CA and a signed server certificate.
type testPKI struct {
	caPool     *x509.CertPool
	caCert     *x509.Certificate
	caKey      *ecdsa.PrivateKey
	caCertPath string
	srvCrtPath string
	srvKeyPath string
}

// newTestPKI generates a self-signed CA and signs a server certificate for
// localhost/127.0.0.1.  Key material is written to t.TempDir().
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

	// Server certificate
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

	return &testPKI{
		caPool:     caPool,
		caCert:     caCert,
		caKey:      caKey,
		caCertPath: caPath,
		srvCrtPath: srvCrtPath,
		srvKeyPath: srvKeyPath,
	}
}

// signClientCert creates and signs a client certificate with the given CN.
func (p *testPKI) signClientCert(t *testing.T, cn string) tls.Certificate {
	t.Helper()
	key, _ := ecdsa.GenerateKey(elliptic.P256(), rand.Reader)

	template := &x509.Certificate{
		SerialNumber: big.NewInt(time.Now().UnixNano()),
		Subject:      pkix.Name{CommonName: cn},
		NotBefore:    time.Now().Add(-time.Hour),
		NotAfter:     time.Now().Add(24 * time.Hour),
		KeyUsage:     x509.KeyUsageDigitalSignature,
		ExtKeyUsage:  []x509.ExtKeyUsage{x509.ExtKeyUsageClientAuth},
	}

	certDER, _ := x509.CreateCertificate(rand.Reader, template, p.caCert, &key.PublicKey, p.caKey)
	leaf, _ := x509.ParseCertificate(certDER)

	return tls.Certificate{
		Certificate: [][]byte{certDER},
		PrivateKey:  key,
		Leaf:        leaf,
	}
}

// ─── PEM write helpers ────────────────────────────────────────────────────────

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

// ─── Stub service ─────────────────────────────────────────────────────────────

// echoService is a minimal AlertServiceServer that captures the agent CN from
// the request context and returns a fixed ACK.
type echoService struct {
	alertpb.UnimplementedAlertServiceServer
	lastCN string
}

func (s *echoService) RegisterAgent(ctx context.Context, _ *alertpb.AgentRegistration) (*alertpb.ServerAck, error) {
	cn, ok := grpcserver.AgentCNFromContext(ctx)
	if !ok {
		return nil, status.Error(3 /* codes.InvalidArgument */, "no agent CN")
	}
	s.lastCN = cn
	return &alertpb.ServerAck{Ok: true, AlertId: "test-ack"}, nil
}

// ─── Server launch helper ─────────────────────────────────────────────────────

// startServer starts an in-process gRPC server on a random OS-assigned port
// and returns its address.  The server is stopped when t finishes.
func startServer(t *testing.T, pki *testPKI, svc alertpb.AlertServiceServer) string {
	t.Helper()

	// Listen on an OS-assigned port so tests never collide.
	lis, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	addr := lis.Addr().String()

	cfg := grpcserver.Config{
		CertPath: pki.srvCrtPath,
		KeyPath:  pki.srvKeyPath,
		CAPath:   pki.caCertPath,
	}

	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	srv, err := grpcserver.New(cfg, logger, svc)
	if err != nil {
		lis.Close()
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

	return addr
}

// dialClient creates a gRPC client using mTLS with the given client certificate.
func dialClient(t *testing.T, addr string, pki *testPKI, clientCert tls.Certificate) *grpc.ClientConn {
	t.Helper()

	tlsCfg := &tls.Config{
		Certificates: []tls.Certificate{clientCert},
		RootCAs:      pki.caPool,
		ServerName:   "localhost",
		MinVersion:   tls.VersionTLS12,
	}

	conn, err := grpc.NewClient(addr, grpc.WithTransportCredentials(credentials.NewTLS(tlsCfg)))
	if err != nil {
		t.Fatalf("grpc.NewClient: %v", err)
	}
	t.Cleanup(func() { conn.Close() })
	return conn
}

// ─── Tests ────────────────────────────────────────────────────────────────────

// TestAgentCNFromContext confirms AgentCNFromContext returns false when no CN
// has been injected (e.g., on a plain background context).
func TestAgentCNFromContext(t *testing.T) {
	cn, ok := grpcserver.AgentCNFromContext(context.Background())
	if ok || cn != "" {
		t.Errorf("expected (empty, false); got (%q, %v)", cn, ok)
	}
}

// TestMTLSAcceptsValidClientCert verifies end-to-end mTLS: a client with a
// valid CA-signed certificate can call RegisterAgent and the agent CN is
// correctly extracted and returned to the handler.
func TestMTLSAcceptsValidClientCert(t *testing.T) {
	pki := newTestPKI(t)
	svc := &echoService{}
	addr := startServer(t, pki, svc)

	clientCert := pki.signClientCert(t, "agent-node-42")
	conn := dialClient(t, addr, pki, clientCert)
	client := alertpb.NewAlertServiceClient(conn)

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	ack, err := client.RegisterAgent(ctx, &alertpb.AgentRegistration{Hostname: "node-42"})
	if err != nil {
		t.Fatalf("RegisterAgent: %v", err)
	}
	if !ack.Ok {
		t.Errorf("ack.Ok = false; want true")
	}
	if svc.lastCN != "agent-node-42" {
		t.Errorf("lastCN = %q; want %q", svc.lastCN, "agent-node-42")
	}
}

// TestMTLSRejectsNoClientCert verifies that a client without a client
// certificate is rejected at the TLS layer.
func TestMTLSRejectsNoClientCert(t *testing.T) {
	pki := newTestPKI(t)
	addr := startServer(t, pki, &echoService{})

	// Client with no certificate.
	tlsCfg := &tls.Config{
		RootCAs:    pki.caPool,
		ServerName: "localhost",
	}
	conn, err := grpc.NewClient(addr, grpc.WithTransportCredentials(credentials.NewTLS(tlsCfg)))
	if err != nil {
		t.Fatalf("grpc.NewClient: %v", err)
	}
	defer conn.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	_, err = alertpb.NewAlertServiceClient(conn).RegisterAgent(ctx, &alertpb.AgentRegistration{})
	if err == nil {
		t.Fatal("expected error for connection without client cert; got nil")
	}
	t.Logf("correctly rejected unauthenticated connection: %v", err)
}

// TestMTLSRejectsUnknownCAClientCert verifies that a client certificate signed
// by a foreign CA is rejected.
func TestMTLSRejectsUnknownCAClientCert(t *testing.T) {
	pki := newTestPKI(t)
	// Second PKI acts as a rogue CA.
	roguePKI := newTestPKI(t)
	addr := startServer(t, pki, &echoService{})

	rogueCert := roguePKI.signClientCert(t, "rogue-agent")

	// Build a client that trusts the real server cert but presents a rogue client cert.
	tlsCfg := &tls.Config{
		Certificates: []tls.Certificate{rogueCert},
		RootCAs:      pki.caPool,
		ServerName:   "localhost",
	}
	conn, err := grpc.NewClient(addr, grpc.WithTransportCredentials(credentials.NewTLS(tlsCfg)))
	if err != nil {
		t.Fatalf("grpc.NewClient: %v", err)
	}
	defer conn.Close()

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	_, err = alertpb.NewAlertServiceClient(conn).RegisterAgent(ctx, &alertpb.AgentRegistration{})
	if err == nil {
		t.Fatal("expected error for rogue CA client cert; got nil")
	}
	t.Logf("correctly rejected rogue CA cert: %v", err)
}

// TestCNExtraction exercises the CN extraction for various Common Name values.
func TestCNExtraction(t *testing.T) {
	cases := []struct {
		cn string
	}{
		{"agent-prod-01"},
		{"sensor-rack-12-us-east"},
		{"node.example.com"},
	}

	pki := newTestPKI(t)
	svc := &echoService{}
	addr := startServer(t, pki, svc)

	for _, tc := range cases {
		t.Run(tc.cn, func(t *testing.T) {
			cert := pki.signClientCert(t, tc.cn)
			conn := dialClient(t, addr, pki, cert)
			client := alertpb.NewAlertServiceClient(conn)

			ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
			defer cancel()

			ack, err := client.RegisterAgent(ctx, &alertpb.AgentRegistration{})
			if err != nil {
				t.Fatalf("RegisterAgent(%q): %v", tc.cn, err)
			}
			if !ack.Ok {
				t.Errorf("ack.Ok = false for CN %q", tc.cn)
			}
			if svc.lastCN != tc.cn {
				t.Errorf("lastCN = %q; want %q", svc.lastCN, tc.cn)
			}
		})
	}
}

// TestServerNewErrorBadCert verifies that New returns an error when the
// certificate paths are invalid.
func TestServerNewErrorBadCert(t *testing.T) {
	cfg := grpcserver.Config{
		CertPath: "/nonexistent/server.crt",
		KeyPath:  "/nonexistent/server.key",
		CAPath:   "/nonexistent/ca.crt",
	}
	logger := slog.New(slog.NewTextHandler(io.Discard, nil))
	_, err := grpcserver.New(cfg, logger, alertpb.UnimplementedAlertServiceServer{})
	if err == nil {
		t.Fatal("expected error for invalid cert paths; got nil")
	}
}
