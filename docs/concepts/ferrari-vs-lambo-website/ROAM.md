# ROAM Analysis: ferrari-vs-lambo-website

**Feature Count:** 4
**Created:** 2026-02-24T19:42:07Z

## Risks

1. **Car Image Sourcing** (High): 80+ production models require individual Creative Commons or press-licensed photos. No image source is identified or pre-approved. Missing images will degrade the top-trump card experience significantly and could block the catalog feature from feeling complete at launch.

2. **Historical Spec Data Accuracy** (High): Hand-authoring 50+ Ferrari records (1947–present) and 30+ Lamborghini records with accurate HP, torque, 0–60, and top speed values is error-prone. Pre-1970s models have inconsistent or contested spec documentation across sources, and incorrect data will undermine user trust on a spec-focused site.

3. **Data File Path Inconsistency** (Medium): The HLD references `src/data/ferrari.json` (Vite static import), the LLD references `public/data/ferrari.json` (fetch-at-runtime), and the epic feature spec also references `public/data/`. This ambiguity will cause a broken `useCarCatalog` hook if developers implement against the wrong path.

4. **eraRivals Curation Complexity** (Medium): Pre-computing `eraRivals` ids across 80+ models requires every record to reference valid ids from the opposite brand's JSON. A single typo or missing id silently breaks the era-match suggestion for that car, and there is no runtime validation to catch it.

5. **Lighthouse Score ≥ 85 on Mobile** (Medium): Self-hosting 80+ car images without explicit lazy loading, WebP conversion, and `width`/`height` attributes risks failing the Lighthouse performance gate, particularly on the catalog page which renders all cards simultaneously.

6. **React Router v6 Integration with Existing Routes** (Low): The existing Costa vs Starbucks UI lives at `/`. Adding `/ferrari`, `/lamborghini`, and `/compare` routes requires wrapping both old and new routes under a single `<BrowserRouter>`. If the existing `App.tsx` already has a router or uses `HashRouter`, this integration will require non-trivial refactoring.

7. **Tailwind Config Extension Breaking Existing Styles** (Low): Appending `ferrari-red` and `lambo-yellow` tokens to `tailwind.config.ts` is low-risk, but if the existing config uses `content` paths that do not include the new component directories, the new utility classes will be purged from the production build.

---

## Obstacles

- **No car data source identified**: All 80+ `CarModel` records must be hand-authored or sourced from a structured public dataset (e.g., Wikimedia, manufacturer press archives). There is no existing data file, script, or pipeline to generate the JSON — this is the single largest time sink in `ferrari-vs-lambo-website-feat-data-foundation` and is a prerequisite for every other feature.

- **Car imagery is unresourced**: `public/images/{brand}/` is referenced in the schema but no image assets exist, no sourcing strategy is agreed, and no placeholder fallback is defined. Catalog and card components cannot be meaningfully demoed or visually tested until at least a representative sample of images is in place.

- **`eraRivals` ids cannot be authored until both JSON files are complete**: Because `eraRivals` in `ferrari.json` references ids from `lamborghini.json` and vice versa, neither file can be finalised in isolation. This creates a sequencing constraint within `ferrari-vs-lambo-website-feat-data-foundation` that is not reflected in the current feature dependency graph.

- **`react-router-dom@6` is not yet installed**: It is listed as the only new dependency but does not appear in any lock file or `package.json` in the current scaffold. It must be installed and the existing `App.tsx` must be audited before route wiring can begin.

---

## Assumptions

1. **The Costa vs Starbucks scaffold is accessible and in a working state** — the existing `useDrinks` pattern, Tailwind config, Vitest setup, and CI pipeline are all functional and the new car features can be added additively without needing to resolve pre-existing breakages. *Validation: run `npm install && npm test` on the scaffold before starting `feat-data-foundation`.*

2. **Sufficient Creative Commons or press-licensed car images exist for all target models** — at least one usable image per production model is findable on Wikimedia Commons or manufacturer press libraries without requiring paid licensing. *Validation: spot-check 10 obscure pre-1970 models (e.g., Ferrari 166 MM, Lamborghini 350 GT) on Wikimedia before committing to self-hosted images.*

3. **Client-side filtering over ≤200 records meets the 300 ms search SLA without debounce optimisation beyond `setTimeout`** — no Web Workers, virtual lists, or memoisation beyond basic `useMemo` are needed. *Validation: benchmark filtering on a mid-range mobile device (Moto G Power class) in Chrome DevTools with the full dataset loaded.*

4. **The `useDrinks` fetch pattern (`fetch('/data/ferrari.json')` from `public/data/`) is the correct implementation target** — the HLD's `src/data/` reference is a documentation error and the LLD's `public/data/` path is authoritative. *Validation: confirm with a code review of the existing `useDrinks` hook and agree on `public/data/` as canonical before `feat-data-foundation` is merged.*

5. **All production model spec values for both brands are publicly available in consistent units** — HP in bhp, torque in lb-ft, 0–60 in seconds, and top speed in mph can be sourced for every record. *Validation: attempt to fully populate 5 early-1960s Lamborghini records (the thinnest-documented era) before committing to the full data authoring effort.*

---

## Mitigations

### Risk 1 — Car Image Sourcing (High)
- **Immediate**: Define a `placeholder.jpg` per brand (Ferrari red gradient, Lambo yellow gradient) and set it as the `image` fallback in `CarCard` so the UI is never broken by a missing asset.
- **Short-term**: Source images exclusively from Wikimedia Commons (CC-BY-SA) and document the attribution URL in each `CarModel` record as an `imageCredit` field — this keeps licensing auditable.
- **Scope gate**: If images cannot be found for a model, omit the model from v1 rather than ship a card with a missing image. The PRD requires ≥50 Ferrari and ≥30 Lambo records, not exhaustive coverage.

### Risk 2 — Historical Spec Data Accuracy (High)
- **Authoritative sources only**: Use manufacturer press releases, the official Ferrari/Lamborghini model archives, and Automobile Catalog (automobile-catalog.com) as primary references. Log the source URL as a `specSource` field in each JSON record for auditability.
- **Flag uncertain values**: Add an optional `specUncertain: true` field on individual `specs` properties for pre-1970 models where values are contested. `CarCard` can render these with a `~` prefix.
- **Peer review the JSON**: Treat the data files as code — require a second developer review of the JSON before merging `feat-data-foundation`.

### Risk 3 — Data File Path Inconsistency (Medium)
- **Resolve before any code is written**: Add a single line to the `feat-data-foundation` acceptance criteria: _"Data files live at `public/data/ferrari.json` and `public/data/lamborghini.json`; `useCarCatalog` fetches via `fetch('/data/ferrari.json')`."_ Update the HLD to correct the `src/data/` reference.
- **Add a CI smoke test**: A Vitest test that asserts `fetch('/data/ferrari.json')` resolves and returns an array with at least 50 items will catch any path regression on every PR.

### Risk 4 — eraRivals Curation Complexity (Medium)
- **Two-pass authoring**: In pass one, author all records with `eraRivals: []`. In pass two, once both files are complete and all ids are stable, populate `eraRivals` using a small Node script that lists all ids from both files grouped by decade for manual assignment.
- **Runtime validation**: Add a `validateEraRivals()` utility (run in `vitest` only, stripped from prod) that cross-checks every `eraRivals` id exists in the opposite brand's JSON and fails the test suite if any id is invalid.

### Risk 5 — Lighthouse Score ≥ 85 on Mobile (Medium)
- **Images**: Serve all car photos as WebP (convert originals at build time via `vite-plugin-image-optimizer` or a pre-commit script). Set explicit `width` and `height` on every `<img>` in `CarCard` to eliminate layout shift.
- **Lazy loading**: Add `loading="lazy"` to all `CarCard` images — this alone typically recovers 10–15 Lighthouse points on image-heavy catalog pages.
- **Lighthouse CI gate**: Add `lighthouse-ci` to GitHub Actions with `assert.minScore.performance: 0.85` on the `/ferrari` route specifically, since it will be the heaviest page.

### Risk 6 — React Router v6 Integration (Low)
- **Audit first**: Before writing any route code, read the existing `App.tsx` in full to confirm whether a router is already present and which version.
- **Single `<BrowserRouter>` at root**: Wrap the entire app (including existing Costa vs Starbucks routes) in one `<BrowserRouter>` in `main.tsx`, not in `App.tsx`, to avoid nesting issues.
- **Route smoke test**: Add a Playwright E2E test that navigates to `/`, `/ferrari`, `/lamborghini`, and `/compare` and asserts a non-error status on each, run on every PR.

### Risk 7 — Tailwind Purge of New Utility Classes (Low)
- **Verify `content` paths**: After adding the new brand tokens, run `vite build` locally and inspect the output CSS to confirm `text-ferrari-red`, `bg-lambo-yellow`, etc. appear. If absent, extend the `content` array in `tailwind.config.ts` to include `./src/components/**/*.tsx` and `./src/pages/**/*.tsx`.
- **Add token usage to Storybook or a static test component** so the classes are always referenced and never purged by tree-shaking.

---

## Appendix: Plan Documents

### PRD
# Product Requirements Document: Ferrari vs Lambo Website

A website detailing ALLLL THE Ferrari car models in history, and a website listing ALLL the lambos. Going back in history and comparing cars of the yesteryear and showing which cars went head to head. With amazing design and model boxes to view cars top trump style

**Created:** 2026-02-24T19:36:37Z
**Status:** Draft

## 1. Overview

**Concept:** Ferrari vs Lambo Website

A website detailing ALLLL THE Ferrari car models in history, and a website listing ALLL the lambos. Going back in history and comparing cars of the yesteryear and showing which cars went head to head. With amazing design and model boxes to view cars top trump style

**Description:** Ferrari vs Lambo Website

A website detailing ALLLL THE Ferrari car models in history, and a website listing ALLL the lambos. Going back in history and comparing cars of the yesteryear and showing which cars went head to head. With amazing design and model boxes to view cars top trump style

---

## 2. Goals

1. Catalog every Ferrari and Lamborghini production model from both brands' full histories with accurate specs.
2. Enable head-to-head comparison of any Ferrari vs any Lambo via top-trump-style stat cards.
3. Surface era-matched rivals (e.g. 1970s Ferrari vs 1970s Lambo) so users can explore historical matchups.
4. Deliver a visually stunning, brand-authentic design that feels premium and enthusiast-grade.
5. Achieve fast page loads so the full model catalog is browsable without frustration.

---

## 3. Non-Goals

1. No user accounts, logins, or saved comparisons in this version.
2. No real-time pricing, market data, or auction integrations.
3. No video or 3D model rendering — static imagery only.
4. No coverage of non-production concept cars, one-offs, or racing-only variants.
5. No mobile-native app — responsive web only.

---

## 4. User Stories

1. As a car enthusiast, I want to browse all Ferrari models by decade so I can explore the brand's full history.
2. As a car enthusiast, I want to browse all Lamborghini models by decade so I can see the brand's evolution.
3. As a user, I want to select one Ferrari and one Lambo and see their stats side by side so I can decide which wins.
4. As a user, I want to filter cars by era so I can find period-correct rivals.
5. As a user, I want to view a car's full stat card (HP, torque, 0–60, top speed, year, engine) at a glance.
6. As a user, I want an era-matched suggestion so the site shows me the Lambo rival to a chosen Ferrari automatically.
7. As a user, I want to search by model name so I can jump directly to a specific car.

---

## 5. Acceptance Criteria

**Browse catalog:**
- Given I open the site, when I select Ferrari or Lamborghini, then I see all models listed chronologically with card thumbnails.

**Head-to-head comparison:**
- Given I have selected one car from each brand, when I click Compare, then a side-by-side stat panel shows all key metrics with visual win/lose highlights per stat.

**Era filter:**
- Given I apply a decade filter (e.g. 1980s), when the filter is active, then only cars from that decade appear in both brand catalogs.

**Search:**
- Given I type a model name in the search box, when results appear, then only matching cards are shown within 300 ms.

---

## 6. Functional Requirements

- **FR-001** Display all Ferrari production models (1947–present) as top-trump stat cards.
- **FR-002** Display all Lamborghini production models (1963–present) as top-trump stat cards.
- **FR-003** Each card shows: model name, year, image, HP, torque, 0–60 mph, top speed, engine config.
- **FR-004** Users can select one car per brand and trigger a head-to-head comparison view.
- **FR-005** Comparison view highlights the winning stat per metric in brand colour.
- **FR-006** Decade/era filter narrows both catalogs simultaneously.
- **FR-007** Text search filters cards by model name in real time.
- **FR-008** Era-matched rival suggestion automatically pairs a selected car with its closest contemporary opponent.

---

## 7. Non-Functional Requirements

### Performance
Initial page load under 3 s on a 4G connection; catalog filtering and search respond within 300 ms client-side.

### Security
Static data only — no user input stored server-side; no third-party auth tokens; CSP headers enforced.

### Scalability
All car data served as static JSON; no backend required; CDN-deployable with zero server scaling concerns.

### Reliability
Target 99.9% uptime via static hosting (Vercel/Netlify); no runtime database dependency.

---

## 8. Dependencies

- **React 18 + TypeScript + Vite** — existing project scaffold from Costa vs Starbucks codebase.
- **Tailwind CSS** — existing styling framework; extend with Ferrari red and Lambo yellow brand tokens.
- **Static JSON data files** — one per brand, matching existing `useDrinks`-style data envelope pattern.
- **Car imagery** — Creative Commons or licensed press photos per model (self-hosted).
- **Vitest + React Testing Library** — existing CI test setup.

---

## 9. Out of Scope

- User authentication or personalisation features.
- Real-time or dynamic data APIs (pricing, availability, news).
- Video, 360° views, or AR features.
- Race/track performance data beyond standard road specs.
- Any brand other than Ferrari and Lamborghini.

---

## 10. Success Metrics

1. Full model catalogs published: ≥ 50 Ferrari models and ≥ 30 Lamborghini models at launch.
2. Head-to-head comparison flow completable end-to-end with zero console errors.
3. Lighthouse performance score ≥ 85 on mobile.
4. All stat-card unit tests passing in CI on merge to main.
5. Era filter correctly narrows both catalogs to period-correct models in manual QA.

---

## Appendix: Clarification Q&A

### Clarification Questions & Answers

### HLD
# High-Level Design: starbucks-mugs

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
- `src/data/ferrari.json` — array of `CarModel[]`
- `src/data/lamborghini.json` — array of `CarModel[]`

Both follow the same envelope pattern as the existing `useDrinks` hook data.

---

## 4. API Contracts

No HTTP API. Data access is via static JSON imports resolved by Vite at build time.

**Hook interface (internal contract):**

```ts
// useCarCatalog
useCarCatalog(brand: "ferrari" | "lamborghini", filters: CatalogFilters)
  => { cars: CarModel[], loading: boolean }

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
- Static JSON files in `src/data/` — versioned in git, no external DB
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

### LLD
264 lines — well within the 400-line limit. The LLD has been written to `docs/concepts/ferrari-vs-lambo-website/LLD.md`.

Key decisions reflected in the document:

- **Mirrors `useDrinks` pattern exactly** — `useCarCatalog` uses `fetch('/data/ferrari.json')` from `public/data/` (not Vite static imports) to stay consistent with the existing scaffold
- **Additive changes only** — `src/types.ts` gets car types appended; existing `Drink`/`Brand` types are untouched; Costa vs Starbucks UI stays at route `/`
- **`tailwind.config.ts` extension** — `ferrari-red: #DC143C` and `lambo-yellow: #FFC72C` added alongside existing `starbucks`/`costa` tokens
- **`react-router-dom@6`** is the only new dependency
- **`eraMatchSuggestion`** is a pure utility function with its own test file, keeping comparison logic isolated from hook state
- **Test plan** covers unit, integration (React Testing Library + fake timers for debounce), and E2E (Playwright) proportional to the project size