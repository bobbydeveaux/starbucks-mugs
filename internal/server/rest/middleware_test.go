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

// generateTestKey creates a fresh 2048-bit RSA key pair for testing.
func generateTestKey(t *testing.T) (*rsa.PrivateKey, *rsa.PublicKey) {
	t.Helper()
	priv, err := rsa.GenerateKey(rand.Reader, 2048)
	if err != nil {
		t.Fatalf("rsa.GenerateKey: %v", err)
	}
	return priv, &priv.PublicKey
}

// signToken creates a signed RS256 JWT with the given claims and private key.
func signToken(t *testing.T, priv *rsa.PrivateKey, claims jwt.Claims) string {
	t.Helper()
	tok := jwt.NewWithClaims(jwt.SigningMethodRS256, claims)
	signed, err := tok.SignedString(priv)
	if err != nil {
		t.Fatalf("sign token: %v", err)
	}
	return signed
}

// wrappedHandler is a trivial handler that records whether it was called.
func wrappedHandler(called *bool) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		*called = true
		w.WriteHeader(http.StatusOK)
	})
}

func TestJWTMiddleware_MissingHeader_Returns401(t *testing.T) {
	_, pub := generateTestKey(t)
	mw := JWTMiddleware(pub)

	called := false
	h := mw(wrappedHandler(&called))

	req := httptest.NewRequest(http.MethodGet, "/", nil)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401, got %d", rec.Code)
	}
	if called {
		t.Error("next handler should not have been called")
	}
}

func TestJWTMiddleware_MalformedHeader_Returns401(t *testing.T) {
	_, pub := generateTestKey(t)
	mw := JWTMiddleware(pub)

	called := false
	h := mw(wrappedHandler(&called))

	for _, bad := range []string{"Basic abc", "token-without-scheme", "Bearer"} {
		req := httptest.NewRequest(http.MethodGet, "/", nil)
		req.Header.Set("Authorization", bad)
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, req)

		if rec.Code != http.StatusUnauthorized {
			t.Errorf("header %q: expected 401, got %d", bad, rec.Code)
		}
	}
	if called {
		t.Error("next handler should not have been called")
	}
}

func TestJWTMiddleware_ExpiredToken_Returns401(t *testing.T) {
	priv, pub := generateTestKey(t)
	mw := JWTMiddleware(pub)

	called := false
	h := mw(wrappedHandler(&called))

	claims := jwt.RegisteredClaims{
		ExpiresAt: jwt.NewNumericDate(time.Now().Add(-time.Hour)), // already expired
		IssuedAt:  jwt.NewNumericDate(time.Now().Add(-2 * time.Hour)),
	}
	tok := signToken(t, priv, claims)

	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.Header.Set("Authorization", "Bearer "+tok)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401 for expired token, got %d", rec.Code)
	}
	if called {
		t.Error("next handler should not have been called")
	}
}

func TestJWTMiddleware_WrongSigningKey_Returns401(t *testing.T) {
	priv, _ := generateTestKey(t)   // key pair 1 (signer)
	_, pub2 := generateTestKey(t)   // key pair 2 (verifier) – mismatch

	mw := JWTMiddleware(pub2)

	called := false
	h := mw(wrappedHandler(&called))

	claims := jwt.RegisteredClaims{
		ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour)),
	}
	tok := signToken(t, priv, claims)

	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.Header.Set("Authorization", "Bearer "+tok)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("expected 401 for wrong key, got %d", rec.Code)
	}
	if called {
		t.Error("next handler should not have been called")
	}
}

func TestJWTMiddleware_ValidToken_CallsNext(t *testing.T) {
	priv, pub := generateTestKey(t)
	mw := JWTMiddleware(pub)

	called := false
	h := mw(wrappedHandler(&called))

	claims := jwt.RegisteredClaims{
		ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour)),
		IssuedAt:  jwt.NewNumericDate(time.Now()),
		Subject:   "test-user",
	}
	tok := signToken(t, priv, claims)

	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.Header.Set("Authorization", "Bearer "+tok)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected 200, got %d", rec.Code)
	}
	if !called {
		t.Error("next handler was not called for a valid token")
	}
}

func TestJWTMiddleware_ValidToken_StoresClaimsInContext(t *testing.T) {
	priv, pub := generateTestKey(t)
	mw := JWTMiddleware(pub)

	var gotClaims *Claims
	h := mw(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		gotClaims = ClaimsFromContext(r.Context())
		w.WriteHeader(http.StatusOK)
	}))

	claims := jwt.RegisteredClaims{
		ExpiresAt: jwt.NewNumericDate(time.Now().Add(time.Hour)),
		Subject:   "user-42",
	}
	tok := signToken(t, priv, claims)

	req := httptest.NewRequest(http.MethodGet, "/", nil)
	req.Header.Set("Authorization", "Bearer "+tok)
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, req)

	if gotClaims == nil {
		t.Fatal("expected Claims in context, got nil")
	}
	if gotClaims.Subject != "user-42" {
		t.Errorf("expected subject=user-42, got %q", gotClaims.Subject)
	}
}

// TestClaimsFromContext_NoClaimsReturnsNil verifies that the helper does not
// panic or return garbage when called on an unauthenticated context.
func TestClaimsFromContext_NoClaimsReturnsNil(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/", nil)
	if c := ClaimsFromContext(req.Context()); c != nil {
		t.Errorf("expected nil, got %+v", c)
	}
}
