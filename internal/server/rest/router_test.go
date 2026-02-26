package rest

import (
	"crypto/rand"
	"crypto/rsa"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"github.com/golang-jwt/jwt/v5"
)

func generateRouterTestKey(t *testing.T) (*rsa.PrivateKey, *rsa.PublicKey) {
	t.Helper()
	priv, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatalf("rsa.GenerateKey: %v", err)
	}
	return priv, &priv.PublicKey
}

func validBearerToken(t *testing.T, priv *rsa.PrivateKey) string {
	t.Helper()
	claims := jwt.RegisteredClaims{
		ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour)),
		IssuedAt:  jwt.NewNumericDate(time.Now()),
		Subject:   "test",
	}
	tok := jwt.NewWithClaims(jwt.SigningMethodRS256, claims)
	signed, err := tok.SignedString(priv)
	if err != nil {
		t.Fatalf("sign token: %v", err)
	}
	return "Bearer " + signed
}

// TestRouter_HealthzNoAuth verifies /healthz is accessible without a JWT.
func TestRouter_HealthzNoAuth(t *testing.T) {
	_, pub := generateRouterTestKey(t)
	srv := NewServer(&mockStore{})
	h := NewRouter(srv, pub)

	req := httptest.NewRequest(http.MethodGet, "/healthz", nil)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
}

// TestRouter_APIRoutesRequireJWT verifies that all /api/v1/* routes return 401
// when no Authorization header is present.
func TestRouter_APIRoutesRequireJWT(t *testing.T) {
	_, pub := generateRouterTestKey(t)
	srv := NewServer(&mockStore{})
	h := NewRouter(srv, pub)

	routes := []string{
		"/api/v1/hosts",
		"/api/v1/alerts?from=2026-01-01T00:00:00Z&to=2026-02-01T00:00:00Z",
		"/api/v1/audit?host_id=h1&from=2026-01-01T00:00:00Z&to=2026-02-01T00:00:00Z",
	}

	for _, route := range routes {
		req := httptest.NewRequest(http.MethodGet, route, nil)
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, req)

		if rec.Code != http.StatusUnauthorized {
			t.Errorf("route %s: expected 401 without JWT, got %d", route, rec.Code)
		}
	}
}

// TestRouter_APIRoutesAccessibleWithJWT verifies that valid JWT passes the
// middleware and routes proceed to the handler (not rejected at auth layer).
func TestRouter_APIRoutesAccessibleWithJWT(t *testing.T) {
	priv, pub := generateRouterTestKey(t)
	srv := NewServer(&mockStore{})
	h := NewRouter(srv, pub)

	bearer := validBearerToken(t, priv)

	// /api/v1/hosts - no required params, just needs valid auth
	req := httptest.NewRequest(http.MethodGet, "/api/v1/hosts", nil)
	req.Header.Set("Authorization", bearer)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	// With a valid JWT the handler is reached; mock returns empty list → 200
	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200 with valid JWT, got %d; body: %s", rec.Code, rec.Body)
	}
}
