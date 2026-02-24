# High-Level Design: Ferrari vs Lambo Website

**Created:** 2026-02-24T19:37:44Z
**Status:** Draft

## 1. Architecture Overview

Single-Page Application (SPA) with zero backend. All car data is bundled as static JSON files and loaded at runtime. The browser handles all filtering, search, and comparison logic client-side. Deployed as a static bundle to a CDN.

```
Browser SPA (React + Vite)
  ├── Static JSON (ferrari.json, lamborghini.json)
  ├── Client-side state (useCarCatalog, useComparison hooks)
  └── CDN (Vercel/Netlify edge) ← single deploy target
```

No server, no API, no database. All data is pre-authored and shipped with the build.

---

## 2. System Components

| Component | Responsibility |
|---|---|
| `CatalogPage` | Renders brand catalog with decade filter + search bar |
| `CarCard` | Top-trump-style stat card (image, HP, torque, 0–60, top speed, engine) |
| `ComparisonView` | Side-by-side stat panel; highlights winner per metric in brand colour |
| `EraFilter` | Decade selector; filters both catalogs simultaneously |
| `SearchBar` | Real-time model-name filter (client-side, debounced ≤300 ms) |
| `useCarCatalog` | Hook — loads JSON, exposes filtered/sorted car arrays |
| `useComparison` | Hook — holds selected Ferrari + Lambo, computes per-stat winners |
| `eraMatchSuggestion` | Pure function — pairs a car with its closest-year opponent |
| `ferrari.json` / `lamborghini.json` | Static data source; one record per production model |

---

## 3. Data Model

**CarModel** (shared schema for both brands):

```ts
interface CarModel {
  id: string;           // "ferrari-testarossa-1984"
  brand: "ferrari" | "lamborghini";
  model: string;        // "Testarossa"
  year: number;         // 1984
  decade: number;       // 1980
  image: string;        // "/images/ferrari/testarossa.jpg"
  specs: {
    hp: number;
    torqueLbFt: number;
    zeroToSixtyMs: number;   // seconds, e.g. 5.2
    topSpeedMph: number;
    engineConfig: string;    // "Flat-12, 4.9L"
  };
  eraRivals: string[];  // ids of close contemporaries from opposite brand
}
```

**Data files:**
- `public/data/ferrari.json` — `CarCatalogEnvelope` (fetched via `fetch('/data/ferrari.json')`)
- `public/data/lamborghini.json` — `CarCatalogEnvelope` (fetched via `fetch('/data/lamborghini.json')`)

Both follow the same envelope pattern as the existing `useDrinks` hook data.
The `image` field in the JSON corresponds to `imageUrl` in the `CarModel` TypeScript interface.

---

## 4. API Contracts

No HTTP API. Data access is via static JSON imports resolved by Vite at build time.

**Hook interface (internal contract):**

```ts
// useCarCatalog — takes no parameters; loads both catalogs on mount
useCarCatalog()
  => {
    filteredFerraris: CarModel[],  // sorted by year ascending
    filteredLambos: CarModel[],    // sorted by year ascending
    loading: boolean,
    error: string | null,
    era: number | undefined,
    setEra: (decade: number | undefined) => void,
    searchValue: string,           // raw (un-debounced) value for controlled input
    setSearch: (query: string) => void  // debounced 300 ms internally
  }

interface CatalogFilters {
  decade?: number;      // e.g. 1980 filters to 1980–1989
  search?: string;      // case-insensitive model name match
}

// useComparison
useComparison()
  => {
    selected: { ferrari?: CarModel, lamborghini?: CarModel },
    select: (car: CarModel) => void,
    stats: ComparisonStat[],   // per-metric winner annotation
    suggestedRival: CarModel | null
  }

interface ComparisonStat {
  label: string;
  ferrariValue: number;
  lamboValue: number;
  winner: "ferrari" | "lamborghini" | "tie";
}
```

---

## 5. Technology Stack

### Backend
None. Zero server-side runtime.

### Frontend
- **React 18** — component framework
- **TypeScript** — type safety across data model and hooks
- **Vite** — bundler; handles JSON imports, fast HMR
- **Tailwind CSS** — utility styling; extended with `ferrari-red: #DC143C` and `lambo-yellow: #FFC72C` brand tokens
- **React Router v6** — `/` (home), `/ferrari`, `/lamborghini`, `/compare` routes

### Infrastructure
- **Vercel or Netlify** — static hosting with edge CDN; zero-config deploy from `main`
- **GitHub Actions** — CI: lint → test → build on PR; deploy on merge to `main`

### Data Storage
- Static JSON files in `public/data/` — versioned in git, no external DB, served via fetch('/data/…')
- Car images in `public/images/{brand}/` — self-hosted, served from CDN

---

## 6. Integration Points

- **Image assets** — self-hosted under `public/`; no external image CDN dependency
- **CI/CD** — GitHub Actions triggers Vercel/Netlify deploy hook on `main` merge
- No third-party APIs, no analytics SDK, no external data feeds

---

## 7. Security Architecture

- No user-submitted data; no server-side attack surface
- **CSP headers** set in `vercel.json` / `netlify.toml`: `default-src 'self'`, no inline scripts
- All assets self-hosted — no third-party script loading
- No secrets, tokens, or environment variables required
- HTTPS enforced by default via Vercel/Netlify

---

## 8. Deployment Architecture

```
git push → GitHub Actions CI
  ├── vitest (unit tests)
  ├── tsc --noEmit (type check)
  └── vite build → /dist

/dist → Vercel/Netlify CDN
  ├── index.html (SPA shell)
  ├── assets/ (hashed JS/CSS chunks)
  └── images/ (car photos)
```

Single environment: production. Preview deploys auto-generated per PR by Vercel/Netlify.

---

## 9. Scalability Strategy

Fully static — scales to any traffic load via CDN edge replication with no infrastructure changes. Vite code-splits per route (`/ferrari`, `/lamborghini`, `/compare`) so initial bundle only loads the home shell. JSON data files are small (<500 KB total for both catalogs) and cached by the CDN.

---

## 10. Monitoring & Observability

- **Vercel/Netlify Analytics** — page views, core web vitals (no additional SDK needed)
- **Lighthouse CI** — run in GitHub Actions on each PR; gate on score ≥ 85 mobile
- **Browser console** — zero errors policy enforced by E2E smoke test in CI
- No server logs, APM, or distributed tracing required for a static site

---

## 11. Architectural Decisions (ADRs)

**ADR-1: Zero backend**
All data is static JSON. Eliminates ops overhead, guarantees 99.9% uptime, and matches CDN deployment model. Accepted trade-off: data updates require a redeploy.

**ADR-2: Client-side filtering**
With ≤200 car records total, all filtering and search run in-memory in the browser. No API round-trips needed; 300 ms search SLA is trivially met.

**ADR-3: Reuse Costa vs Starbucks scaffold**
React 18 + Vite + Tailwind + Vitest are already configured. Extending brand tokens and mirroring the `useDrinks` hook pattern minimises setup and ensures CI compatibility.

**ADR-4: eraRivals pre-computed in JSON**
Era-matched suggestions are authored into the data file rather than computed at runtime. This avoids a matching algorithm edge case and lets curators control which rivalries are surfaced.

---

## Appendix: PRD Reference

*(See PRD: Ferrari vs Lambo Website, created 2026-02-24)*