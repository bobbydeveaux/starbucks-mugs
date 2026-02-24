Now I have all the context needed to write the LLD. Let me generate it.

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