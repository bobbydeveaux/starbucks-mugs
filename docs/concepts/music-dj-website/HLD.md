# High-Level Design: starbucks-mugs

**Created:** 2026-03-02T15:51:32Z
**Status:** Draft

## 1. Architecture Overview

Single-page web application with a lightweight backend API server. The backend proxies chart data from external music APIs, caches responses, and exposes a clean REST API to the frontend. No database required — all state is ephemeral (in-memory cache + client-side UI state).

```
[Browser SPA] → [Node.js API Server] → [Chart API (Spotify/Last.fm)]
                        ↕
                 [In-Memory Cache]
```

---

## 2. System Components

- **Frontend SPA**: React single-page app. Renders chart list, genre filter controls, random picker UI, and selected track highlight.
- **Backend API Server**: Node.js/Express server. Fetches chart data from upstream API, applies 1-hour in-memory cache, exposes `/api/charts` endpoint.
- **Cache Layer**: In-process Node.js cache (e.g., `node-cache`). Stores fetched chart responses for up to 60 minutes.
- **Chart Data Proxy**: Internal module that wraps upstream API calls, normalizes response shape, and handles fallback to stale cache on upstream failure.

---

## 3. Data Model

**Track** (in-memory, no persistence):
```
{
  id: string,
  rank: number,
  title: string,
  artist: string,
  genre: string,
  chartSource: string   // e.g. "spotify" | "lastfm"
}
```

**CachedChartResponse**:
```
{
  fetchedAt: ISO8601 timestamp,
  tracks: Track[]
}
```

No relational model needed. Data lives in server memory and client JS state only.

---

## 4. API Contracts

**GET /api/charts**
- Query params: `genre?: string`
- Response `200`:
```json
{
  "fetchedAt": "2026-03-02T15:00:00Z",
  "tracks": [
    { "id": "1", "rank": 1, "title": "Song", "artist": "Artist", "genre": "Pop" }
  ]
}
```
- Response `503` (upstream unavailable, no cache):
```json
{ "error": "Chart data unavailable. Please try again later." }
```

All randomization and re-roll logic runs client-side using the returned track array.

---

## 5. Technology Stack

### Backend
- **Node.js + Express** — lightweight, fast, well-suited for proxy/cache patterns
- **node-cache** — simple in-process TTL cache; no Redis needed at this scale
- **axios** — HTTP client for upstream chart API calls

### Frontend
- **React** (Vite build) — component model fits filter + list + selection UI cleanly
- **Plain CSS / CSS Modules** — no heavy UI library needed; DJ-optimized minimal design

### Infrastructure
- **Railway or Render** — simple PaaS deployment, handles both frontend static assets and Node.js server; zero DevOps overhead

### Data Storage
- No persistent storage. In-memory cache only. Stale cache used as fallback on upstream failure.

---

## 6. Integration Points

**Spotify Web API (Charts / Top Tracks)**
- Endpoint: `https://api.spotify.com/v1/playlists/{top-charts-id}/tracks`
- Auth: Client Credentials OAuth2 (server-side only)
- Fallback: Last.fm API `chart.getTopTracks` if Spotify unavailable

**Last.fm API (Fallback)**
- Endpoint: `https://ws.audioscrobbler.com/2.0/?method=chart.getTopTracks`
- Auth: API key (server-side env var)

Both integrations are wrapped by the Chart Data Proxy module with a unified `Track` response shape.

---

## 7. Security Architecture

- All API keys stored as server-side environment variables; never sent to the browser
- Backend acts as a proxy — client never calls chart APIs directly
- No user authentication required (public tool)
- HTTPS enforced via PaaS platform (automatic TLS)
- CORS restricted to the app's own origin

---

## 8. Deployment Architecture

Single deployment unit on Railway/Render:
- Node.js server serves both the Express API (`/api/*`) and the compiled React static build
- Environment variables injected at deploy time (API keys, cache TTL)
- Zero containers or orchestration needed at this scale

```
[Render/Railway Instance]
  ├── Express API  → /api/*
  └── Static SPA   → /*
```

---

## 9. Scalability Strategy

- In-memory cache absorbs repeated upstream API calls; 500 concurrent users share one cached response
- If traffic grows, replace `node-cache` with Redis and run multiple Node instances behind a load balancer
- Random selection is pure client-side computation — zero server load per pick/re-roll

---

## 10. Monitoring & Observability

- **Logging**: Morgan middleware logs all API requests (method, path, status, latency)
- **Error tracking**: Sentry (free tier) captures upstream API failures and unhandled exceptions
- **Uptime**: Render/Railway built-in health checks on `/api/health` endpoint
- **Cache hit rate**: Simple counter logged per request (`cache_hit: true/false`) — no dedicated metrics infra needed

---

## 11. Architectural Decisions (ADRs)

**ADR-1: Monolith over microservices**
Single Node.js server handles API proxy and static file serving. The feature scope does not justify service separation overhead.

**ADR-2: In-memory cache over Redis**
500 concurrent users with 1-hour chart TTL requires minimal cache infrastructure. `node-cache` is sufficient; Redis would be premature complexity.

**ADR-3: Client-side randomization**
Random selection and re-roll happen in the browser using the fetched track array. This keeps the server stateless and ensures sub-100ms response with no additional round trips.

**ADR-4: Spotify as primary, Last.fm as fallback**
Spotify Charts provides richer genre metadata. Last.fm is a well-documented fallback. Both are wrapped behind the proxy to keep the frontend API contract stable regardless of upstream availability.

---

## Appendix: PRD Reference

*(See attached PRD: Music DJ Website, 2026-03-02)*