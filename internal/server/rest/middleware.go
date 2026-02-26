// Package rest provides the HTTP REST API server for the TripWire dashboard.
// This file implements RS256 JWT bearer-token authentication middleware.
//
// # Authentication Flow
//
// All requests to protected routes must include an Authorization header:
//
//	Authorization: Bearer <compact-JWT>
//
// The middleware:
//  1. Extracts the Bearer token from the Authorization header.
//  2. Decodes and validates the JWT header – only RS256 is accepted.
//  3. Verifies the RSA-PKCS1v15 signature against the configured public key.
//  4. Checks that the token has not expired (exp claim).
//  5. Optionally validates the issuer (iss) and audience (aud) claims.
//  6. Injects the verified [Claims] into the request context.
//
// On any failure the middleware responds with HTTP 401 and a JSON error body;
// it does NOT call the next handler.
//
// # Public-Key Format
//
// [ParseRSAPublicKey] accepts PEM-encoded keys in either PKCS#1
// ("RSA PUBLIC KEY") or PKIX ("PUBLIC KEY") format.
package rest

import (
	"context"
	"crypto"
	"crypto/rsa"
	"crypto/sha256"
	"crypto/x509"
	"encoding/base64"
	"encoding/json"
	"encoding/pem"
	"errors"
	"fmt"
	"log/slog"
	"net/http"
	"strings"
	"time"
)

// ─── Context key ─────────────────────────────────────────────────────────────

// contextKey is an unexported type used for context keys in this package to
// avoid collisions with keys defined in other packages.
type contextKey int

const claimsKey contextKey = 0

// ─── Public types ─────────────────────────────────────────────────────────────

// Claims holds the verified JWT payload claims that are injected into the
// request context by [JWTMiddleware] on successful authentication.
//
// Downstream handlers retrieve them with [ClaimsFromContext].
type Claims struct {
	// Issuer is the "iss" registered claim.
	Issuer string `json:"iss,omitempty"`
	// Subject is the "sub" registered claim; typically the user/service ID.
	Subject string `json:"sub,omitempty"`
	// Audience is the "aud" registered claim.  Per RFC 7519 this may be a
	// single string or an array; both forms are normalised to a []string.
	Audience Audience `json:"aud,omitempty"`
	// ExpiresAt is the "exp" registered claim (Unix seconds).
	ExpiresAt int64 `json:"exp,omitempty"`
	// IssuedAt is the "iat" registered claim (Unix seconds).
	IssuedAt int64 `json:"iat,omitempty"`
	// JWTID is the "jti" registered claim.
	JWTID string `json:"jti,omitempty"`
}

// Audience is a JWT "aud" value that may be serialised as either a JSON string
// or a JSON array.  Both forms are unmarshalled into []string.
type Audience []string

// UnmarshalJSON implements [json.Unmarshaler].
func (a *Audience) UnmarshalJSON(data []byte) error {
	// Try single-string form first.
	var s string
	if err := json.Unmarshal(data, &s); err == nil {
		*a = Audience{s}
		return nil
	}
	// Fall back to array form.
	var arr []string
	if err := json.Unmarshal(data, &arr); err != nil {
		return fmt.Errorf("jwt: cannot unmarshal audience: %w", err)
	}
	*a = Audience(arr)
	return nil
}

// JWTConfig holds the configuration for [JWTMiddleware].
type JWTConfig struct {
	// PublicKey is the RSA public key used to verify RS256 JWT signatures.
	// Required.
	PublicKey *rsa.PublicKey

	// Issuer, if non-empty, is compared against the "iss" JWT claim.
	// A mismatch results in HTTP 401.
	Issuer string

	// Audience, if non-empty, must appear in the "aud" JWT claim.
	// A missing or non-matching audience results in HTTP 401.
	Audience string

	// SkipPaths lists exact URL paths that bypass JWT authentication.
	// The /healthz liveness path should typically be included.
	SkipPaths []string

	// Logger is used to record per-request authentication failures.
	// When nil, slog.Default() is used.
	Logger *slog.Logger
}

// ─── Context helpers ─────────────────────────────────────────────────────────

// ClaimsFromContext retrieves the verified [Claims] injected by [JWTMiddleware].
// It returns (nil, false) when no claims are present (unauthenticated request
// or middleware not in the chain).
func ClaimsFromContext(ctx context.Context) (*Claims, bool) {
	c, ok := ctx.Value(claimsKey).(*Claims)
	return c, ok
}

// ─── Public-key helper ───────────────────────────────────────────────────────

// ParseRSAPublicKey decodes a PEM block and parses an RSA public key.
// It accepts both PKCS#1 ("RSA PUBLIC KEY") and PKIX ("PUBLIC KEY") encodings.
func ParseRSAPublicKey(pemData []byte) (*rsa.PublicKey, error) {
	block, _ := pem.Decode(pemData)
	if block == nil {
		return nil, errors.New("jwt: no PEM block found in public key data")
	}
	switch block.Type {
	case "RSA PUBLIC KEY":
		key, err := x509.ParsePKCS1PublicKey(block.Bytes)
		if err != nil {
			return nil, fmt.Errorf("jwt: PKCS#1 parse error: %w", err)
		}
		return key, nil
	case "PUBLIC KEY":
		key, err := x509.ParsePKIXPublicKey(block.Bytes)
		if err != nil {
			return nil, fmt.Errorf("jwt: PKIX parse error: %w", err)
		}
		rsaKey, ok := key.(*rsa.PublicKey)
		if !ok {
			return nil, errors.New("jwt: public key is not an RSA key")
		}
		return rsaKey, nil
	default:
		return nil, fmt.Errorf("jwt: unsupported PEM type %q", block.Type)
	}
}

// ─── Middleware ───────────────────────────────────────────────────────────────

// JWTMiddleware returns an [http.Handler] that enforces RS256 JWT bearer-token
// authentication.
//
// On success the verified [Claims] are stored in the request context (retrieve
// with [ClaimsFromContext]) and the request is forwarded to next.  On failure
// the response is HTTP 401 with a JSON error body; next is never called.
//
// Paths listed in [JWTConfig.SkipPaths] are passed straight through without
// any authentication check.
func JWTMiddleware(cfg JWTConfig, next http.Handler) http.Handler {
	logger := cfg.Logger
	if logger == nil {
		logger = slog.Default()
	}

	skip := make(map[string]struct{}, len(cfg.SkipPaths))
	for _, p := range cfg.SkipPaths {
		skip[p] = struct{}{}
	}

	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if _, ok := skip[r.URL.Path]; ok {
			next.ServeHTTP(w, r)
			return
		}

		claims, err := extractAndValidate(r, cfg)
		if err != nil {
			logger.Warn("jwt: authentication failed",
				slog.String("path", r.URL.Path),
				slog.String("remote_addr", r.RemoteAddr),
				slog.String("error", err.Error()),
			)
			writeJSONError(w, http.StatusUnauthorized, "unauthorized")
			return
		}

		ctx := context.WithValue(r.Context(), claimsKey, claims)
		next.ServeHTTP(w, r.WithContext(ctx))
	})
}

// ─── Internal helpers ─────────────────────────────────────────────────────────

// jwtHeader is the JOSE header decoded from the first JWT segment.
type jwtHeader struct {
	Alg string `json:"alg"`
	Typ string `json:"typ"`
	Kid string `json:"kid"`
}

// extractAndValidate parses the Authorization header, decodes the JWT, verifies
// the RS256 signature, checks the standard time and identity claims, and returns
// the verified payload.
func extractAndValidate(r *http.Request, cfg JWTConfig) (*Claims, error) {
	raw := r.Header.Get("Authorization")
	if !strings.HasPrefix(raw, "Bearer ") {
		return nil, errors.New("missing or malformed Authorization header")
	}
	token := strings.TrimPrefix(raw, "Bearer ")
	if token == "" {
		return nil, errors.New("empty bearer token")
	}
	return verifyRS256(token, cfg)
}

// verifyRS256 performs the full RS256 JWT verification pipeline:
//  1. Split the compact serialisation into header / payload / signature.
//  2. Decode and validate the JOSE header (algorithm must be RS256).
//  3. Verify the RSA-PKCS1v15 signature over the signing input.
//  4. Decode and validate the payload claims.
func verifyRS256(token string, cfg JWTConfig) (*Claims, error) {
	parts := strings.Split(token, ".")
	if len(parts) != 3 {
		return nil, errors.New("malformed JWT: expected 3 dot-separated segments")
	}

	// --- Decode header ---
	headerBytes, err := base64.RawURLEncoding.DecodeString(parts[0])
	if err != nil {
		return nil, fmt.Errorf("malformed JWT header encoding: %w", err)
	}
	var header jwtHeader
	if err := json.Unmarshal(headerBytes, &header); err != nil {
		return nil, fmt.Errorf("malformed JWT header JSON: %w", err)
	}
	if header.Alg != "RS256" {
		return nil, fmt.Errorf("unsupported algorithm %q: only RS256 is accepted", header.Alg)
	}

	// --- Decode payload ---
	payloadBytes, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return nil, fmt.Errorf("malformed JWT payload encoding: %w", err)
	}

	// --- Decode signature ---
	sigBytes, err := base64.RawURLEncoding.DecodeString(parts[2])
	if err != nil {
		return nil, fmt.Errorf("malformed JWT signature encoding: %w", err)
	}

	// --- Verify signature ---
	// The signing input is the ASCII bytes of headerB64.payloadB64.
	signingInput := parts[0] + "." + parts[1]
	digest := sha256.Sum256([]byte(signingInput))
	if err := rsa.VerifyPKCS1v15(cfg.PublicKey, crypto.SHA256, digest[:], sigBytes); err != nil {
		return nil, fmt.Errorf("invalid JWT signature: %w", err)
	}

	// --- Parse claims ---
	var claims Claims
	if err := json.Unmarshal(payloadBytes, &claims); err != nil {
		return nil, fmt.Errorf("malformed JWT payload JSON: %w", err)
	}

	// --- Validate expiry ---
	if claims.ExpiresAt != 0 && time.Now().Unix() > claims.ExpiresAt {
		return nil, errors.New("JWT has expired")
	}

	// --- Validate issuer ---
	if cfg.Issuer != "" && claims.Issuer != cfg.Issuer {
		return nil, fmt.Errorf("JWT issuer %q does not match expected %q", claims.Issuer, cfg.Issuer)
	}

	// --- Validate audience ---
	if cfg.Audience != "" {
		found := false
		for _, a := range claims.Audience {
			if a == cfg.Audience {
				found = true
				break
			}
		}
		if !found {
			return nil, fmt.Errorf("JWT audience does not include %q", cfg.Audience)
		}
	}

	return &claims, nil
}

// writeJSONError writes an HTTP error response with a JSON body.
// It sets the Content-Type header before writing the status code so that
// the header is included even when ResponseWriter buffers are flushed early.
func writeJSONError(w http.ResponseWriter, code int, detail string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	body := fmt.Sprintf(`{"error":%q}`, detail)
	_, _ = w.Write([]byte(body))
}
