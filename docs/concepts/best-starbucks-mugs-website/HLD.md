# High-Level Design: starbucks-mugs

**Created:** 2026-02-24T09:44:37Z
**Status:** Draft

## 1. Architecture Overview

Pure static site architecture — no backend, no server-side logic. All functionality runs in the browser. A single HTML page fetches `mugs.json` via the Fetch API on load, then performs all search, filtering, and rendering client-side. Deployed to a static host (GitHub Pages or Netlify).

```
Browser
  └── index.html  (shell + markup)
  └── style.css   (responsive layout, modal, grid)
  └── app.js      (data fetch, filter engine, DOM rendering, modal)
  └── mugs.json   (catalog data — single source of truth)
```

---

## 2. System Components

| Component | Responsibility |
|-----------|---------------|
| `index.html` | Page shell, filter controls, grid container, modal container, accessibility landmarks |
| `app.js` | Fetch + cache `mugs.json`; filter/search engine; card + modal renderer; keyboard nav |
| `style.css` | Responsive CSS Grid layout, modal overlay, card styles, theme tokens |
| `mugs.json` | Catalog data — 50+ entries, single source of truth for all mug metadata |
| Filter Engine | Debounced text search + series/year-range multi-filter, runs in-memory |
| Modal Controller | Opens/closes detail modal, manages focus trap, ESC/backdrop handling |
| Image Loader | Native `loading="lazy"` + SVG placeholder fallback for missing images |

---

## 3. Data Model

**Mug entity** (one object per entry in `mugs.json`):

```json
{
  "id": "yah-new-york-2019",
  "name": "You Are Here — New York",
  "series": "You Are Here",
  "year": 2019,
  "region": "North America",
  "edition": "Limited",
  "material": "Ceramic",
  "capacity_oz": 14,
  "price_usd": 19.95,
  "description": "Iconic NYC skyline with Siren motif in green and white.",
  "image": "images/yah-new-york-2019.jpg",
  "tags": ["city", "new york", "limited", "usa"]
}
```

**Top-level structure:**
```json
{ "version": "1.0", "mugs": [ ...MugEntry ] }
```

No relational links needed — all data is self-contained per entry.

---

## 4. API Contracts

No server API. One data endpoint:

**GET `/mugs.json`**
- Triggered by Fetch API on `DOMContentLoaded`
- Response: `{ version: string, mugs: MugEntry[] }`
- Cached by browser after first load (via Cache-Control headers on static host)
- Client validates presence of required fields; missing optional fields degrade gracefully

No other network calls are made at runtime.

---

## 5. Technology Stack

### Backend
None — static files only.

### Frontend
- **HTML5** — semantic markup, ARIA roles for accessibility
- **Vanilla JavaScript (ES2020)** — no framework; Fetch API, array filter/reduce, optional chaining
- **CSS3** — custom properties (design tokens), CSS Grid, Flexbox, media queries
- **Native `loading="lazy"`** — browser-native image lazy loading

### Infrastructure
- **GitHub Pages** or **Netlify** — zero-config static hosting, free tier
- **CDN** — assets served via host's built-in CDN edge network

### Data Storage
- **`mugs.json`** — flat file, version-controlled in repository, single source of truth
- No database, no localStorage, no cookies

---

## 6. Integration Points

| Integration | Purpose | Notes |
|-------------|---------|-------|
| Google Fonts CDN | Typography (e.g., Inter or Playfair Display) | Optional; system font stack fallback |
| Local SVG placeholder | Image fallback for mugs without photos | Inline SVG, no external dependency |
| Static host CDN | Asset delivery at edge | Netlify/GitHub Pages automatic |

No webhooks, no third-party APIs, no analytics scripts in initial release.

---

## 7. Security Architecture

- **No attack surface** — no server, no database, no user input persisted anywhere
- **No XSS risk** — all DOM writes use `textContent` / `createElement`; never `innerHTML` with user data
- **No secrets** — no API keys, tokens, or credentials in codebase
- **CSP header** — static host configured with `Content-Security-Policy: default-src 'self'; font-src fonts.gstatic.com` to block unexpected resource loads
- **Subresource Integrity** — optional SRI hash on any CDN font/icon link

---

## 8. Deployment Architecture

```
GitHub repo (main branch)
    │
    ▼
GitHub Actions (CI)
    │  lint JS/CSS, validate mugs.json schema
    ▼
GitHub Pages / Netlify
    │  serves static files from repo root or /dist
    ▼
CDN edge nodes → Browser
```

- No build step required (no bundler/transpiler) — files served as-is
- `mugs.json` updates trigger automatic redeploy via git push
- Cache-Control: `max-age=3600` for JSON; `max-age=86400` for images

---

## 9. Scalability Strategy

- **Data tier**: JSON flat file scales to 1,000+ entries (~300 KB uncompressed) within browser memory limits; no pagination needed at this scale
- **Filter engine**: In-memory array operations on 1,000 entries complete in <10ms; debounce (200ms) prevents unnecessary re-renders
- **Images**: Lazy loading ensures only visible images are fetched; total asset size decoupled from catalog size
- **No server to scale** — static hosting inherently handles unlimited concurrent users via CDN

---

## 10. Monitoring & Observability

| Concern | Approach |
|---------|----------|
| Performance | Lighthouse CI in GitHub Actions on each PR; target score ≥ 90 mobile |
| JS errors | Browser console; no error tracking service in v1 |
| Accessibility | axe-core automated audit in CI pipeline |
| Uptime | GitHub Pages / Netlify status page; no custom monitoring needed |
| Data quality | JSON schema validation script run in CI to catch malformed entries |

---

## 11. Architectural Decisions (ADRs)

**ADR-1: No framework (Vanilla JS)**
Rationale: Catalog is read-only with simple DOM operations. React/Vue would add 40–100 KB overhead with no benefit. Vanilla JS keeps load time minimal and eliminates dependency churn.

**ADR-2: JSON flat file over CMS/database**
Rationale: PRD explicitly excludes backend. JSON is version-controlled, human-editable, and sufficient for 500+ static entries. Schema validated in CI.

**ADR-3: Client-side filtering over server-side search**
Rationale: With <1,000 entries loaded once, in-memory filtering is faster than a round-trip and works offline after first load.

**ADR-4: Extend existing files, do not replace**
Rationale: PRD dependency constraint. Incremental changes preserve working baseline and reduce regression risk.

**ADR-5: Native lazy loading over JavaScript intersection observer**
Rationale: `loading="lazy"` is supported in all target browsers (Chrome, Firefox, Safari) and requires zero JS, reducing complexity and improving Lighthouse score.

---

## Appendix: PRD Reference

*(See PRD document: Best Starbucks Mugs Website, created 2026-02-24)*