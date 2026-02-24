# High-Level Design: starbucks-mugs

**Created:** 2026-02-24T16:11:56Z
**Status:** Draft

## 1. Architecture Overview

Static Single-Page Application (SPA). No backend, no server-side rendering, no runtime API dependencies. All drink and nutritional data is bundled as static JSON files served alongside the React app. Vite builds the app to a `/dist` folder deployed directly to a CDN-backed static host (Netlify or GitHub Pages).

```
┌─────────────────────────────────────────┐
│            Browser (React SPA)          │
│  ┌──────────┐  ┌────────────────────┐   │
│  │ Catalog  │  │ Comparison Panel   │   │
│  │  View    │  │ (side-by-side)     │   │
│  └──────────┘  └────────────────────┘   │
│       │                │                │
│  ┌────▼────────────────▼──────────────┐ │
│  │         React State (useState)     │ │
│  └────────────────────────────────────┘ │
│       │                                 │
│  ┌────▼────────────────────────────┐    │
│  │  Static JSON (drinks data)      │    │
│  └─────────────────────────────────┘    │
└─────────────────────────────────────────┘
         Hosted on Netlify / GitHub Pages
```

---

## 2. System Components

| Component | Responsibility |
|---|---|
| `DrinkCatalog` | Renders filterable, searchable grid of drink cards for both brands |
| `DrinkCard` | Displays drink name, category, brand colour, and a "Select to Compare" CTA |
| `ComparisonPanel` | Side-by-side view of two selected drinks with full nutritional breakdown |
| `NutritionBar` | Visual bar component scaled relative to the higher of the two values |
| `FilterBar` | Category filter buttons (Hot, Iced, Blended, Tea, Other) |
| `SearchBox` | Instant client-side search across both brands |
| `useDrinks` hook | Loads JSON data, exposes filtered/searched drink lists and selected comparison state |
| `drinks/starbucks.json` | Static nutritional data for 30+ Starbucks drinks |
| `drinks/costa.json` | Static nutritional data for 30+ Costa drinks |

---

## 3. Data Model

**Drink entity** (shared schema for both brands):

```json
{
  "id": "sbux-flat-white",
  "brand": "starbucks",
  "name": "Flat White",
  "category": "hot",
  "size_ml": 354,
  "image": "/images/sbux-flat-white.webp",
  "nutrition": {
    "calories_kcal": 160,
    "sugar_g": 14,
    "fat_g": 6,
    "protein_g": 9,
    "caffeine_mg": 130
  }
}
```

**Top-level JSON envelope:**

```json
{
  "schema_version": "1.0",
  "brand": "starbucks",
  "updated": "2026-02-24",
  "drinks": [ ...Drink[] ]
}
```

**Category enum:** `hot | iced | blended | tea | other`

**Brand enum:** `starbucks | costa`

No relational data. No IDs cross-reference between files. Comparison state is held in React component state only — no persistence.

---

## 4. API Contracts

No runtime API. Data access is via static JSON fetched once on app load.

**Data fetch pattern:**

```
GET /data/starbucks.json  → DrinkCatalogEnvelope
GET /data/costa.json      → DrinkCatalogEnvelope
```

Both fetched in parallel via `Promise.all` in the `useDrinks` hook on mount. Responses cached by the browser; no subsequent requests during the session.

**Internal state interface:**

```typescript
interface ComparisonState {
  starbucks: Drink | null;
  costa: Drink | null;
}

interface FilterState {
  category: Category | 'all';
  query: string;
}
```

---

## 5. Technology Stack

### Backend
None. This is a fully static site.

### Frontend
- **React 18** — component model, hooks-based state management
- **Vite 5** — dev server and production bundler (fast HMR, optimised output)
- **Tailwind CSS 3** — utility classes; custom theme tokens for Starbucks green (`#00704A`) and Costa red (`#6B1E1E`)
- **Recharts** — `<BarChart>` for nutrition comparison bars (lighter bundle than Chart.js for this use case)
- **TypeScript** — type safety for drink schema and component props

### Infrastructure
- **Netlify** (primary) or **GitHub Pages** — static hosting with global CDN, zero config deploys from `main` branch
- **GitHub Actions** — CI pipeline: lint → type-check → build → deploy on push to `main`

### Data Storage
Static JSON files in `/public/data/`. No database. No CMS. Data updates require a PR and redeploy.

---

## 6. Integration Points

| Integration | Type | Notes |
|---|---|---|
| Nutritional data source | Manual | Sourced from Costa and Starbucks UK websites; entered into JSON by hand |
| Netlify deploy | CD webhook | GitHub push triggers Netlify build hook automatically |
| Optional analytics | Script tag | Plausible or Fathom (privacy-first, no cookies) — no PII collected |

No external runtime API dependencies.

---

## 7. Security Architecture

- **No user data collected** — no forms, no login, no cookies (beyond optional analytics)
- **No server-side code** — eliminates injection, auth bypass, and server vulnerability surface entirely
- **CSP headers** via `netlify.toml`: restrict script sources to self + analytics domain only
- **HTTPS enforced** by Netlify/GitHub Pages by default
- **No secrets** — no API keys, tokens, or credentials in the codebase
- **Dependency audit** — `npm audit` run in CI; Dependabot alerts enabled on the repo

---

## 8. Deployment Architecture

```
GitHub repo (main branch)
        │  push
        ▼
GitHub Actions CI
  ├── npm ci
  ├── tsc --noEmit
  ├── npm run lint
  └── npm run build → /dist
        │  artifact upload
        ▼
Netlify CDN (global edge)
  └── Serves /dist as static files
      └── Custom domain + HTTPS
```

Single environment (production). No staging required for a static site of this scale. Preview deploys generated automatically per PR by Netlify for QA.

---

## 9. Scalability Strategy

- **Data layer:** JSON envelope schema supports 200+ drinks per brand with zero code changes. New brands added by dropping a new JSON file and updating the `useDrinks` hook import list.
- **CDN edge caching:** Static assets served from Netlify edge nodes globally; no origin bottleneck.
- **Bundle size:** Code-split by route if the app grows (Vite supports this natively). Current scope is a single page — no splitting needed at launch.
- **Component reuse:** `DrinkCard` and `NutritionBar` are brand-agnostic; adding a third brand (e.g., Pret) requires no component changes.

---

## 10. Monitoring & Observability

| Concern | Tool | Detail |
|---|---|---|
| Uptime | Netlify dashboard | Build status and deploy history |
| Performance | Lighthouse CI | Run in GitHub Actions on every PR; fail if score < 90 |
| Errors | Browser console | No error tracking service needed for a static site |
| Analytics | Plausible (optional) | Page views, popular comparisons — no PII |
| Accessibility | axe-core in CI | Zero critical WCAG AA violations gate merges |

---

## 11. Architectural Decisions (ADRs)

**ADR-001: Static SPA over SSR**
All data is known at build time and changes infrequently. SSR (Next.js/Remix) adds hosting complexity and cost with no benefit. Static SPA gives sub-2s loads from CDN with zero server maintenance.

**ADR-002: React state only — no Redux/Zustand**
Comparison state is two nullable drink objects and a filter struct. This is `useState` complexity, not global store complexity. Adding a state library would be over-engineering.

**ADR-003: Recharts over Chart.js**
Recharts is React-native (no imperative canvas refs), tree-shakeable, and its `<BarChart>` API maps directly to the nutrition bar requirement. Chart.js requires a wrapper and larger bundle.

**ADR-004: Tailwind CSS with custom brand tokens**
Tailwind's JIT compiler eliminates unused styles; custom `theme.extend.colors` entries for `starbucks-green` and `costa-red` keep brand colours consistent without a separate design token system.

**ADR-005: Manual JSON data over scraping**
Nutritional data from official websites is authoritative, updated infrequently, and small in volume (60–80 drinks). A scraper introduces maintenance burden and ToS risk. Manual curation is appropriate at this scale.

---

## Appendix: PRD Reference

*(See attached PRD: Costa vs Starbucks — 2026-02-24)*