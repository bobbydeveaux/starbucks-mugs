# ROAM Analysis: best-starbucks-mugs-website

**Feature Count:** 3
**Created:** 2026-02-24T09:47:20Z

## Risks

1. **Missing Mug Photography** (High): The `images/` directory contains only `.gitkeep` — no actual mug photos exist. A catalog site for visual collectors with 50+ placeholder SVGs instead of real images severely undermines the core value proposition of a "visually stunning" experience.

2. **Trademark and Intellectual Property Exposure** (High): Reproducing Starbucks product names, series branding, and official product photography without license creates potential trademark and copyright exposure. The site is explicitly positioned as a definitive reference, increasing visibility and therefore risk.

3. **Catalog Data Accuracy** (High): Manually curated JSON entries for 50+ real collector mugs (years, edition sizes, pricing, region availability) will contain errors without a verified source. Inaccurate metadata on a site aimed at collectors and researchers directly damages credibility.

4. **Schema Migration Breaking Existing Functionality** (Medium): Renaming `price` → `price_usd` and restructuring the root from a bare array to `{ version, mugs[] }` in `mugs.json` will break any existing code paths that reference `mug.price` or iterate the root directly. The legacy fallback guard in `loadMugs()` mitigates the envelope change but does not cover the field rename.

5. **WCAG 2.1 AA Compliance on Filter Bar** (Medium): The filter bar introduces new interactive elements (search input, series dropdown, year range inputs, reset button) and the modal requires a focus trap. Missing ARIA live region updates or broken keyboard navigation will fail the stated accessibility acceptance criterion.

6. **Lighthouse Mobile Score ≥ 90** (Medium): Rendering 50+ cards with images on initial load, even with `loading="lazy"`, can degrade Cumulative Layout Shift (CLS) if image dimensions are not declared. No CI Lighthouse check is configured yet, so regressions will go undetected until manual audit.

7. **Long-Term Data Staleness** (Low): A static JSON file with no contribution workflow or update process will become outdated as Starbucks releases new mugs and discontinues old ones. A stale catalog contradicts the "definitive reference" goal over time.

---

## Obstacles

- **No mug images on disk**: The `images/` directory has only `.gitkeep`. Sourcing, licensing, and committing 50+ images (or confirming that the placeholder SVG fallback is the intended v1 approach) must be resolved before the visual experience can be evaluated.
- **CI pipeline not yet configured**: The HLD references GitHub Actions for Lighthouse CI, axe-core audits, and JSON schema validation, but no `.github/workflows/` directory exists in the current repo structure. None of the quality gates described in the HLD are enforced today.
- **Existing `mugs.json` uses legacy schema**: The current file has ~6 entries with `price` (not `price_usd`) in a bare array format. The new `filterMugs()` and `populateSeriesFilter()` functions depend on the `series`, `year`, `region`, and `tags` fields — none of which exist yet. The catalog data enabler feature must land before UI features are testable end-to-end.
- **No verified data source identified**: The PRD requires 50+ entries with accurate metadata, but no collector database, official Starbucks archive, or community source has been identified as the authoritative reference for mug details.

---

## Assumptions

1. **The existing four files provide a working baseline**: It is assumed that `app.js`, `index.html`, `style.css`, and `mugs.json` are in a functional, non-broken state that can be extended incrementally. *Validation: run the site locally and confirm zero console errors before beginning feature work.*

2. **Placeholder SVG fallback is acceptable at launch for mugs without photos**: It is assumed that shipping 50+ entries with a generic cup silhouette for missing images meets the v1 bar and that real photography is a post-launch concern. *Validation: confirm with the product owner that a no-photo launch is acceptable before committing to this approach.*

3. **Public collector community data is sufficiently accurate for v1**: Mug names, series, years, and approximate pricing sourced from collector forums and fan wikis are assumed to be accurate enough for a v1 reference catalog. *Validation: cross-reference at least two independent sources per entry before publishing.*

4. **Target browsers (Chrome, Firefox, Safari) all support ES2020, Fetch API, and `loading="lazy"` without polyfills**: The HLD explicitly targets these browsers and native features. *Validation: check MDN compatibility tables for `loading="lazy"`, optional chaining, and `fetch` against the minimum browser versions in scope.*

5. **GitHub Pages or Netlify will serve the static files with appropriate `Cache-Control` headers**: The offline-after-first-load reliability requirement and JSON caching strategy depend on the host setting `max-age` headers. *Validation: deploy a test page and inspect response headers via DevTools before relying on caching behavior.*

---

## Mitigations

### Risk 1 — Missing Mug Photography
- Decide explicitly at project kickoff whether v1 ships with real images or placeholder-only, and document this in the README.
- If real images are required: identify Creative Commons licensed mug photos from collector communities (Flickr, Reddit r/starbucks) and attribute correctly.
- Implement the `img.onerror` → `placeholder.svg` fallback as the first code change so the site is never visually broken regardless of image availability.
- Declare explicit `width` and `height` attributes on all `<img>` tags in `createCard()` to prevent CLS even when images are absent.

### Risk 2 — Trademark and Intellectual Property Exposure
- Add a clearly visible disclaimer in the site footer: "This is an unofficial collector reference site. Not affiliated with or endorsed by Starbucks Corporation."
- Do not reproduce official Starbucks product photography scraped from starbucks.com; use only Creative Commons or community-contributed images.
- Avoid reproducing verbatim marketing copy from official Starbucks pages; write original descriptions.
- Keep the site non-commercial (no ads, no affiliate links) to reduce the profile of potential IP claims — this is already a stated non-goal in the PRD.

### Risk 3 — Catalog Data Accuracy
- Cross-reference each mug entry against at least two independent sources (e.g., eBay sold listings for year/pricing, collector wikis for edition details) before adding to `mugs.json`.
- Add an optional `"verified": true/false` field to the schema and surface unverified entries visually (e.g., a small badge) so users know which data needs review.
- Add a "Report an error" link on each modal that opens a pre-filled GitHub Issue template, enabling community corrections without requiring contributor setup.
- Run the JSON schema validation script in CI to catch structural errors; data accuracy validation remains a manual process.

### Risk 4 — Schema Migration Breaking Existing Functionality
- Before committing the new `mugs.json`, update all `mug.price` references in `app.js` and `app.test.js` to `mug.price_usd` in the same commit to keep the rename atomic.
- The legacy-array fallback in `loadMugs()` is already designed into the LLD — keep it in place for at least one release cycle.
- Run the existing test suite against the updated `mugs.json` before merging to confirm no regressions in `createCard()`, `openModal()`, and any existing tests that reference price.
- Treat `best-starbucks-mugs-website-feat-catalog-data` as a hard dependency gate: do not begin UI feature work until this enabler passes all tests.

### Risk 5 — WCAG 2.1 AA Compliance on Filter Bar
- Add `aria-live="polite"` and `aria-atomic="true"` to `#results-count` (already specified in the LLD) and manually verify that screen readers announce filter result changes.
- Implement focus trap in the modal from the start (not as a follow-up), trapping Tab/Shift+Tab between the first and last focusable modal elements.
- Run axe-core browser extension against the filter bar and modal after initial implementation; fix all violations before merging.
- Add axe-core as an automated CI check (GitHub Actions + axe-cli on the built HTML) to prevent accessibility regressions on future PRs.

### Risk 6 — Lighthouse Mobile Score ≥ 90
- Declare explicit `width` and `height` on card `<img>` elements to eliminate CLS before images load.
- Add a Lighthouse CI GitHub Actions workflow (using `lighthouse-ci` npm package) targeting the production URL on every PR against `main`.
- Set a budget: fail the CI check if Lighthouse mobile performance score drops below 85 (warning) or 80 (hard fail), giving headroom before the 90 target becomes critical.
- Audit and compress any mug images added to the repo (target: <100 KB per JPEG at 2x resolution) using a CI image optimization step or documented contributor guidelines.

### Risk 7 — Long-Term Data Staleness
- Create a `CONTRIBUTING.md` documenting how to add new mug entries (schema reference, required fields, image naming convention, PR process).
- Add a GitHub Issue template: "Add/Update mug entry" with fields mapping to the JSON schema to lower the barrier for community contributions.
- Include a `"last_reviewed"` timestamp at the top level of `mugs.json` so visitors can see how recently the catalog was audited.

---

## Appendix: Plan Documents

### PRD
# Product Requirements Document: Best Starbucks Mugs Website

I want a Starbucks mugs website - but the best Starbucks website in the world covering all the different types of Starbucks collectors mugs ever

**Created:** 2026-02-24T09:43:42Z
**Status:** Draft

## 1. Overview

**Concept:** Best Starbucks Mugs Website

I want a Starbucks mugs website - but the best Starbucks website in the world covering all the different types of Starbucks collectors mugs ever

**Description:** Best Starbucks Mugs Website

I want a Starbucks mugs website - but the best Starbucks website in the world covering all the different types of Starbucks collectors mugs ever

---

## 2. Goals

- Provide the most comprehensive catalog of Starbucks collector mugs ever assembled, covering every major series and limited release
- Enable collectors to quickly find mugs by series, region, year, or keyword via filtering and search
- Deliver rich mug detail pages with metadata (series, year, edition size, materials, artist notes) beyond basic name/price
- Achieve a visually stunning, fast-loading experience that rivals official retail sites in polish
- Become the definitive reference resource for Starbucks mug collectors worldwide

---

## 3. Non-Goals

- No e-commerce or purchase functionality (no cart, checkout, or payment processing)
- No user accounts, authentication, or saved collections
- No real-time inventory or pricing sync with Starbucks or third-party retailers
- No mobile app — web only
- No user-submitted content or community features in this phase

---

## 4. User Stories

- As a **collector**, I want to browse mugs by series (City, Holiday, Reserve, You Are Here) so I can find gaps in my collection
- As a **new enthusiast**, I want to search by city or keyword so I can locate a specific mug quickly
- As a **researcher**, I want detailed metadata (year, edition, materials) so I can verify authenticity and value
- As a **visual browser**, I want high-quality images in a responsive grid so I can enjoy the collection aesthetically
- As a **mobile user**, I want a responsive layout so I can browse on any device
- As a **collector**, I want to filter by decade or release year so I can explore the historical catalog chronologically

---

## 5. Acceptance Criteria

**Browse by series:**
- Given the catalog is loaded, when a user selects a series filter, then only mugs from that series are displayed

**Search:**
- Given the catalog page, when a user types in the search box, then cards filter in real-time to matching mug names, cities, or series

**Detail modal:**
- Given a mug card is visible, when the user clicks it, then a modal opens showing full metadata: name, series, year, price, description, and image
- Given the modal is open, when the user presses ESC or clicks the backdrop, then the modal closes

**Responsive grid:**
- Given any viewport width ≥ 320px, the grid renders without horizontal overflow and images load without layout shift

---

## 6. Functional Requirements

- **FR-001** Expand `mugs.json` to 50+ entries covering City Collection, Holiday, You Are Here, Reserve, Siren, Anniversary, and Dot Collection series
- **FR-002** Add metadata fields: `series`, `year`, `edition`, `material`, `region`, `tags[]`
- **FR-003** Implement client-side search filtering by name, city, series, and tags with debounced input
- **FR-004** Implement series and year-range filter controls above the grid
- **FR-005** Display mug count and active filter summary above the grid
- **FR-006** Enhance modal to show all metadata fields with a structured layout
- **FR-007** Support keyboard navigation (Tab, Enter, ESC) throughout catalog and modal
- **FR-008** Implement lazy loading for mug card images to improve initial load performance

---

## 7. Non-Functional Requirements

### Performance
Page initial load under 2 seconds on a 4G connection; image lazy-loading prevents blocking render; JSON data file under 200 KB uncompressed.

### Security
No user input is persisted or sent to a server; search/filter operates client-side only; no third-party scripts beyond a CDN font/icon library.

### Scalability
Data-driven architecture (JSON) allows catalog expansion to 500+ entries without code changes; filter/search must remain responsive up to 1,000 entries.

### Reliability
Static site with no backend dependency; fully functional offline after first load if served with appropriate cache headers; graceful degradation if images fail to load (alt text + placeholder).

---

## 8. Dependencies

- Existing `mugs.json`, `app.js`, `style.css`, `index.html` — extend, do not replace
- Browser Fetch API for JSON loading (no external HTTP library needed)
- Optional: Google Fonts or system font stack for typography
- Optional: A placeholder image service (e.g., local SVG fallback) for mugs without photography

---

## 9. Out of Scope

- Backend API, database, or CMS
- User accounts, wishlists, or collection tracking
- Price comparison or affiliate links to purchase mugs
- Mug value estimation or appraisal tools
- Internationalization / multi-language support
- Admin interface for managing catalog data

---

## 10. Success Metrics

- Catalog contains 50+ unique mug entries across at least 6 distinct series at launch
- Search returns results within 100ms of user input on a mid-range device
- All mug cards and modals pass WCAG 2.1 AA accessibility audit
- Lighthouse performance score ≥ 90 on mobile
- Zero JavaScript errors on page load in Chrome, Firefox, and Safari

---

## Appendix: Clarification Q&A

### Clarification Questions & Answers
HLD: # High-Level Design: starbucks-mugs

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
LLD: Now I have all the context needed to write the LLD. Let me generate it.

# Low-Level Design: starbucks-mugs

**Created:** 2026-02-24T09:45:26Z
**Status:** Draft

## 1. Implementation Overview

Extend the existing static site (no rewrite) with: (1) an expanded `mugs.json` data model, (2) a debounced filter/search engine in `app.js`, (3) filter controls in `index.html`, (4) filter bar CSS in `style.css`, and (5) an SVG placeholder fallback for missing images. All logic remains client-side; no build step required.

---

## 2. File Structure

```
index.html      MODIFY — add #filter-bar section above #grid
style.css       MODIFY — add filter bar, empty-state, placeholder styles
app.js          MODIFY — add filterMugs(), debounce(), image fallback; wire filter events
mugs.json       MODIFY — expand schema; add 44+ entries to reach 50 total
images/         EXISTING — add mug JPGs; placeholder SVG at images/placeholder.svg
app.test.js     MODIFY — add tests for filterMugs() and image fallback
```

---

## 3. Detailed Component Designs

### 3.1 Filter Bar (`index.html`)

Insert between `<header>` and `<main>`:

```html
<section id="filter-bar" aria-label="Filter mugs">
  <input id="search" type="search" placeholder="Search mugs…" aria-label="Search mugs" />
  <select id="filter-series" aria-label="Filter by series">
    <option value="">All Series</option>
  </select>
  <label>
    Year:
    <input id="year-min" type="number" min="1990" max="2030" placeholder="From" aria-label="Year from" />
    <span aria-hidden="true">–</span>
    <input id="year-max" type="number" min="1990" max="2030" placeholder="To" aria-label="Year to" />
  </label>
  <button id="filter-reset" type="button">Reset</button>
</section>
<p id="results-count" aria-live="polite" aria-atomic="true"></p>
```

### 3.2 Filter Engine (`app.js`)

New module-level state alongside `currentMug`:

```js
let allMugs = [];       // full catalog, set once after fetch
let filterState = { query: '', series: '', yearMin: null, yearMax: null };
```

Core filter function — pure, testable:

```js
/**
 * @param {MugEntry[]} mugs
 * @param {{ query: string, series: string, yearMin: number|null, yearMax: number|null }} state
 * @returns {MugEntry[]}
 */
function filterMugs(mugs, state) { ... }
```

Matching rules (all conditions AND-combined):
- `query`: case-insensitive substring match on `name`, `series`, `region`, `tags.join()`
- `series`: exact equality on `mug.series` (empty string = no filter)
- `yearMin`/`yearMax`: inclusive range on `mug.year` (null = unbounded)

### 3.3 Debounce Utility (`app.js`)

```js
/**
 * @param {Function} fn
 * @param {number} delay  — 200ms default
 * @returns {Function}
 */
function debounce(fn, delay = 200) { ... }
```

The `search` input listener wraps `applyFilters` with `debounce`; `select` and number inputs call `applyFilters` directly (no debounce needed for discrete controls).

### 3.4 Render Pipeline (`app.js`)

```js
function applyFilters() {
  const filtered = filterMugs(allMugs, filterState);
  renderCards(filtered);
  updateResultsCount(filtered.length, allMugs.length);
}

function populateSeriesFilter(mugs) { ... }  // builds <option> list from distinct series values
function updateResultsCount(shown, total) { ... }  // writes to #results-count
```

`loadMugs()` return type changes from `Promise<Array>` to `Promise<{ version: string, mugs: MugEntry[] }>` to match updated JSON schema. Bootstrap becomes:

```js
loadMugs()
  .then(({ mugs }) => {
    allMugs = mugs;
    populateSeriesFilter(mugs);
    applyFilters();
  })
  .catch(err => { ... });
```

### 3.5 Image Fallback (`app.js`)

In `createCard` and `openModal`, after setting `img.src`:

```js
img.onerror = () => { img.src = 'images/placeholder.svg'; img.onerror = null; };
```

`images/placeholder.svg` — inline SVG cup silhouette, ~400 bytes, no external dependency.

### 3.6 Expanded `mugs.json` Schema

Top-level structure changes from a bare array to:

```json
{ "version": "1.0", "mugs": [ ...MugEntry ] }
```

Each entry adds optional fields (existing 6 entries retain `id`, `name`, `price`, `image`, `description`):

| Field | Type | Required |
|---|---|---|
| `id` | string | yes |
| `name` | string | yes |
| `series` | string | yes |
| `year` | number | yes |
| `region` | string | yes |
| `edition` | string | no |
| `material` | string | no |
| `capacity_oz` | number | no |
| `price_usd` | number | yes (rename from `price`) |
| `description` | string | yes |
| `image` | string | yes |
| `tags` | string[] | yes |

`price` is renamed `price_usd`; `app.js` references updated accordingly.

---

## 4. Database Schema Changes

None — flat JSON file only. Schema migration: rename `price` → `price_usd` and restructure root from array to `{ version, mugs }` in `mugs.json`. Handled in a single file edit.

---

## 5. API Implementation Details

No server API. `loadMugs()` updated:

```js
async function loadMugs() {
  const response = await fetch('./mugs.json');
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const data = await response.json();
  // graceful fallback: bare array (legacy) or versioned envelope
  return Array.isArray(data) ? { version: '0', mugs: data } : data;
}
```

The legacy-array fallback ensures old `mugs.json` format does not break the page during incremental migration.

---

## 6. Function Signatures

```js
// Existing — signatures unchanged
async function loadMugs(): Promise<{ version: string, mugs: MugEntry[] }>
function createCard(mug: MugEntry): HTMLElement
function renderCards(mugs: MugEntry[]): void
function openModal(mug: MugEntry): void
function closeModal(): void

// New
function filterMugs(mugs: MugEntry[], state: FilterState): MugEntry[]
function debounce(fn: Function, delay?: number): Function
function applyFilters(): void
function populateSeriesFilter(mugs: MugEntry[]): void
function updateResultsCount(shown: number, total: number): void

// Types (JSDoc)
// @typedef {{ id:string, name:string, series:string, year:number,
//   region:string, edition?:string, material?:string, capacity_oz?:number,
//   price_usd:number, description:string, image:string, tags:string[] }} MugEntry
// @typedef {{ query:string, series:string, yearMin:number|null, yearMax:number|null }} FilterState
```

---

## 7. State Management

All state is module-level variables in `app.js` — no framework, no localStorage:

| Variable | Type | Purpose |
|---|---|---|
| `allMugs` | `MugEntry[]` | Full catalog; set once on load; never mutated |
| `currentMug` | `MugEntry\|null` | Currently open modal entry |
| `filterState` | `FilterState` | Current filter values; updated by UI events |

`filterState` is mutated in-place by each input event handler, then `applyFilters()` re-runs the filter and re-renders. No derived state is cached.

---

## 8. Error Handling Strategy

| Scenario | Handling |
|---|---|
| `fetch` network failure | `catch` → `grid.innerHTML = '<p class="grid-error">…</p>'` (existing) |
| `mugs.json` HTTP error (4xx/5xx) | Same catch path via `throw new Error(\`HTTP ${response.status}\`)` |
| Missing `mugs` field in JSON | `Array.isArray` guard in `loadMugs()` returns `{ mugs: [] }` |
| Image 404 | `img.onerror` → `images/placeholder.svg`; `onerror` nulled to prevent loop |
| Filter yields zero results | `renderCards([])` renders empty grid; `#results-count` shows "0 of N mugs" |
| Invalid year inputs (NaN) | `parseInt` with `isNaN` guard; null treated as unbounded |

No custom error codes. All user-facing messages use `textContent`, never `innerHTML`.

---

## 9. Test Plan

### Unit Tests

Add to `app.test.js` (Node + built-in `assert`, no test runner):

- `filterMugs` — empty query returns all mugs
- `filterMugs` — query matches name (case-insensitive)
- `filterMugs` — query matches tag substring
- `filterMugs` — series filter excludes non-matching series
- `filterMugs` — yearMin/yearMax bounds (inclusive)
- `filterMugs` — all filters combined narrows results correctly
- `filterMugs` — no matches returns empty array
- `debounce` — callback not called until delay elapses (use `setTimeout` mock via `Date.now` stub)
- `createCard` — `img.onerror` sets src to placeholder (existing test extended)

### Integration Tests

Add to `runIntegrationTests()`:

- Versioned envelope: `{ version: "1.0", mugs: [...] }` → `allMugs` populated correctly
- Legacy array fallback: bare array JSON → wrapped internally, grid renders
- Filter + render: set `filterState`, call `applyFilters()`, assert `grid.children.length`

### E2E Tests

Manual smoke test checklist (no automated E2E framework in v1):

1. Open `index.html` locally (file:// or `npx serve .`)
2. Verify all cards render with images or placeholder
3. Type in search box — grid updates after 200 ms debounce
4. Select series from dropdown — grid filters immediately
5. Enter year range — grid filters on input
6. Click Reset — all cards reappear
7. Click card → modal opens; ESC closes; backdrop click closes
8. Tab through cards; Enter/Space opens modal
9. Resize to 375 px width — single-column layout

---

## 10. Migration Strategy

1. **Update `mugs.json`**: Change root from bare array to `{ version, mugs }`. Rename `price` → `price_usd`. Add `series`, `year`, `region`, `tags` to all 6 existing entries. Add 44 new entries.
2. **Update `app.js`**: Apply all changes in one PR against `main`. The `loadMugs` legacy-array guard ensures the page stays functional between JSON and JS deploys.
3. **Update `index.html`**: Add `#filter-bar` and `#results-count`.
4. **Update `style.css`**: Add filter bar and results count styles.
5. **Add `images/placeholder.svg`**.
6. **Deploy**: `git push` → GitHub Pages auto-deploys.

Deploy order does not matter due to the legacy guard in `loadMugs`.

---

## 11. Rollback Plan

```
git revert <commit-sha>   # or git checkout main -- index.html app.js style.css mugs.json
git push
```

GitHub Pages redeploys within ~60 seconds. No database or server state to restore. Previous `mugs.json` (bare array) is handled by the legacy guard, so partial rollback of JS-only is also safe.

---

## 12. Performance Considerations

- **Debounce 200 ms** on search input prevents re-renders on every keystroke.
- **`allMugs` cached** in memory after first fetch; no repeat network calls for filter changes.
- **`Array.filter`** on 50–500 entries completes in <1 ms; no worker needed.
- **`loading="lazy"`** on all `<img>` elements (cards and modal); only visible images fetched.
- **SVG placeholder** is ~400 bytes inline; eliminates 404 waterfall on missing images.
- **`mugs.json` size**: 50 entries × ~350 bytes ≈ 17 KB uncompressed; Brotli compression on Netlify/GitHub Pages reduces to ~5 KB.
- **CSS Grid `auto-fill minmax(260px,1fr)`** — no layout JS needed; browser handles reflow.
- **No external JS dependencies** — zero parse/eval overhead beyond the single `app.js` file.

---

## Appendix: Existing Repository Structure

```
.claude-plan.json
.claude-resolution.json
.conflict-info.json
.git
.gitignore
app.js
app.test.js
docs/
  concepts/
    best-starbucks-mugs-website/
      HLD.md
      PRD.md
      README.md
    website-starbucks-mugs/
      HLD.md
      LLD.md
      PRD.md
      README.md
      ROAM.md
      epic.yaml
      issues_created.yaml
      slices.yaml
      tasks.yaml
      timeline.md
      timeline.yaml
images/
  .gitkeep
index.html
mugs.json
style.css
```