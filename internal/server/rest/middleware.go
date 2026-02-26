// Package rest provides the HTTP REST API layer for the TripWire dashboard
// server. It includes a chi router, JWT authentication middleware, and handler
// functions for all /api/v1 endpoints.
package rest

import (
	"context"
	"crypto/rsa"
	"encoding/json"
	"errors"
	"net/http"
	"strings"

	"github.com/golang-jwt/jwt/v5"
)

// contextKey is an unexported type used to store values in request contexts,
// preventing collisions with keys from other packages.
type contextKey int

const (
	// claimsKey is the context key under which validated JWT claims are stored.
	claimsKey contextKey = iota
)

// Claims extends the standard jwt.RegisteredClaims with any application-
// specific fields that handlers may need to inspect.
type Claims struct {
	jwt.RegisteredClaims
}

// JWTMiddleware returns an HTTP middleware that validates RS256 Bearer tokens.
//
// The middleware extracts the Authorization header value, expects the format
// "Bearer <token>", and validates the token's RS256 signature using pubKey.
// On success, the parsed Claims are stored in the request context and the next
// handler is called. On any validation failure the middleware responds with
// HTTP 401 and does not call next.
func JWTMiddleware(pubKey *rsa.PublicKey) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			authHeader := r.Header.Get("Authorization")
			if authHeader == "" {
				writeError(w, http.StatusUnauthorized, "missing Authorization header")
				return
			}

			parts := strings.SplitN(authHeader, " ", 2)
			if len(parts) != 2 || !strings.EqualFold(parts[0], "Bearer") {
				writeError(w, http.StatusUnauthorized, "Authorization header must be Bearer token")
				return
			}
			tokenStr := parts[1]

			claims := &Claims{}
			token, err := jwt.ParseWithClaims(tokenStr, claims, func(t *jwt.Token) (any, error) {
				if _, ok := t.Method.(*jwt.SigningMethodRSA); !ok {
					return nil, errors.New("unexpected signing method")
				}
				return pubKey, nil
			}, jwt.WithValidMethods([]string{"RS256"}))

			if err != nil || !token.Valid {
				writeError(w, http.StatusUnauthorized, "invalid or expired token")
				return
			}

			ctx := context.WithValue(r.Context(), claimsKey, claims)
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

// ClaimsFromContext retrieves the JWT claims stored in ctx by JWTMiddleware.
// Returns nil if no claims are present (e.g. on unauthenticated routes).
func ClaimsFromContext(ctx context.Context) *Claims {
	c, _ := ctx.Value(claimsKey).(*Claims)
	return c
}

// writeError writes a JSON error response with the given HTTP status code.
// The response body is {"error": "<message>"}.
func writeError(w http.ResponseWriter, status int, message string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{"error": message})
}
