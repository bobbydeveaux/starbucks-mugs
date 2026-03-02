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