# ROAM Analysis: what-s-the-temp-website

**Feature Count:** 7
**Created:** 2026-03-02T15:32:24Z

## Risks

1. **Scraper Fragility on climate-data.org** (High): The scraper relies on cheerio parsing of climate-data.org HTML structure. Any site redesign, anti-scraping measures, or rate limiting will break data collection silently or cause CI failures. With 150+ country pages to fetch, the scraper is also slow and vulnerable to transient HTTP errors mid-run.

2. **Incomplete or Inaccurate Temperature Data** (High): Scraped country-level averages may be missing for smaller or less-documented nations (e.g. Pacific island states, territories), leaving gaps in the 150+ country target. Scraped values may also reflect a single weather station rather than a true national average, reducing data quality.

3. **Data Staleness with No Refresh Mechanism** (Medium): `temperatures.json` is committed to the repo as a static asset. Without a scheduled CI job to re-scrape, the data will age indefinitely. If the source site updates historical averages or the scraper URL slugs change, there is no automated signal that the data is stale.

4. **Flag Emoji Rendering Inconsistency** (Medium): `CountryCard` derives flag emoji from ISO country codes (regional indicator symbols). Rendering varies across OS/browser combinations—Windows renders flags as two-letter codes rather than emoji flags. This affects a significant portion of users and degrades visual quality.

5. **Lighthouse ≥90 Target at Risk from JSON Payload** (Medium): `temperatures.json` at ~80KB uncompressed adds to Time to Interactive if not served with correct compression and cache headers. Combined with React 18 + Tailwind CSS bundle weight, hitting Lighthouse ≥90 consistently requires careful configuration that is easy to miss on initial deployment setup.

6. **TypeScript/Node Scraper Tooling Friction** (Low): The scraper uses `npx ts-node scripts/scrape.ts` which requires ts-node as a dev dependency. ts-node version conflicts with the project's tsconfig (especially `moduleResolution` settings for Vite) are a known source of friction and may require a separate tsconfig for the scripts directory.

7. **No Automated Data Validation** (Low): After scraping, there is no schema validation step to assert that all 150+ countries have all 12 months populated with plausible numeric values. A silent scraper bug (e.g. parsing a string as NaN) would produce a corrupt JSON file that only surfaces as a UI bug at runtime.

---

## Obstacles

- **Source site scraping access**: climate-data.org may throttle or block automated requests during the initial bulk scrape of 150+ country pages. There is no fallback data source defined in the LLD if the primary scraper target is unavailable, making the first successful data collection run a prerequisite blocker for all downstream features.

- **Country slug enumeration**: The scraper depends on a hardcoded list of ~150 country slugs for climate-data.org. This list must be manually curated before the scraper can run; it is not derived automatically. Small nations, territories, and disputed regions may require research to identify correct slugs or may not exist on the source site at all.

- **Deployment platform not yet selected**: The LLD lists Netlify, Vercel, and GitHub Pages as options but does not commit to one. Cache-Control headers (`max-age=86400`) and CSP configuration differ between platforms. This decision must be made before deployment configuration can be written, blocking the performance and security NFRs from being validated.

- **No test runner configured in scaffold**: The Vite `react-ts` template does not include Vitest or Jest by default. The LLD specifies unit and integration tests across 7 test files but does not document the test framework setup steps, meaning test infrastructure must be configured before any test-writing features can begin.

---

## Assumptions

1. **climate-data.org provides reliable, parseable data for 150+ countries**: The scraper design assumes consistent HTML structure across all country pages and that 150+ countries are available with all 12 months populated. *Validation approach*: Run the scraper against a sample of 10–20 diverse countries (including small island states) before committing to the architecture; check for missing months and structural anomalies.

2. **~80KB JSON payload meets the 200KB budget and does not impair Lighthouse ≥90**: The HLD estimates 50–80KB uncompressed. With gzip compression on the CDN, the actual transfer size will be ~15–25KB, well within budget. *Validation approach*: Generate the real `temperatures.json` from the scraper and measure actual file size before assuming it fits the budget.

3. **Country-level temperature averages are a useful and accurate enough proxy for user travel decisions**: The product assumes a single average per country per month is sufficient—ignoring geographic variation within large countries (e.g. Russia, USA, Brazil, Australia). *Validation approach*: Accept this as a known product limitation documented in the PRD's Non-Goals; consider surfacing a disclaimer in the UI.

4. **`useMemo` filtering of 150+ country records will consistently render within 300ms**: The filter logic is O(n) over a small, in-memory array. For 150–200 entries this is trivially fast, but the assumption must hold on low-end mobile devices. *Validation approach*: Benchmark filter execution in Chrome DevTools on a throttled CPU (4x slowdown) during development.

5. **Flag emoji rendering from ISO codes is acceptable UX across target browsers**: The plan derives flag emoji from country codes without a fallback. This assumes the majority of target users are on macOS, iOS, or Android where flag emoji render correctly. *Validation approach*: Test on Windows Chrome/Edge early; decide whether to add a text-based fallback or accept the limitation.

---

## Mitigations

### Risk 1: Scraper Fragility on climate-data.org
- Add a secondary data source fallback (Wikipedia climate tables) to the scraper with a `--source` flag, so if climate-data.org structure changes, the scraper can switch sources without code restructuring.
- Implement per-country error catching in the scraper loop: log failed countries to stderr and continue rather than aborting the entire run. Output a `scrape-report.json` alongside `temperatures.json` listing success/failure counts.
- Add a `User-Agent` header and a configurable delay between requests (default 500ms) to reduce the risk of rate limiting during the bulk scrape.
- Commit `temperatures.json` to the repository so the live site is never blocked by a scraper failure; CI scraper failures are non-blocking for deployment.

### Risk 2: Incomplete or Inaccurate Temperature Data
- Manually audit the scraped JSON for countries with missing months (any `null` or `undefined` values) using a post-scrape validation script before committing.
- Supplement scraper-sourced data with manually entered values for known gap countries (small Pacific/Caribbean islands) using a `manual-overrides.json` that is merged at scrape time.
- Filter out countries with incomplete data (missing any of the 12 months) from the dataset rather than displaying them with gaps, with a count logged to the build output.

### Risk 3: Data Staleness with No Refresh Mechanism
- Add a GitHub Actions scheduled workflow (`on: schedule: cron`) to re-run the scraper once per quarter and open an automated PR with any changes to `temperatures.json` for human review before merge.
- Embed a `scrapedAt` timestamp in `temperatures.json` and display it as a footer note in the UI (e.g. "Data last updated: Q4 2025") so users are aware of data vintage.

### Risk 4: Flag Emoji Rendering Inconsistency
- Add a build-time step that maps ISO codes to Unicode flag emoji characters explicitly, rather than relying on runtime regional indicator symbol concatenation.
- Implement a Windows detection check (or simply a CSS `font-family` fallback using Twemoji or Noto Color Emoji) as a progressive enhancement. If budget is tight, document the known Windows limitation and ship without the fix—the feature still works textually.

### Risk 5: Lighthouse ≥90 Target at Risk
- Configure `netlify.toml` (or `vercel.json`) with explicit `Cache-Control: public, max-age=86400, stale-while-revalidate=86400` for `temperatures.json` and immutable caching for hashed JS/CSS assets.
- Run Lighthouse CI locally (`lhci autorun`) against the Vite production build (`npm run build && npm run preview`) before the first deployment to catch regressions early.
- Set Tailwind's `content` paths correctly to enable purging of unused CSS classes, keeping the CSS bundle minimal.

### Risk 6: TypeScript/Node Scraper Tooling Friction
- Add a dedicated `tsconfig.node.json` (already listed in the file structure) with `module: CommonJS` and `moduleResolution: node` for the scraper, separate from the Vite app tsconfig. Reference it explicitly in the `ts-node` command: `npx ts-node --project tsconfig.node.json scripts/scrape.ts`.
- Alternatively, migrate the scraper to plain JavaScript (`scripts/scrape.js`) with JSDoc type comments to eliminate ts-node entirely, since the scraper is a one-off utility rather than production code.

### Risk 7: No Automated Data Validation
- Write a `scripts/validate.ts` script that loads `temperatures.json`, checks every country has all 12 `MonthKey` values as finite numbers in the range −60°C to 60°C, and exits non-zero on failure. Run it as a CI step after the scraper and before the build.
- Add a unit test fixture that imports a sample of the committed `temperatures.json` and asserts structural integrity, catching file corruption introduced by manual edits.

---

## Appendix: Plan Documents

### PRD
# Product Requirements Document: What's the Temp Website

I want a website similar to https://www.whereshotnow.com but the idea is that it's a react website showing countries that you can visit on a given month in the temp range you select. i.e. if you want to go somewhere in November thats 27C +/- 3C then you should be able to see those countries. It can just scrape average temperatures and store them in static JSON - but we should include as many countries as possible.

**Created:** 2026-03-02T15:27:42Z
**Status:** Draft

## 1. Overview

**Concept:** What's the Temp Website

I want a website similar to https://www.whereshotnow.com but the idea is that it's a react website showing countries that you can visit on a given month in the temp range you select. i.e. if you want to go somewhere in November thats 27C +/- 3C then you should be able to see those countries. It can just scrape average temperatures and store them in static JSON - but we should include as many countries as possible.

**Description:** What's the Temp Website

I want a website similar to https://www.whereshotnow.com but the idea is that it's a react website showing countries that you can visit on a given month in the temp range you select. i.e. if you want to go somewhere in November thats 27C +/- 3C then you should be able to see those countries. It can just scrape average temperatures and store them in static JSON - but we should include as many countries as possible.

---

## 2. Goals

- Cover 150+ countries with monthly average temperature data stored as static JSON
- Allow users to filter destinations by target temperature and tolerance (e.g. 27°C ±3°C) for any selected month
- Render filtered results as a responsive, browsable country list with temperature context
- Provide a fast, no-backend experience with sub-second filter response times

---

## 3. Non-Goals

- No real-time or forecast weather data — static historical averages only
- No user accounts, saved searches, or personalisation
- No flight/hotel booking integration or pricing data
- No city-level granularity — country-level averages only

---

## 4. User Stories

- As a traveller, I want to select a month and temperature range so I can discover countries with my preferred climate
- As a user, I want to adjust the temperature tolerance (±°C) so I can broaden or narrow my results
- As a user, I want to switch between Celsius and Fahrenheit so I can use my preferred unit
- As a user, I want to see each result's average temperature for my chosen month so I can compare destinations
- As a user, I want results to update instantly as I change my filters so I don't wait for page reloads

---

## 5. Acceptance Criteria

**Filter by month and temperature:**
- Given a selected month and target temperature with tolerance, when the user sets the filter, then only countries whose average temperature falls within the range are shown

**Celsius/Fahrenheit toggle:**
- Given the default Celsius display, when the user toggles to Fahrenheit, then all temperatures and inputs convert correctly

**Instant results:**
- Given any filter change, when the value updates, then the results list re-renders within 300ms

---

## 6. Functional Requirements

- **FR-001** Month selector (January–December) controls the active temperature dataset
- **FR-002** Temperature target input (numeric) with ± tolerance slider/input (default ±3°C)
- **FR-003** Results list displays matching countries with their average temperature for the selected month
- **FR-004** Celsius/Fahrenheit toggle converts all values throughout the UI
- **FR-005** Static JSON dataset contains monthly average temperatures for 150+ countries
- **FR-006** No-match state displayed when zero countries meet the filter criteria

---

## 7. Non-Functional Requirements

### Performance
Page load under 2s on a standard connection; filter results render within 300ms; static JSON under 200KB

### Security
No backend, no user data collected; no external API calls at runtime; CSP headers on static host

### Scalability
Fully static deployment (Netlify/Vercel/GitHub Pages); no server scaling concerns

### Reliability
100% uptime achievable via CDN-hosted static site; no runtime dependencies on external services

---

## 8. Dependencies

- **React** — UI framework
- **Static JSON** — pre-scraped monthly average temperature data (build-time asset)
- **Temperature data source** — e.g. Wikipedia climate tables or climate-data.org (scrape at build time)
- **Static host** — Netlify, Vercel, or GitHub Pages

---

## 9. Out of Scope

- Real-time weather APIs or live data fetching
- City, region, or sub-country temperature data
- User authentication or saved preferences
- Mobile native apps
- Booking or travel planning integrations
- Precipitation, humidity, or UV index data

---

## 10. Success Metrics

- Dataset covers ≥150 countries with all 12 months populated
- Filter interaction latency ≤300ms (measured in Chrome DevTools)
- Zero runtime external API calls (verified via Network tab)
- Lighthouse performance score ≥90 on desktop

---

## Appendix: Clarification Q&A

### Clarification Questions & Answers

### HLD
# High-Level Design: What's the Temp Website

**Created:** 2026-03-02T15:28:41Z
**Status:** Draft

## 1. Architecture Overview

Single-page application (SPA) with a fully static architecture. All logic runs client-side in the browser. No backend, no API server, no database. Temperature data is bundled as a static JSON asset at build time. The entire site is deployed to a CDN as pre-built static files.

```
[Build Time]                        [Runtime]
  Scraper Script                      Browser
  (Node.js)          →  JSON Asset →  React SPA
  climate-data.org                    (filter, display)
       ↓
  temperatures.json
  (bundled into dist/)
```

---

## 2. System Components

| Component | Description |
|---|---|
| **Data Scraper** | One-off Node.js script that fetches average monthly temperatures from climate-data.org or Wikipedia, outputs `temperatures.json` |
| **React App** | SPA with filter controls and results list; all filtering done in-memory via `useMemo` |
| **Filter Engine** | Pure JS function: filters country array by `month`, `targetTemp`, `tolerance`; unit conversion handled here |
| **Static Assets** | Built output (HTML/JS/CSS + JSON) served from CDN |

---

## 3. Data Model

**`temperatures.json`** — single file, array of country objects:

```json
[
  {
    "country": "Thailand",
    "code": "TH",
    "avgTemps": {
      "jan": 26, "feb": 27, "mar": 29, "apr": 30,
      "may": 29, "jun": 28, "jul": 28, "aug": 28,
      "sep": 27, "oct": 27, "nov": 26, "dec": 25
    }
  }
]
```

- All temperatures stored in Celsius (canonical unit)
- Fahrenheit conversion applied at display time only
- Target: 150+ country entries, all 12 months populated
- Estimated file size: ~50–80KB uncompressed, well under 200KB limit

---

## 4. API Contracts

No runtime API. The single data contract is the static JSON schema above.

**Filter function signature (internal):**
```ts
filterCountries(
  countries: Country[],
  month: MonthKey,          // "jan" | "feb" | ... | "dec"
  targetTemp: number,       // in Celsius
  tolerance: number,        // ±°C, default 3
): Country[]
```

**Unit conversion:**
```ts
toFahrenheit(celsius: number): number  // (c * 9/5) + 32
toCelsius(fahrenheit: number): number  // (f - 32) * 5/9
```

---

## 5. Technology Stack

### Backend
None — no backend exists at runtime.

**Build-time scraper only:** Node.js with `cheerio` (HTML parsing) and `node-fetch` for HTTP requests. Run once manually or in CI to regenerate `temperatures.json`.

### Frontend
- **React 18** — UI framework (Vite scaffold)
- **TypeScript** — type safety for data model and filter logic
- **CSS Modules or Tailwind CSS** — styling (no heavy UI library needed)
- **No state management library** — `useState` + `useMemo` sufficient for this use case

### Infrastructure
- **Vite** — build tool (fast builds, good tree-shaking)
- **Netlify / Vercel / GitHub Pages** — static hosting with CDN
- **GitHub Actions** — CI for build and deploy on merge to main

### Data Storage
- **Single static JSON file** — bundled into the Vite build output as a public asset
- Loaded once at app mount via `import` or `fetch('/temperatures.json')`

---

## 6. Integration Points

| Integration | When | Purpose |
|---|---|---|
| climate-data.org / Wikipedia | Build time only | Source for monthly average temperatures |
| CDN host (Netlify/Vercel) | Deploy time | Serves static files globally |

Zero runtime external integrations. No third-party scripts, analytics, or APIs loaded in the browser.

---

## 7. Security Architecture

- No user data collected or transmitted
- No cookies, no local storage (no state to persist)
- CSP header configured on host: `default-src 'self'` blocks all external resource loading
- Scraper runs in isolated CI job; no secrets needed (public data sources)
- No authentication surface area exists

---

## 8. Deployment Architecture

```
GitHub (main branch)
    ↓ push / merge
GitHub Actions CI
    ↓ npm run build (Vite)
dist/ (static files)
    ↓ deploy
Netlify / Vercel CDN
    ↓ global edge nodes
End Users (browser)
```

- Build output: `index.html` + hashed JS/CSS bundles + `temperatures.json`
- No containers, no servers, no infrastructure to manage
- Preview deployments per PR via Netlify/Vercel automatic previews

---

## 9. Scalability Strategy

Fully static CDN deployment scales to any traffic volume with zero configuration. No horizontal or vertical scaling concerns. CDN edge caching provides sub-50ms response times globally for all assets. The only "scale" consideration is JSON file size, which is bounded by the dataset (150 countries × 12 months = negligible).

---

## 10. Monitoring & Observability

- **Lighthouse CI** — run on every PR to enforce performance score ≥90
- **Netlify/Vercel Analytics** — basic page view and performance metrics (no PII)
- **Build status badge** — GitHub Actions job status on repo README
- No error tracking service needed (no server-side errors possible; JS errors are non-critical UI edge cases)

---

## 11. Architectural Decisions (ADRs)

**ADR-1: Static JSON over runtime API**
All temperature data is pre-scraped and bundled at build time. Rationale: eliminates backend infrastructure, ensures 100% uptime, meets sub-300ms filter performance, and aligns with PRD requirement for zero runtime external calls.

**ADR-2: Store temperatures in Celsius as canonical unit**
Fahrenheit conversion applied at display time only. Rationale: avoids floating-point drift from round-tripping conversions; simplifies filtering logic (single comparison unit).

**ADR-3: Vite over Create React App**
Vite chosen for fast HMR, modern ES module output, and smaller bundle sizes. CRA is deprecated. No meaningful trade-off for this project size.

**ADR-4: No UI component library**
Tailwind CSS or plain CSS Modules only. Rationale: a component library (MUI, Chakra) would add significant bundle weight for a UI with two controls and a list. Keeping dependencies minimal supports Lighthouse ≥90 target.

**ADR-5: Single JSON file vs. per-month split**
Single `temperatures.json` loaded once at startup. At ~80KB, it's well under the 200KB budget and avoids 12 sequential fetches that would complicate loading state management.

---

## Appendix: PRD Reference

*(See full PRD above)*

### LLD
# Low-Level Design: What's the Temp Website

**Created:** 2026-03-02T15:29:36Z
**Status:** Draft

## 1. Implementation Overview

New sub-directory `what-s-the-temp/` following the monorepo pattern established by `costa-vs-starbucks/` and `markdowntopdf/`. A standalone Vite + React 18 + TypeScript SPA with no backend. A one-off Node.js scraper generates `public/temperatures.json` at build time; the app loads it once on mount and filters in-memory via `useMemo`. Deployed as static files to Netlify/Vercel CDN.

---

## 2. File Structure

```
what-s-the-temp/
  index.html
  package.json
  tsconfig.json
  tsconfig.node.json
  vite.config.ts
  tailwind.config.ts
  scripts/
    scrape.ts              # Node.js scraper → public/temperatures.json
  public/
    temperatures.json      # pre-built data, committed to repo
  src/
    main.tsx               # Vite entry point
    App.tsx                # root: data fetch, filter state, layout
    App.test.tsx
    types.ts               # Country, MonthKey, FilterState, Unit
    utils/
      temperature.ts       # toFahrenheit, toCelsius, formatTemp
      temperature.test.ts
      filterCountries.ts   # core filter function
      filterCountries.test.ts
    components/
      FilterControls.tsx   # month, targetTemp, tolerance, unit toggle
      FilterControls.test.tsx
      CountryList.tsx      # sorted results list
      CountryList.test.tsx
      CountryCard.tsx      # single result row
      CountryCard.test.tsx
    hooks/
      useTemperatures.ts   # fetch + parse temperatures.json
      useTemperatures.test.ts
```

---

## 3. Detailed Component Designs

### `src/types.ts`
```ts
export type MonthKey = 'jan'|'feb'|'mar'|'apr'|'may'|'jun'|
                       'jul'|'aug'|'sep'|'oct'|'nov'|'dec';
export type Unit = 'C' | 'F';

export interface Country {
  country: string;
  code: string;
  avgTemps: Record<MonthKey, number>; // always Celsius
}

export interface FilterState {
  month: MonthKey;
  targetTemp: number;  // in selected unit
  tolerance: number;   // ± degrees, default 3
  unit: Unit;
}
```

### `src/App.tsx`
- Calls `useTemperatures()` for data, `loading`, `error`
- Holds `FilterState` in `useState` (defaults: month=current, targetTemp=25, tolerance=3, unit='C')
- `useMemo(() => filterCountries(countries, month, targetCelsius, tolerance), [countries, filter])`
- Converts `targetTemp` to Celsius before passing to `filterCountries`
- Shows loading skeleton while fetching; inline error on failure

### `src/components/FilterControls.tsx`
- Controlled; props: `filter: FilterState`, `onChange: (f: FilterState) => void`
- Month: `<select>` with 12 labeled options
- Target temp: `<input type="number" step="1">`
- Tolerance: `<input type="number" min="1" max="15">`
- Unit toggle: two `<button>` elements (C / F); on switch, converts `targetTemp` then calls `onChange`

### `src/components/CountryCard.tsx`
- Props: `country: Country`, `month: MonthKey`, `unit: Unit`
- Renders country name, flag emoji (derived from `code`), and `formatTemp(avgTemps[month], unit)`

### `src/components/CountryList.tsx`
- Props: `countries: Country[]`, `month: MonthKey`, `unit: Unit`
- Sorts A-Z by `country.country`; renders `<CountryCard>` per entry
- Empty state: "No countries match your criteria."

### `scripts/scrape.ts`
- `node-fetch` + `cheerio` to scrape climate-data.org country pages
- Iterates a hardcoded list of ~150 country slugs
- Extracts 12 monthly average temps, normalises to Celsius
- Writes `public/temperatures.json`; run via `npx ts-node scripts/scrape.ts`

---

## 4. Database Schema Changes

None. No database. All data is a static JSON file committed to the repository.

---

## 5. API Implementation Details

None. No runtime API. The browser fetches `GET /temperatures.json` from CDN — handled entirely by `useTemperatures`.

---

## 6. Function Signatures

```ts
// src/utils/temperature.ts
export function toFahrenheit(celsius: number): number;       // (c * 9/5) + 32
export function toCelsius(fahrenheit: number): number;       // (f - 32) * 5/9
export function formatTemp(celsius: number, unit: Unit): string; // "26°C" | "79°F"

// src/utils/filterCountries.ts
export function filterCountries(
  countries: Country[],
  month: MonthKey,
  targetTempCelsius: number,  // caller converts to C before passing
  toleranceCelsius: number,
): Country[];  // abs(avgTemps[month] - targetTempCelsius) <= toleranceCelsius

// src/hooks/useTemperatures.ts
export function useTemperatures(): {
  countries: Country[];
  loading: boolean;
  error: string | null;
};

// Component prop interfaces
interface FilterControlsProps {
  filter: FilterState;
  onChange: (filter: FilterState) => void;
}
interface CountryListProps {
  countries: Country[];
  month: MonthKey;
  unit: Unit;
}
interface CountryCardProps {
  country: Country;
  month: MonthKey;
  unit: Unit;
}
```

---

## 7. State Management

`useState` + `useMemo` in `App.tsx` only. No context, no external store needed.

```
App.tsx
  ├── useTemperatures()           → { countries[], loading, error }
  ├── useState<FilterState>()     → filter, setFilter
  └── useMemo(filterCountries)    → results[]
```

Unit conversion is the caller's responsibility: `App.tsx` converts `filter.targetTemp` to Celsius via `toCelsius` before passing to `filterCountries`, keeping the filter function unit-agnostic.

---

## 8. Error Handling Strategy

| Scenario | Handling |
|---|---|
| `temperatures.json` fetch fails | `useTemperatures` sets `error`; App renders inline error message |
| Non-numeric temp input | `type="number"` prevents; `filterCountries` guards with `isNaN` check → returns `[]` |
| Empty filter results | `CountryList` renders "No countries match your criteria." |
| Scraper HTTP error | Script exits non-zero; CI fails; committed JSON unchanged |

No toast libraries. Errors displayed inline near the relevant UI element.

---

## 9. Test Plan

### Unit Tests

**`temperature.test.ts`**
- `toFahrenheit(0)` → 32; `toFahrenheit(100)` → 212
- `toCelsius(32)` → 0; round-trip precision within 0.01°

**`filterCountries.test.ts`**
- Countries within tolerance are returned
- Countries outside tolerance are excluded
- `tolerance=0` → exact-match only
- Empty input array → empty result
- NaN targetTemp → empty result (guard check)

**`useTemperatures.test.ts`**
- Mock fetch success → `countries` populated, `loading=false`, `error=null`
- Mock fetch failure → `error` set, `loading=false`, `countries=[]`

**`FilterControls.test.tsx`**
- Renders 12 month options
- Unit toggle converts `targetTemp` and calls `onChange`
- Tolerance input change propagates correctly

**`CountryCard.test.tsx`**
- Renders Celsius when `unit='C'`
- Renders Fahrenheit when `unit='F'`

**`CountryList.test.tsx`**
- Renders correct number of cards
- Shows empty-state message when array is empty

### Integration Tests

**`App.test.tsx`**
- Mock fetch with fixture (5 countries); assert list renders after load
- Changing month select updates results
- Changing unit toggle converts all displayed temperatures

### E2E Tests

Not required for this project tier. Lighthouse CI (`lhci autorun`) serves as the primary automated quality gate, enforcing performance score ≥90 on each PR per the existing `.lighthouserc.json`.

---

## 10. Migration Strategy

Greenfield sub-directory; no changes to existing monorepo code. Steps:

1. `npm create vite@latest what-s-the-temp -- --template react-ts`
2. Install Tailwind CSS per Vite integration guide
3. Run scraper: `npx ts-node scripts/scrape.ts` → commits `public/temperatures.json`
4. Implement types, utils, hooks, components per this LLD
5. Configure Netlify/Vercel: root dir = `what-s-the-temp/`, build = `npm run build`, publish = `dist/`

---

## 11. Rollback Plan

Static deployment; rollback = redeploy prior commit. Netlify/Vercel retain full deployment history with one-click instant rollback via their dashboard. No database migrations to reverse. `temperatures.json` can be reverted with `git revert` if scraper output is bad.

---

## 12. Performance Considerations

- `temperatures.json` served with `Cache-Control: max-age=86400` via Netlify `_headers` or `netlify.toml`
- `useMemo` prevents re-running filter on unrelated re-renders
- No images, no web fonts (system stack only) — minimal render-blocking resources
- Vite minification + tree-shaking targets JS bundle <50KB gzipped
- Lighthouse ≥90 enforced via existing `.lighthouserc.json` in repo root on every PR

---

## Appendix: Existing Repository Structure

*(See repository file structure in the HLD reference above.)*