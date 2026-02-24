# ROAM Analysis: costa-vs-starbucks

**Feature Count:** 6
**Created:** 2026-02-24T16:15:19Z

## Risks

1. **Manual Nutritional Data Accuracy** (High): All 60+ drink records are hand-entered from Costa and Starbucks UK websites. A transcription error in calorie or caffeine values directly misleads health-conscious users — the core use case of the site. No automated validation exists in the current plan.

2. **Nutritional Data Staleness** (Medium): Seasonal menu changes (e.g., Pumpkin Spice launch, Christmas range) will silently invalidate static JSON. The plan has no update trigger or staleness indicator, so users may compare drinks that no longer exist or have revised nutrition.

3. **Image Asset Gap** (Medium): The data model references 60+ per-drink `.webp` images (`/images/sbux-flat-white.webp`) but no feature covers sourcing, optimising, or generating these assets. Missing images degrade visual quality and could push the Lighthouse performance score below the ≥90 threshold if handled naively with layout shift.

4. **Lighthouse CI Gate Blocking Deploys** (Medium): A hard ≥90 Lighthouse score requirement in CI will block merges if Recharts, unoptimised images, or Tailwind's CSS output cause regressions. With no staging environment and a single production environment, a blocked pipeline halts all progress.

5. **Recharts Bundle Contribution** (Low): The LLD targets a <150 kB gzipped bundle. Recharts adds ~40–60 kB gzipped. Combined with React 18, Tailwind (minimal via JIT), and TypeScript output, the margin is tight. A single additional dependency risks breaching the budget.

6. **WCAG AA Compliance in Comparison Panel** (Low): The side-by-side `ComparisonPanel` with dynamic `NutritionBar` components involves colour contrast relying on brand tokens (`#00704A`, `#6B1E1E`) and proportional bar widths. These are common sources of contrast failures and missing ARIA labels if not explicitly designed for accessibility from the start.

7. **Same-Brand Duplicate Selection UX** (Low): The plan includes a duplicate brand selection guard in `ComparisonPanel` but the user-facing error behaviour is unspecified. If the guard silently swaps or drops a selection without feedback, users will be confused — particularly on mobile where accidental taps are common.

---

## Obstacles

- **Nutritional data is not yet compiled.** The `costa-vs-starbucks-feat-data-layer` feature (complexity: medium) is blocked until 60+ drink records with all six nutritional fields are manually sourced from Costa and Starbucks UK websites. This is the critical path dependency for every subsequent feature.

- **Drink images do not exist.** No feature in the epic covers sourcing or creating 60+ `.webp` drink images. The `DrinkCard` component references them in the data model but will render broken image placeholders at launch unless a placeholder strategy is decided and implemented explicitly.

- **Netlify site and GitHub Actions configuration are not initialised.** The CI/CD pipeline (`costa-vs-starbucks-feat-project-setup`) must be bootstrapped before any other feature can be tested in a deploy preview. This includes Netlify site creation, environment variable wiring, and Lighthouse CI token setup — none of which are automated.

- **No reference implementation for the comparison interaction pattern.** The PRD cites "reuse interaction patterns from the Starbucks Mugs catalog" but no such catalog code is referenced in the LLD or epic. The `ComparisonPanel` and selection handlers in `App.tsx` must be designed from scratch without an existing pattern to follow.

---

## Assumptions

1. **Official nutritional data is publicly accessible and complete for 30+ drinks per brand.** If either brand's UK website lacks caffeine data or serving size for a significant portion of their menu, the JSON schema will have null fields, violating FR-002 and the "100% complete nutritional fields" success metric. *Validate by auditing both websites before committing to the data layer feature.*

2. **Recharts `<BarChart>` will stay within the <150 kB gzipped bundle budget alongside React 18 and Vite output.** If this assumption fails, the NutritionBar feature (`costa-vs-starbucks-feat-nutrition-bars`) will require a different charting approach or a custom SVG implementation. *Validate with `vite-bundle-visualizer` during project scaffolding, before Recharts is committed to.*

3. **Netlify free tier is sufficient for expected traffic and build frequency.** The plan assumes zero hosting cost. If the site gains meaningful traffic or CI build minutes exceed free-tier limits, the hosting assumption breaks. *Validate by checking current Netlify free-tier limits against expected PR volume and page views.*

4. **`useState` in `App.tsx` will not cause prop-drilling issues across the component tree.** With `DrinkCatalog` → `DrinkCard` needing selection handlers and `ComparisonPanel` needing selected drink objects, state is passed through at least two component layers. If the tree deepens, this assumption will cause maintenance friction. *Validate during `costa-vs-starbucks-feat-drink-cards` implementation; introduce React Context only if prop chains exceed two levels.*

5. **Brand colour tokens (`#00704A`, `#6B1E1E`) meet WCAG AA contrast requirements against white card backgrounds.** Starbucks green at `#00704A` on white has a contrast ratio of ~4.6:1, which passes AA for normal text (≥4.5:1) with minimal margin. Costa red `#6B1E1E` on white is ~9.1:1 — safe. Any tint or opacity applied to these tokens in the UI could break the Starbucks green contrast. *Validate with a contrast checker before finalising Tailwind brand tokens.*

---

## Mitigations

### Risk 1: Manual Nutritional Data Accuracy
- Add a `scripts/validate-data.ts` script (run in CI) that checks every drink record against the TypeScript `Drink` type: all six nutritional fields present, numeric values within plausible ranges (e.g., `calories_kcal` between 0–1000, `caffeine_mg` between 0–500), and no duplicate IDs within a file.
- Store the source URL and date for each drink's nutritional data in a non-schema comment or a companion `_sources.json` file to enable spot-checking and audit trails.
- Conduct a peer review of all 60+ records against the live official websites before the `costa-vs-starbucks-feat-data-layer` feature is merged.

### Risk 2: Nutritional Data Staleness
- Add a visible `data-updated` timestamp in the site footer sourced from the JSON envelope's `updated` field, so users can judge freshness themselves.
- Create a GitHub Issue template for "Nutritional data update" and schedule a quarterly review as a recurring calendar event linked from the repo README.
- The `validate-data.ts` CI script should warn (not fail) if the `updated` field in either JSON file is older than 180 days.

### Risk 3: Image Asset Gap
- Implement CSS brand-colour placeholder cards (Starbucks green / Costa red gradient with drink name centred) as the default `DrinkCard` render when no image is available. This is launch-ready and visually on-brand without requiring any images.
- Add `onerror` fallback on `<img>` tags to swap to the placeholder silently, preventing broken image icons.
- Defer real drink photography/illustrations to a post-launch iteration; document this explicitly in the epic as a follow-on task.

### Risk 4: Lighthouse CI Gate Blocking Deploys
- Run Lighthouse CI locally (`npx lhci autorun`) against the production build during the project scaffolding feature to establish a baseline score before any components are built.
- Set the initial CI threshold at ≥85 and raise it to ≥90 once the image placeholder strategy (Risk 3 mitigation) and bundle budget (Risk 5 mitigation) are confirmed stable.
- Configure `lhci` with `--collect.numberOfRuns=3` to average scores and reduce variance from CI runner noise blocking legitimate merges.

### Risk 5: Recharts Bundle Contribution
- Run `npx vite-bundle-visualizer` after adding Recharts in the scaffolding phase to measure actual contribution before any feature work begins.
- If Recharts pushes the bundle over 120 kB gzipped (leaving <30 kB headroom), replace `NutritionBar` with a pure SVG/CSS proportional bar — the visual requirement (scaled horizontal bars) does not require a full charting library and can be implemented in ~20 lines of TSX.
- Tree-shake Recharts by importing only `BarChart`, `Bar`, `XAxis`, `YAxis`, and `Tooltip` rather than the full package.

### Risk 6: WCAG AA Compliance in Comparison Panel
- Run `axe-core` in Vitest integration tests against the `ComparisonPanel` and `NutritionBar` components from the first day they are implemented — not as a post-launch audit.
- Verify Starbucks green `#00704A` contrast ratio programmatically in `tailwind.config.ts` comments and ensure no opacity modifiers are applied to brand colour classes in brand-bordered cards.
- Add explicit `aria-label` props to all `NutritionBar` instances (e.g., `aria-label="Calories: 160 kcal for Flat White, 140 kcal for Americano"`) in the `getNutritionRows` utility output.

### Risk 7: Same-Brand Duplicate Selection UX
- Define the guard behaviour explicitly in the `ComparisonPanel` component spec: show an inline warning banner ("You've already selected a Starbucks drink — please select a Costa drink to compare") rather than silently blocking or swapping.
- Add a Vitest unit test for `handleSelect` in `App.tsx` covering the duplicate-brand scenario and asserting the warning state is set.
- On mobile, add a brief toast notification (200ms fade-in, 2s duration) to surface the guard feedback without requiring the user to scroll to the comparison panel.

---

## Appendix: Plan Documents

### PRD
# Product Requirements Document: Costa vs Starbucks

I want you to design an extra ordinary website combining the best of both of Starbucks Drinks and Costa drinks. Compare them all, maybe make a savvy react compare model that allows each drink and all the nutrient / calorie information so that one can compare. THIS NEEDS TO BE THE BEST COMPARISON WEBSITE EVAR

**Created:** 2026-02-24T16:10:29Z
**Status:** Draft

## 1. Overview

**Concept:** Costa vs Starbucks

I want you to design an extra ordinary website combining the best of both of Starbucks Drinks and Costa drinks. Compare them all, maybe make a savvy react compare model that allows each drink and all the nutrient / calorie information so that one can compare. THIS NEEDS TO BE THE BEST COMPARISON WEBSITE EVAR

**Description:** Costa vs Starbucks

I want you to design an extra ordinary website combining the best of both of Starbucks Drinks and Costa drinks. Compare them all, maybe make a savvy react compare model that allows each drink and all the nutrient / calorie information so that one can compare. THIS NEEDS TO BE THE BEST COMPARISON WEBSITE EVAR

---

## 2. Goals

1. Deliver the definitive drink comparison site with 30+ drinks per brand and complete nutritional data at launch.
2. Enable side-by-side comparison of Starbucks and Costa drinks covering calories, sugar, fat, protein, and caffeine.
3. Build an intuitive React UI with filtering, search, and visual nutrition indicators that load under 2 seconds.
4. Provide a visually stunning, brand-accurate design that makes health-conscious drink selection genuinely delightful.
5. Become the go-to reference for coffee lovers comparing the two biggest UK coffee chains.

---

## 3. Non-Goals

1. No ordering, purchasing, or any e-commerce functionality.
2. No user accounts, saved comparisons, or personalisation.
3. No real-time API integration with Costa or Starbucks live menus.
4. No coffee shop locator or mapping features.
5. No mobile app — responsive web only.

---

## 4. User Stories

- As a health-conscious consumer, I want to compare calorie counts side-by-side so I can choose the lower-calorie drink.
- As a coffee lover, I want to browse all drinks from both brands so I can discover new options.
- As a user, I want to select two drinks for comparison so I can see their full nutritional breakdown together.
- As a user, I want to filter by category (lattes, frappes, teas) so I can compare like-for-like.
- As a user, I want to search by drink name so I can quickly find a specific drink.
- As a user, I want visual nutrition bars so I can grasp differences at a glance without reading raw numbers.
- As a mobile user, I want a responsive layout so I can compare drinks on my phone.

---

## 5. Acceptance Criteria

**Compare two drinks:**
- Given I'm on the homepage, when I select one Starbucks and one Costa drink, then a side-by-side panel shows calories, sugar, fat, protein, and caffeine for both.

**Filter by category:**
- Given I select "Lattes" from the filter, when the list updates, then only latte drinks from both brands are shown.

**Search:**
- Given I type "Flat White" in the search box, when results appear, then both brands' matching drinks are shown.

**Visual indicators:**
- Given the comparison panel is open, when nutritional data is displayed, then each nutrient has a visual bar scaled to the higher value for instant visual comparison.

---

## 6. Functional Requirements

- **FR-001** Drink catalog: 30+ drinks per brand with name, category, size, and image placeholder.
- **FR-002** Nutritional data per drink: calories, sugar (g), total fat (g), protein (g), caffeine (mg), serving size (ml).
- **FR-003** Side-by-side comparison panel: select one drink per brand and view all nutrients together.
- **FR-004** Visual nutrition bars scaled relative to each other within the comparison view.
- **FR-005** Category filter (Hot, Iced, Blended, Tea, Other) applied across both brands simultaneously.
- **FR-006** Instant search by drink name across both brands.
- **FR-007** Brand-differentiated card design (Starbucks green / Costa red) for immediate visual identification.
- **FR-008** Responsive layout supporting desktop, tablet, and mobile viewports.

---

## 7. Non-Functional Requirements

### Performance
Page load under 2 seconds on standard broadband. Comparison panel renders in under 100ms. All data served from static JSON — no blocking API calls.

### Security
Static site with no user data collected, no authentication, and no server-side processing. No third-party trackers beyond optional analytics.

### Scalability
JSON data structured to support 200+ drinks per brand without code changes. React component architecture supports adding new brands in future.

### Reliability
99.9% uptime target via static hosting (GitHub Pages or Netlify). No runtime dependencies on external APIs.

---

## 8. Dependencies

- **React 18+** — component framework for the comparison UI.
- **Vite** — build tooling for fast development experience.
- **Tailwind CSS** — utility-first styling for brand-themed design.
- **Recharts or Chart.js** — visual nutrition bars in the comparison panel.
- **Nutritional data** — sourced manually from Costa and Starbucks official UK websites.
- **Existing modal/card pattern** — reuse interaction patterns from the Starbucks Mugs catalog as reference.

---

## 9. Out of Scope

- Ordering, delivery, or any e-commerce flow.
- User accounts, login, saved comparisons, or personalisation.
- Live menu/price sync via official APIs (data is static JSON).
- Coffee shop locator, map, or store finder.
- Multi-language support or international menu variants.
- Comparison of food items, snacks, or merchandise.

---

## 10. Success Metrics

- 30+ drinks per brand with 100% complete nutritional fields at launch.
- Comparison feature reachable within 2 clicks from the homepage.
- Lighthouse performance score ≥ 90 (page load under 2 seconds).
- WCAG AA accessibility compliance with zero critical errors.
- Visually distinctive, brand-accurate colour schemes for both chains validated by product owner.
- Qualitative bar: "best comparison website ever" — as set by the concept brief.

---

## Appendix: Clarification Q&A

### Clarification Questions & Answers

### HLD
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

### LLD
The LLD has been written to `docs/concepts/costa-vs-starbucks/LLD.md`. Here's a summary of what was covered:

**Key design decisions captured:**

- **File structure** — 14 source files under `src/` plus `public/data/` JSON and `public/images/`; minimal, no over-engineering
- **Component designs** — Props interfaces and render logic for all 6 components from the HLD (`DrinkCard`, `DrinkCatalog`, `ComparisonPanel`, `NutritionBar`, `FilterBar`, `SearchBox`)
- **Types** — Full TypeScript schema in `src/types.ts` matching the HLD data model exactly
- **State** — All 6 state values in a single table; confirms `useState` in `App.tsx` with no external store
- **Function signatures** — `useDrinks`, `filterDrinks`, all 4 `App` handlers, and `getNutritionRows`
- **Error handling** — 5 failure scenarios covered (fetch fail, malformed JSON, image 404, empty search, duplicate brand selection guard)
- **Test plan** — 7 unit tests (Vitest), 4 integration tests, 5 E2E tests (Playwright + Lighthouse CI)
- **Migration** — 8-step greenfield setup sequence
- **Performance** — Bundle target <150 kB gzipped, lazy images, `.webp`, CDN cache headers