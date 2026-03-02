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