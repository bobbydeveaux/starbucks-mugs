package rest_test

import (
	"context"
	"crypto"
	"crypto/rand"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"encoding/pem"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/tripwire/agent/internal/server/rest"
)

// ─── Test key generation ──────────────────────────────────────────────────────

// newTestKeyPair generates a 2048-bit RSA key pair for use in tests.
func newTestKeyPair(t *testing.T) (*rsa.PrivateKey, *rsa.PublicKey) {
	t.Helper()
	priv, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatalf("generate RSA key: %v", err)
	}
	return priv, &priv.PublicKey
}

// ─── JWT builder ─────────────────────────────────────────────────────────────

type jwtClaims struct {
	Issuer    string      `json:"iss,omitempty"`
	Subject   string      `json:"sub,omitempty"`
	Audience  interface{} `json:"aud,omitempty"` // string or []string
	ExpiresAt int64       `json:"exp,omitempty"`
	IssuedAt  int64       `json:"iat,omitempty"`
}

// buildJWT creates a compact RS256 JWT signed with priv.
// alg overrides the algorithm field in the header (use "RS256" for valid tokens).
func buildJWT(t *testing.T, priv *rsa.PrivateKey, alg string, claims jwtClaims) string {
	t.Helper()

	header := map[string]string{"alg": alg, "typ": "JWT"}
	headerJSON, _ := json.Marshal(header)
	payloadJSON, _ := json.Marshal(claims)

	headerB64 := base64.RawURLEncoding.EncodeToString(headerJSON)
	payloadB64 := base64.RawURLEncoding.EncodeToString(payloadJSON)
	sigInput := headerB64 + "." + payloadB64

	digest := sha256.Sum256([]byte(sigInput))
	sig, err := rsa.SignPKCS1v15(rand.Reader, priv, crypto.SHA256, digest[:])
	if err != nil {
		t.Fatalf("sign JWT: %v", err)
	}
	sigB64 := base64.RawURLEncoding.EncodeToString(sig)

	return sigInput + "." + sigB64
}

// buildJWTWithSig builds a JWT whose signature bytes are explicitly provided.
// Use this to inject corrupt signatures.
func buildJWTWithSig(t *testing.T, priv *rsa.PrivateKey, claims jwtClaims, sigOverride []byte) string {
	t.Helper()
	header := map[string]string{"alg": "RS256", "typ": "JWT"}
	headerJSON, _ := json.Marshal(header)
	payloadJSON, _ := json.Marshal(claims)
	headerB64 := base64.RawURLEncoding.EncodeToString(headerJSON)
	payloadB64 := base64.RawURLEncoding.EncodeToString(payloadJSON)
	return headerB64 + "." + payloadB64 + "." + base64.RawURLEncoding.EncodeToString(sigOverride)
}

// ─── PEM helpers ─────────────────────────────────────────────────────────────

func publicKeyPEM(pub *rsa.PublicKey) []byte {
	der := x509.MarshalPKCS1PublicKey(pub)
	return pem.EncodeToMemory(&pem.Block{Type: "RSA PUBLIC KEY", Bytes: der})
}

func publicKeyPKIXPEM(pub *rsa.PublicKey) []byte {
	der, _ := x509.MarshalPKIXPublicKey(pub)
	return pem.EncodeToMemory(&pem.Block{Type: "PUBLIC KEY", Bytes: der})
}

// ─── Test helpers ─────────────────────────────────────────────────────────────

// okHandler is a simple handler that writes 200 OK.
var okHandler = http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
	w.WriteHeader(http.StatusOK)
})

// claimsCapture is a handler that captures the Claims from the context.
type claimsCapture struct {
	got *rest.Claims
}

func (c *claimsCapture) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	c.got, _ = rest.ClaimsFromContext(r.Context())
	w.WriteHeader(http.StatusOK)
}

func validClaims() jwtClaims {
	return jwtClaims{
		Issuer:    "https://auth.example.com",
		Subject:   "user-123",
		ExpiresAt: time.Now().Add(time.Hour).Unix(),
		IssuedAt:  time.Now().Unix(),
	}
}

// ─── ParseRSAPublicKey tests ──────────────────────────────────────────────────

func TestParseRSAPublicKey_PKCS1(t *testing.T) {
	_, pub := newTestKeyPair(t)
	pemData := publicKeyPEM(pub)
	got, err := rest.ParseRSAPublicKey(pemData)
	if err != nil {
		t.Fatalf("ParseRSAPublicKey(PKCS1): unexpected error: %v", err)
	}
	if got.N.Cmp(pub.N) != 0 {
		t.Error("parsed key modulus differs from original")
	}
}

func TestParseRSAPublicKey_PKIX(t *testing.T) {
	_, pub := newTestKeyPair(t)
	pemData := publicKeyPKIXPEM(pub)
	got, err := rest.ParseRSAPublicKey(pemData)
	if err != nil {
		t.Fatalf("ParseRSAPublicKey(PKIX): unexpected error: %v", err)
	}
	if got.N.Cmp(pub.N) != 0 {
		t.Error("parsed key modulus differs from original")
	}
}

func TestParseRSAPublicKey_NoPEMBlock(t *testing.T) {
	_, err := rest.ParseRSAPublicKey([]byte("not-pem-data"))
	if err == nil {
		t.Fatal("expected error for non-PEM input, got nil")
	}
}

func TestParseRSAPublicKey_UnsupportedType(t *testing.T) {
	data := pem.EncodeToMemory(&pem.Block{Type: "CERTIFICATE", Bytes: []byte("fake")})
	_, err := rest.ParseRSAPublicKey(data)
	if err == nil {
		t.Fatal("expected error for unsupported PEM type, got nil")
	}
}

// ─── ClaimsFromContext tests ──────────────────────────────────────────────────

func TestClaimsFromContext_Missing(t *testing.T) {
	c, ok := rest.ClaimsFromContext(context.Background())
	if ok || c != nil {
		t.Errorf("expected (nil, false) for empty context, got (%v, %v)", c, ok)
	}
}

// ─── JWTMiddleware tests ──────────────────────────────────────────────────────

func cfg(t *testing.T, priv *rsa.PrivateKey, pub *rsa.PublicKey) rest.JWTConfig {
	t.Helper()
	return rest.JWTConfig{PublicKey: pub}
}

func TestJWTMiddleware_ValidToken_Returns200(t *testing.T) {
	priv, pub := newTestKeyPair(t)
	token := buildJWT(t, priv, "RS256", validClaims())

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/alerts", nil)
	req.Header.Set("Authorization", "Bearer "+token)

	rest.JWTMiddleware(cfg(t, priv, pub), okHandler).ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Errorf("status = %d, want 200", rec.Code)
	}
}

func TestJWTMiddleware_MissingAuthHeader_Returns401(t *testing.T) {
	_, pub := newTestKeyPair(t)
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/alerts", nil)

	rest.JWTMiddleware(rest.JWTConfig{PublicKey: pub}, okHandler).ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Errorf("status = %d, want 401", rec.Code)
	}
}

func TestJWTMiddleware_NonBearerScheme_Returns401(t *testing.T) {
	_, pub := newTestKeyPair(t)
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/alerts", nil)
	req.Header.Set("Authorization", "Basic dXNlcjpwYXNz")

	rest.JWTMiddleware(rest.JWTConfig{PublicKey: pub}, okHandler).ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Errorf("status = %d, want 401", rec.Code)
	}
}

func TestJWTMiddleware_EmptyToken_Returns401(t *testing.T) {
	_, pub := newTestKeyPair(t)
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/alerts", nil)
	req.Header.Set("Authorization", "Bearer ")

	rest.JWTMiddleware(rest.JWTConfig{PublicKey: pub}, okHandler).ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Errorf("status = %d, want 401", rec.Code)
	}
}

func TestJWTMiddleware_InvalidSignature_Returns401(t *testing.T) {
	priv, pub := newTestKeyPair(t)
	// Sign with a different key.
	otherPriv, _ := newTestKeyPair(t)
	token := buildJWT(t, otherPriv, "RS256", validClaims())
	_ = priv // unused; pub is the verification key

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/alerts", nil)
	req.Header.Set("Authorization", "Bearer "+token)

	rest.JWTMiddleware(rest.JWTConfig{PublicKey: pub}, okHandler).ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Errorf("status = %d, want 401", rec.Code)
	}
}

func TestJWTMiddleware_CorruptSignature_Returns401(t *testing.T) {
	priv, pub := newTestKeyPair(t)
	token := buildJWTWithSig(t, priv, validClaims(), []byte("bad-signature"))

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/alerts", nil)
	req.Header.Set("Authorization", "Bearer "+token)

	rest.JWTMiddleware(rest.JWTConfig{PublicKey: pub}, okHandler).ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Errorf("status = %d, want 401", rec.Code)
	}
}

func TestJWTMiddleware_ExpiredToken_Returns401(t *testing.T) {
	priv, pub := newTestKeyPair(t)
	claims := validClaims()
	claims.ExpiresAt = time.Now().Add(-time.Minute).Unix() // already expired
	token := buildJWT(t, priv, "RS256", claims)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/alerts", nil)
	req.Header.Set("Authorization", "Bearer "+token)

	rest.JWTMiddleware(rest.JWTConfig{PublicKey: pub}, okHandler).ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Errorf("status = %d, want 401", rec.Code)
	}
}

func TestJWTMiddleware_WrongAlgorithm_Returns401(t *testing.T) {
	priv, pub := newTestKeyPair(t)
	// Build a token declaring HS256 (even though it is still RSA-signed, the
	// middleware must reject any non-RS256 algorithm claim).
	token := buildJWT(t, priv, "HS256", validClaims())

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/alerts", nil)
	req.Header.Set("Authorization", "Bearer "+token)

	rest.JWTMiddleware(rest.JWTConfig{PublicKey: pub}, okHandler).ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Errorf("status = %d, want 401", rec.Code)
	}
}

func TestJWTMiddleware_MalformedJWT_Returns401(t *testing.T) {
	_, pub := newTestKeyPair(t)
	tests := []struct {
		name  string
		token string
	}{
		{"only-one-part", "onlyone"},
		{"only-two-parts", "part1.part2"},
		{"four-parts", "a.b.c.d"},
		{"bad-base64-header", "!!!.payload.sig"},
		{"bad-json-header", base64.RawURLEncoding.EncodeToString([]byte("notjson")) + ".payload.sig"},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			rec := httptest.NewRecorder()
			req := httptest.NewRequest(http.MethodGet, "/api/v1/alerts", nil)
			req.Header.Set("Authorization", "Bearer "+tt.token)

			rest.JWTMiddleware(rest.JWTConfig{PublicKey: pub}, okHandler).ServeHTTP(rec, req)

			if rec.Code != http.StatusUnauthorized {
				t.Errorf("token=%q: status = %d, want 401", tt.token, rec.Code)
			}
		})
	}
}

func TestJWTMiddleware_WrongIssuer_Returns401(t *testing.T) {
	priv, pub := newTestKeyPair(t)
	token := buildJWT(t, priv, "RS256", validClaims()) // iss = "https://auth.example.com"

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/alerts", nil)
	req.Header.Set("Authorization", "Bearer "+token)

	rest.JWTMiddleware(rest.JWTConfig{
		PublicKey: pub,
		Issuer:    "https://different-issuer.example.com",
	}, okHandler).ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Errorf("status = %d, want 401", rec.Code)
	}
}

func TestJWTMiddleware_CorrectIssuer_Returns200(t *testing.T) {
	priv, pub := newTestKeyPair(t)
	token := buildJWT(t, priv, "RS256", validClaims()) // iss = "https://auth.example.com"

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/alerts", nil)
	req.Header.Set("Authorization", "Bearer "+token)

	rest.JWTMiddleware(rest.JWTConfig{
		PublicKey: pub,
		Issuer:    "https://auth.example.com",
	}, okHandler).ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Errorf("status = %d, want 200", rec.Code)
	}
}

func TestJWTMiddleware_WrongAudience_Returns401(t *testing.T) {
	priv, pub := newTestKeyPair(t)
	claims := validClaims()
	claims.Audience = "api.example.com"
	token := buildJWT(t, priv, "RS256", claims)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/alerts", nil)
	req.Header.Set("Authorization", "Bearer "+token)

	rest.JWTMiddleware(rest.JWTConfig{
		PublicKey: pub,
		Audience:  "other-service.example.com",
	}, okHandler).ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Errorf("status = %d, want 401", rec.Code)
	}
}

func TestJWTMiddleware_CorrectAudience_StringForm_Returns200(t *testing.T) {
	priv, pub := newTestKeyPair(t)
	claims := validClaims()
	claims.Audience = "api.example.com"
	token := buildJWT(t, priv, "RS256", claims)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/alerts", nil)
	req.Header.Set("Authorization", "Bearer "+token)

	rest.JWTMiddleware(rest.JWTConfig{
		PublicKey: pub,
		Audience:  "api.example.com",
	}, okHandler).ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Errorf("status = %d, want 200", rec.Code)
	}
}

func TestJWTMiddleware_CorrectAudience_ArrayForm_Returns200(t *testing.T) {
	priv, pub := newTestKeyPair(t)
	claims := validClaims()
	claims.Audience = []string{"service-a", "api.example.com", "service-b"}
	token := buildJWT(t, priv, "RS256", claims)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/alerts", nil)
	req.Header.Set("Authorization", "Bearer "+token)

	rest.JWTMiddleware(rest.JWTConfig{
		PublicKey: pub,
		Audience:  "api.example.com",
	}, okHandler).ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Errorf("status = %d, want 200", rec.Code)
	}
}

func TestJWTMiddleware_SkipPath_NoAuthRequired(t *testing.T) {
	_, pub := newTestKeyPair(t)
	// No Authorization header – but the path is skipped.
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)

	rest.JWTMiddleware(rest.JWTConfig{
		PublicKey: pub,
		SkipPaths: []string{"/healthz"},
	}, okHandler).ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Errorf("status = %d, want 200 (skipped path)", rec.Code)
	}
}

func TestJWTMiddleware_SkipPath_OnlyExactMatch(t *testing.T) {
	_, pub := newTestKeyPair(t)
	// /healthz/extra is NOT in the skip list.
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/healthz/extra", nil)

	rest.JWTMiddleware(rest.JWTConfig{
		PublicKey: pub,
		SkipPaths: []string{"/healthz"},
	}, okHandler).ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Errorf("status = %d, want 401 (non-skip path)", rec.Code)
	}
}

func TestJWTMiddleware_ClaimsInjectedIntoContext(t *testing.T) {
	priv, pub := newTestKeyPair(t)
	claims := validClaims()
	claims.Subject = "agent-007"
	token := buildJWT(t, priv, "RS256", claims)

	capture := &claimsCapture{}
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/alerts", nil)
	req.Header.Set("Authorization", "Bearer "+token)

	rest.JWTMiddleware(rest.JWTConfig{PublicKey: pub}, capture).ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want 200", rec.Code)
	}
	if capture.got == nil {
		t.Fatal("claims not found in context")
	}
	if capture.got.Subject != "agent-007" {
		t.Errorf("Subject = %q, want %q", capture.got.Subject, "agent-007")
	}
}

func TestJWTMiddleware_NoExpiryClaim_Accepted(t *testing.T) {
	priv, pub := newTestKeyPair(t)
	// A token with no exp claim should be accepted (zero value means "not set").
	claims := jwtClaims{Subject: "service-account"}
	token := buildJWT(t, priv, "RS256", claims)

	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/alerts", nil)
	req.Header.Set("Authorization", "Bearer "+token)

	rest.JWTMiddleware(rest.JWTConfig{PublicKey: pub}, okHandler).ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Errorf("status = %d, want 200 (no exp claim)", rec.Code)
	}
}

func TestJWTMiddleware_ResponseContentType_IsJSON(t *testing.T) {
	_, pub := newTestKeyPair(t)
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/alerts", nil)
	// No Authorization header → 401.

	rest.JWTMiddleware(rest.JWTConfig{PublicKey: pub}, okHandler).ServeHTTP(rec, req)

	ct := rec.Header().Get("Content-Type")
	if ct != "application/json" {
		t.Errorf("Content-Type = %q, want %q", ct, "application/json")
	}
}

func TestJWTMiddleware_ResponseBody_ContainsErrorField(t *testing.T) {
	_, pub := newTestKeyPair(t)
	rec := httptest.NewRecorder()
	req := httptest.NewRequest(http.MethodGet, "/api/v1/alerts", nil)

	rest.JWTMiddleware(rest.JWTConfig{PublicKey: pub}, okHandler).ServeHTTP(rec, req)

	var body map[string]string
	if err := json.NewDecoder(rec.Body).Decode(&body); err != nil {
		t.Fatalf("decode error body: %v", err)
	}
	if body["error"] == "" {
		t.Error("expected non-empty 'error' field in JSON response")
	}
}
