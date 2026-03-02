# ROAM Analysis: music-dj-website

**Feature Count:** 6
**Created:** 2026-03-02T15:55:12Z

## Risks

1. **Spotify Charts API Availability** (High): Spotify's Web API does not expose a dedicated "top charts" endpoint publicly — the playlist-based approach (`/v1/playlists/{top-charts-id}/tracks`) relies on Spotify's internal Global Top 50 playlist IDs, which are undocumented, subject to change, and require a valid OAuth Client Credentials token. If Spotify revokes access or changes playlist IDs, the primary data source fails silently.

2. **Last.fm Genre Metadata Quality** (Medium): `chart.getTopTracks` returns minimal metadata. Genre data from Last.fm is crowd-sourced via tags and is often missing, inconsistent, or multi-valued. If the genre field is frequently null or unreliable, the GenreFilter feature degrades significantly — users get empty filtered lists.

3. **In-Memory Cache Lost on Restart** (Medium): `node-cache` is process-local. Any server restart (deploy, crash, platform sleep on free tier) flushes all cached chart data. On free-tier Render/Railway, instances spin down after inactivity, meaning the first request after cold start always hits the upstream APIs — which may fail or be slow.

4. **Spotify Client Credentials Token Expiry Race** (Medium): OAuth2 Client Credentials tokens expire in 3600 seconds. If token refresh fails (rate limit, network blip) while concurrent requests arrive, multiple requests may simultaneously attempt re-auth, causing a thundering herd against Spotify's auth endpoint and potential 429 errors.

5. **Genre Filter UX with Cross-Source Data** (Low): Spotify and Last.fm use different genre taxonomies. Normalizing genres from two sources into a consistent pill-button set is non-trivial. Mismatched genre strings (e.g., "hip-hop" vs "Hip Hop" vs "hip hop") will fragment the filter UI or produce empty filtered results.

6. **Re-roll Duplicate Selection** (Low): `Math.random()` has no built-in deduplication. With a small filtered genre pool (e.g., 3–5 tracks), re-roll has a meaningful probability of returning the same track, breaking the user expectation of "a different song."

7. **Free Tier PaaS Cold Start Latency** (Low): Render/Railway free tier instances sleep after ~15 minutes of inactivity. Cold start adds 10–30 seconds to the first request, violating the 2-second load time NFR and delivering a broken experience for the first user after idle periods.

---

## Obstacles

- **No Billboard API access in the plan**: The PRD mentions Billboard as a desired data source, but the HLD/LLD spec only implements Spotify + Last.fm. Billboard's official API is private/enterprise. This gap means the "current market data" goal relies entirely on Spotify's unofficial playlist approach, which has no SLA.

- **Spotify API credentials must be provisioned before development can proceed**: `spotifyClient.js` requires `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` from a registered Spotify Developer app. Without these, local development of the chart proxy feature (`music-dj-website-feat-chart-proxy`) is blocked entirely — mocks are needed from day one.

- **Genre data normalization strategy is undefined**: The LLD specifies a `genre: string` field on `Track` but provides no mapping table or normalization logic for reconciling Spotify's genre taxonomy against Last.fm's tag system. This design gap must be resolved before `GenreFilter` can be implemented reliably.

- **`getStale` on `node-cache` requires non-default configuration**: `node-cache` does not expose expired entries by default. Enabling stale reads requires `deleteOnExpire: false` in the constructor. This is a non-obvious configuration detail that, if missed, will silently break the stale-cache fallback path on both-API-failure scenarios.

---

## Assumptions

1. **Spotify's Global Top 50 playlist ID is stable and accessible**: The implementation assumes a known, static playlist ID can be used to fetch top tracks via Client Credentials flow. *Validation*: Manually verify the playlist ID resolves correctly with a Client Credentials token before wiring up `spotifyClient.js`; document the ID in `.env.example` with a retrieval instruction.

2. **Last.fm `chart.getTopTracks` returns genre-tagged tracks suitable for filtering**: The fallback assumes Last.fm provides usable genre data. *Validation*: Make a raw API call to `chart.getTopTracks` and inspect the `toptracks.track[].toptags` field — confirm tag availability rate and decide on a minimum-tag threshold before GenreFilter implementation.

3. **500 concurrent users will not overwhelm a single Node.js process**: The scalability NFR assumes in-memory cache absorbs all concurrency. *Validation*: Since all users share one cached response, this holds as long as cache is warm — but the assumption breaks during cache miss windows. Load test with a cache-miss scenario to confirm Express can queue concurrent upstream requests without cascading failures.

4. **A single PaaS instance on Render/Railway is sufficient for production**: The deployment plan uses zero orchestration. *Validation*: Confirm the target platform's free/starter tier memory limit (typically 512MB) is sufficient for Node.js + `node-cache` holding ~200 tracks + Express overhead. Estimate in-memory footprint before deploy.

5. **Client-side genre filtering against a full `Track[]` response is acceptable UX**: The design fetches all tracks unfiltered and applies genre filtering in the browser. *Validation*: Confirm the API returns genre on every track (not just some); if genre coverage is sparse, the filtered list will appear near-empty, making the feature feel broken. Prototype with real API data before committing to this approach.

---

## Mitigations

**Risk 1 — Spotify Charts API Availability**
- Immediately validate the target playlist ID with a spike/proof-of-concept before writing production code.
- Store the playlist ID as an env var (`SPOTIFY_TOP_CHARTS_PLAYLIST_ID`) so it can be updated without a code deploy.
- Implement Last.fm fallback from day one — do not treat it as an afterthought. Write integration tests that exercise the fallback path before merging `music-dj-website-feat-chart-proxy`.
- Add a `/api/health` response field indicating which data source was last used (`dataSource: "spotify" | "lastfm" | "stale_cache"`) to enable rapid diagnosis in production.

**Risk 2 — Last.fm Genre Metadata Quality**
- During `lastfmClient.js` implementation, inspect the `toptags` array and select the highest-weight tag as the canonical genre. Default to `"Other"` rather than `null` so tracks always appear in a catch-all filter bucket.
- Add a genre normalization map (e.g., `{ "hip-hop": "Hip Hop", "r&b": "R&B" }`) in a shared `genreNormalize.js` utility, applied in `chartProxy.js` after both clients return data.
- E2E test: assert that GenreFilter always renders at least one genre pill when chart data is present.

**Risk 3 — In-Memory Cache Lost on Restart**
- Configure Render/Railway to use a paid tier with always-on instances, or accept cold-start cache misses as a known limitation documented in the project README.
- On cold start, pre-warm the cache by calling `chartProxy.getCharts()` at server startup (`server/index.js`) before accepting traffic, so the first real user request hits cache.
- If free tier is required long-term, replace `node-cache` with a managed Redis instance (Upstash free tier: 10k requests/day, persistent). This is a one-file swap in `cache.js`.

**Risk 4 — Spotify Token Expiry Race**
- Implement a singleton token manager in `spotifyClient.js` that holds the current token and its expiry timestamp. Refresh proactively 60 seconds before expiry using a `setTimeout`. Wrap concurrent requests with a pending-refresh guard (store the in-flight promise and reuse it) to prevent thundering herd.
- Unit test: simulate concurrent calls during token expiry and assert only one token refresh HTTP call is made.

**Risk 5 — Genre Filter UX with Cross-Source Data**
- Define a canonical genre list (e.g., Pop, Hip Hop, R&B, Electronic, Rock, Latin, Other) in a constants file. Map both Spotify and Last.fm raw genres to this list during normalization in `chartProxy.js`. Tracks with unrecognized genres fall into `"Other"`.
- Integration test: assert the `GET /api/charts` response contains only canonical genre strings.

**Risk 6 — Re-roll Duplicate Selection**
- Update `pickRandom(tracks, exclude?: Track)` in `randomPick.ts` to accept an optional exclusion parameter. When `exclude` is provided, filter it from the candidate array before sampling. If the pool has only one track, return it regardless (unavoidable).
- Unit test: assert re-roll with a two-track pool never returns the same track twice across 100 invocations.

**Risk 7 — Free Tier PaaS Cold Start Latency**
- Use Render/Railway's health check ping URL with an external uptime monitor (e.g., UptimeRobot free tier) to send a request every 10 minutes, preventing the instance from sleeping.
- Alternatively, configure the `/api/health` endpoint as the health check target and set the platform's health check interval to 5 minutes.
- Document the cold-start behavior in the project README so operators understand the trade-off before choosing a free tier.

---

## Appendix: Plan Documents

### PRD
# Product Requirements Document: Music DJ Website

I want a website purely to help DJs select random top hits to play at an event. It should use current market data

**Created:** 2026-03-02T15:50:33Z
**Status:** Draft

## 1. Overview

**Concept:** Music DJ Website

I want a website purely to help DJs select random top hits to play at an event. It should use current market data

**Description:** Music DJ Website

I want a website purely to help DJs select random top hits to play at an event. It should use current market data

---

## 2. Goals

- Provide DJs with real-time access to current top charting songs from major music charts (Billboard, Spotify, etc.)
- Enable random song selection from top hits to reduce decision fatigue during live events
- Deliver a fast, distraction-free UI optimized for use during active DJ sets
- Surface genre/mood filters so DJs can narrow randomization to crowd-appropriate tracks

---

## 3. Non-Goals

- This is not a music streaming or playback platform
- This is not a playlist management or library organization tool
- This is not a social or collaborative platform for multiple DJs
- This is not a music recommendation engine based on user history or ML

---

## 4. User Stories

- As a DJ, I want to see current top 100 hits so that I always have up-to-date song choices
- As a DJ, I want to randomly select a song from the charts so that I can make quick, crowd-pleasing decisions
- As a DJ, I want to filter by genre before randomizing so that the suggestion fits the event vibe
- As a DJ, I want to see song metadata (title, artist, chart position) so that I can confidently introduce tracks
- As a DJ, I want to re-roll for a new random suggestion so that I'm not locked into one result

---

## 5. Acceptance Criteria

**Chart Data Display:**
- Given the app loads, when chart data is fetched, then top hits are displayed with title, artist, and rank

**Random Selection:**
- Given chart data is loaded, when the DJ clicks "Pick Random", then one song is selected uniformly at random from the visible list

**Genre Filter:**
- Given the DJ selects a genre filter, when they click "Pick Random", then only songs matching that genre are candidates

**Re-roll:**
- Given a song has been selected, when the DJ clicks "Re-roll", then a different song is returned from the same filtered set

---

## 6. Functional Requirements

- FR-001: Fetch and display current top chart data from at least one music chart API on page load
- FR-002: Refresh chart data automatically (max 1-hour cache) to reflect current market data
- FR-003: Display each track with title, artist name, chart position, and genre tag
- FR-004: Provide a "Pick Random" button that selects one track at random from the displayed list
- FR-005: Support genre/mood filter to narrow the pool before random selection
- FR-006: Provide a "Re-roll" action to get a new random pick without changing filters
- FR-007: Highlight the currently selected track prominently on screen

---

## 7. Non-Functional Requirements

### Performance
- Chart data must load within 2 seconds on standard broadband; random selection must respond in under 100ms

### Security
- All chart API keys stored server-side; no credentials exposed to the client browser

### Scalability
- Support up to 500 concurrent users without degraded performance using cached chart responses

### Reliability
- Display a graceful fallback (last cached chart or error message) if the upstream chart API is unavailable

---

## 8. Dependencies

- Music chart API (e.g., Billboard API, Spotify Charts, or Last.fm API) for real-time top hits data
- Backend caching layer (e.g., Redis or in-memory) to limit upstream API call frequency
- Frontend framework (e.g., React or plain JS) for responsive single-page UI

---

## 9. Out of Scope

- Audio playback, previews, or streaming of any kind
- User accounts, login, or saved preferences
- Integration with DJ hardware or software (e.g., Serato, rekordbox)
- Historical chart data or trend analysis
- Mobile native app (web only)

---

## 10. Success Metrics

- 80% of sessions result in at least one "Pick Random" action (tool is actively used, not just visited)
- Chart data freshness: 95% of page loads show data no older than 1 hour
- Page load time under 2 seconds for 90th percentile of users
- Zero client-side API key exposure incidents

---

## Appendix: Clarification Q&A

### Clarification Questions & Answers

### HLD
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
Spotify Charts provide richer genre metadata. Last.fm is a well-documented fallback. Both are wrapped behind the proxy to keep the frontend API contract stable regardless of upstream availability.

---

## Appendix: PRD Reference

*(See attached PRD: Music DJ Website, 2026-03-02)*

### LLD
# Low-Level Design: starbucks-mugs

**Created:** 2026-03-02T15:52:23Z
**Status:** Draft

## 1. Implementation Overview

New `music-dj-website/` sub-application following the existing `costa-vs-starbucks/` pattern: a self-contained directory with a Vite+React frontend and a co-located Node.js/Express backend. The frontend fetches chart data via `/api/charts`, renders a filterable track list, and handles random selection client-side. The backend proxies Spotify (primary) and Last.fm (fallback), caching responses for 60 minutes using `node-cache`.

---

## 2. File Structure

**New files:**
```
music-dj-website/
  package.json                    # scripts for client + server dev/build
  index.html                      # Vite entry point
  vite.config.ts                  # proxy /api/* → Express on port 3001
  tsconfig.json
  server/
    index.js                      # Express app, serves static build + /api/*
    routes/
      charts.js                   # GET /api/charts, GET /api/health
    services/
      cache.js                    # node-cache wrapper with stale-read support
      spotifyClient.js            # Client Credentials OAuth2 + top tracks fetch
      lastfmClient.js             # chart.getTopTracks fetch
      chartProxy.js               # primary/fallback orchestration, normalizes Track[]
  src/
    main.tsx
    App.tsx
    types.ts                      # Track, ChartResponse interfaces
    api/
      charts.ts                   # fetch wrapper for /api/charts
    components/
      TrackList.tsx               # renders ranked Track[] list
      TrackCard.tsx               # single row: rank, title, artist, genre chip
      GenreFilter.tsx             # genre filter pills
      RandomPicker.tsx            # pick/re-roll button + highlighted track display
    hooks/
      useCharts.ts                # data fetching: loading, error, tracks, fetchedAt
    utils/
      randomPick.ts               # pickRandom(tracks[]) → Track | null
    index.css
```

**Modified files:**
- `docs/concepts/music-dj-website/LLD.md` — this document

---

## 3. Detailed Component Designs

### `server/services/chartProxy.js`
On each request:
1. Check cache by key `charts:{genre|'all'}`; return if valid.
2. Attempt `spotifyClient.fetchTopTracks(genre?)`.
3. On Spotify failure, attempt `lastfmClient.fetchTopTracks(genre?)`.
4. On both failures, return stale cache entry if available; else throw `UPSTREAM_UNAVAILABLE`.
5. Normalize to `Track[]`, write to cache, return `CachedChartResponse`.

### `server/services/cache.js`
Wraps `node-cache` (TTL=3600s). Exposes `get(key)`, `set(key, value)`, `getStale(key)` (reads expired entries for fallback use).

### `src/components/RandomPicker.tsx`
Receives `tracks: Track[]` as prop. Holds `pickedTrack: Track | null` in local state. "Pick" calls `pickRandom(tracks)`, "Re-roll" re-invokes same function. Highlights selected track with accent border/background.

### `src/hooks/useCharts.ts`
Calls `fetchCharts(genre?)` on mount and when `genre` prop changes via `useEffect`. Manages `loading`, `error`, `tracks`, `fetchedAt` with `useState`.

---

## 4. Database Schema Changes

No database. All state is ephemeral — server in-memory cache and client JS state only.

---

## 5. API Implementation Details

### `GET /api/charts`
```
Handler:    charts.js → chartProxy.getCharts(genre?)
Validation: genre param — strip non-alphanumeric, max 50 chars, treat empty as null
Cache key:  charts:${genre ?? 'all'}
Success 200: { fetchedAt: ISO8601, tracks: Track[] }
Error   503: { error: "Chart data unavailable. Please try again later." }
```

### `GET /api/health`
```
Handler: inline in charts.js
Response 200: { status: "ok", cacheSize: number }
```

Morgan logs all requests: method, path, status, response time.

---

## 6. Function Signatures

```typescript
// src/api/charts.ts
fetchCharts(genre?: string): Promise<ChartResponse>

// src/utils/randomPick.ts
pickRandom(tracks: Track[]): Track | null

// src/hooks/useCharts.ts
useCharts(genre: string | null): {
  tracks: Track[];
  loading: boolean;
  error: string | null;
  fetchedAt: string | null;
}
```

```javascript
// server/services/chartProxy.js
async getCharts(genre?: string): Promise<CachedChartResponse>

// server/services/spotifyClient.js
async getAccessToken(): Promise<string>
async fetchTopTracks(genre?: string): Promise<Track[]>

// server/services/lastfmClient.js
async fetchTopTracks(genre?: string): Promise<Track[]>

// server/services/cache.js
get(key: string): CachedChartResponse | null
set(key: string, value: CachedChartResponse): void
getStale(key: string): CachedChartResponse | null
```

---

## 7. State Management

No global state manager. State is local to each layer:

- **Server**: `node-cache` module-level singleton keyed by `charts:{genre}`.
- **`App.tsx`**: `selectedGenre: string | null` via `useState`, passed as prop to `GenreFilter` and `useCharts`.
- **`useCharts`**: `tracks[]`, `loading`, `error`, `fetchedAt` via `useState`/`useEffect`.
- **`RandomPicker`**: `pickedTrack: Track | null` via local `useState`; resets to `null` when `tracks` prop changes.

---

## 8. Error Handling Strategy

| Scenario | Server behavior | Client display |
|---|---|---|
| Spotify token failure | Fallback to Last.fm | Transparent |
| Both APIs fail, cache valid | Return stale `CachedChartResponse` | "Data may be outdated" banner |
| Both APIs fail, no cache | Throw `UPSTREAM_UNAVAILABLE` → 503 | "Chart data unavailable. Try again later." |
| Network error on client | `useCharts` sets `error` string | Error message below filter bar |
| Invalid genre param | Sanitize → treat as `null` | No error shown |

Server-side errors logged via `console.error`; Sentry captures uncaught exceptions via Express error middleware.

---

## 9. Test Plan

### Unit Tests

- `server/services/cache.test.js`: TTL expiry returns null, `getStale` returns expired entry, keys isolated per genre
- `server/services/chartProxy.test.js`: cache hit skips fetch, Spotify success path, Spotify-fail→Last.fm, both-fail→stale, both-fail→throws
- `server/services/spotifyClient.test.js`: token fetch mocked, track shape normalization, HTTP error propagation
- `server/services/lastfmClient.test.js`: track normalization, API error propagation
- `src/utils/randomPick.test.ts`: empty array returns null, result always in input array, distribution is uniform over many runs
- `src/hooks/useCharts.test.ts`: sets loading true on fetch start, sets tracks on success, sets error on 503, re-fetches on genre change

### Integration Tests

- `server/routes/charts.test.js`:
  - Mock `chartProxy.getCharts` → 200 with valid `Track[]` body shape
  - Mock `chartProxy.getCharts` to throw `UPSTREAM_UNAVAILABLE` → 503 with error body
  - `genre` query param forwarded to `chartProxy`
  - Health endpoint returns `{ status: "ok" }`

### E2E Tests

- `music-dj-website/e2e/charts.spec.ts`:
  - Page loads and displays at least one track row
  - Selecting a genre filter updates the visible track list
  - Clicking "Pick" highlights exactly one track
  - Clicking "Re-roll" changes the highlighted track

---

## 10. Migration Strategy

No existing code to migrate. Steps to add the sub-application:

1. Create `music-dj-website/` with own `package.json` (independent from root).
2. Add `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `LASTFM_API_KEY` to `.env.example`.
3. Configure Vite dev proxy: `/api/*` → `http://localhost:3001`.
4. Add `dev:music-dj` and `build:music-dj` targets to root `Makefile`.
5. Configure Render/Railway: build command `npm run build`, start command `node server/index.js`.

---

## 11. Rollback Plan

Self-contained directory — no shared DB or schema changes. Rollback options:

- **Platform rollback**: Render/Railway dashboard → "Redeploy previous" (one click, ~30s).
- **Code rollback**: `git revert` the merge commit, redeploy.
- **Feature isolation**: Other sub-apps (`costa-vs-starbucks/`, `markdowntopdf/`) are unaffected.

---

## 12. Performance Considerations

- **Cache absorption**: 1-hour TTL means ~1 upstream API call/hour per genre regardless of concurrent users.
- **Client-side randomization**: `pickRandom` is O(1) — `Math.floor(Math.random() * tracks.length)`. Zero server round-trip per re-roll.
- **Genre filtering**: Applied client-side from the full cached array (`<200` tracks). No additional round-trips.
- **Bundle size**: No heavy UI library; target `<150KB` gzipped. Vite tree-shakes unused exports.
- **Stale-on-expiry**: First request after TTL expiry incurs upstream latency. If p99 degrades, introduce background TTL refresh (pre-fetch before expiry).

---

## Appendix: Existing Repository Structure

## Repository File Structure

*(See full repository tree in HLD Appendix — music-dj-website/ does not yet exist and will be created as a new sub-application directory alongside `costa-vs-starbucks/` and `markdowntopdf/`.)*