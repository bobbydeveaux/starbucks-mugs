# TripWire Dashboard UI

**Package:** `dashboard-ui/`
**Sprint:** 5
**Status:** In progress

---

## Overview

The TripWire Security Dashboard is a React 18 + TypeScript single-page application built with Vite.
It provides a real-time view of tripwire alerts across all monitored hosts.

---

## Project Structure

```
dashboard-ui/
├── index.html                   # HTML entry point
├── vite.config.ts               # Vite + Vitest configuration
├── tsconfig.json                # TypeScript strict mode config
├── package.json                 # Dependencies
└── src/
    ├── main.tsx                 # React root mount
    ├── App.tsx                  # Router + OIDC auth guards
    ├── vite-env.d.ts            # Vite env type declarations
    ├── setupTests.ts            # Vitest setup (jest-dom matchers)
    ├── api/
    │   ├── client.ts            # API client + bearer token storage
    │   └── types.ts             # TypeScript types for REST payloads
    └── auth/
        └── oidc.ts              # OIDC Authorization Code + PKCE flow
```

---

## Authentication

Authentication is handled via **OIDC Authorization Code Flow with PKCE**.
The identity provider is configured through environment variables.

### Environment Variables

| Variable | Description |
|---|---|
| `VITE_API_BASE_URL` | Base URL of the dashboard REST API (default: `""` — same origin) |
| `VITE_OIDC_AUTHORIZATION_ENDPOINT` | OIDC provider authorization endpoint |
| `VITE_OIDC_TOKEN_ENDPOINT` | OIDC provider token endpoint |
| `VITE_OIDC_CLIENT_ID` | Client ID registered with the OIDC provider |
| `VITE_OIDC_REDIRECT_URI` | Redirect URI (default: `<origin>/auth/callback`) |
| `VITE_OIDC_SCOPE` | OAuth scopes (default: `openid profile email`) |

Create a `.env.local` file in `dashboard-ui/` for local development:

```env
VITE_API_BASE_URL=http://localhost:8080
VITE_OIDC_AUTHORIZATION_ENDPOINT=https://auth.example.com/authorize
VITE_OIDC_TOKEN_ENDPOINT=https://auth.example.com/token
VITE_OIDC_CLIENT_ID=tripwire-dashboard
VITE_OIDC_REDIRECT_URI=http://localhost:3000/auth/callback
VITE_OIDC_SCOPE=openid profile email
```

### Auth Flow

1. Unauthenticated users at any route are redirected to `/login`.
2. Clicking "Sign in with SSO" calls `initiateLogin()`, which:
   - Generates a PKCE code verifier + challenge (SHA-256).
   - Stores state and verifier in `sessionStorage`.
   - Redirects to the OIDC provider's authorization endpoint.
3. After successful provider auth, the provider redirects to `/auth/callback`.
4. `handleCallback()` validates state, exchanges the code for tokens, and stores
   the `access_token` in `localStorage` via `setToken()`.
5. The user is redirected to the originally requested route.

---

## API Client

`dashboard-ui/src/api/client.ts` provides:

- **Token storage**: `setToken`, `getToken`, `clearToken`, `isAuthenticated`
- **Typed fetch helpers** (all attach `Authorization: Bearer <token>`):
  - `getHealth()` → `HealthResponse`
  - `getAlerts(params)` → `Alert[]`
  - `getHosts()` → `Host[]`
  - `getAudit(params)` → `AuditEntry[]`
- **`ApiResponseError`**: thrown on non-2xx responses; carries `.status` and `.body`

---

## Development

```bash
cd dashboard-ui
npm install
npm run dev          # Start Vite dev server on http://localhost:3000
npm test             # Run Vitest unit tests
npm run typecheck    # TypeScript strict mode check
npm run build        # Production build
```

The dev server proxies `/api/*` to `http://localhost:8080` and `/ws/*` as WebSocket
to `ws://localhost:8080`, so no CORS configuration is needed during development.

---

## Testing

Tests live in `src/**/*.test.{ts,tsx}` and use **Vitest** + **Testing Library**.

| Test file | Coverage |
|---|---|
| `src/api/client.test.ts` | Token storage, Authorization header, query params, error handling |
| `src/auth/oidc.test.ts` | Callback state validation, token exchange, logout |
| `src/App.test.tsx` | Route guard redirect, authenticated render |
