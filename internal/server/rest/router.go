package rest

import (
	"crypto/rsa"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/go-chi/chi/v5/middleware"
)

// NewRouter returns a configured chi.Router for the TripWire dashboard API.
//
// Route layout:
//
//	GET /healthz            – liveness probe (no authentication required)
//	GET /api/v1/alerts      – paginated alert query (JWT required)
//	GET /api/v1/hosts       – list all hosts (JWT required)
//	GET /api/v1/audit       – tamper-evident audit log query (JWT required)
//
// pubKey is the RSA public key used to verify RS256 Bearer tokens on all
// /api routes.  Pass nil to disable JWT validation (useful in tests that
// cover only request parsing / response formatting).
func NewRouter(srv *Server, pubKey *rsa.PublicKey) http.Handler {
	r := chi.NewRouter()

	// Built-in chi middleware for observability and hygiene.
	r.Use(middleware.RequestID)
	r.Use(middleware.RealIP)
	r.Use(middleware.Recoverer)

	// Health check – no authentication.
	r.Get("/healthz", srv.handleHealthz)

	// Authenticated API routes.
	r.Route("/api/v1", func(r chi.Router) {
		if pubKey != nil {
			r.Use(JWTMiddleware(pubKey))
		}

		r.Get("/alerts", srv.handleGetAlerts)
		r.Get("/hosts", srv.handleGetHosts)
		r.Get("/audit", srv.handleGetAudit)
	})

	return r
}
