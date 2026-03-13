# ROAM Analysis: petrol-vs-ev-cost-comparison-website

**Feature Count:** 10
**Created:** 2026-03-11T20:41:39Z

## Risks

1. **Seed Data Quality & Completeness** (High): The ≥200 UK vehicle target depends on DVLA/manufacturer CSV exports containing accurate MPG, efficiency, and WLTP data for all fuel types. DVLA open data is inconsistently formatted across model years, and EV efficiency figures vary by trim — incomplete or incorrect seed data directly undermines the ±2% calculation accuracy goal.

2. **Existing Component Contract Coupling** (Medium): Reusing `useCarCatalog`, `ComparisonPanel`, and `SearchBar` without forking assumes these components have stable, well-understood prop interfaces. If their internal data shapes don't accommodate cost/CO2 fields natively, extending them may require deeper refactoring than estimated, or force an undocumented fork anyway.

3. **UK Grid CO2 Factor Staleness** (Medium): The EV CO2 calculation hardcodes the UK grid average at ~233 g CO2/kWh. The National Grid ESO publishes updated figures as the grid decarbonises; an outdated constant will cause the CO2 comparison to misrepresent EV environmental benefit, eroding user trust and undermining a key selling point.

4. **Pricing Data Freshness — Manual Process Risk** (Medium): Weekly pricing updates rely on a manual admin action (or a scheduled GitHub Action calling `PUT /api/admin/pricing`). If this process is skipped or the GitHub Action fails silently, default prices diverge from reality. Stale petrol prices could make comparisons misleading enough to undermine user trust.

5. **URL State Length With Full Price Overrides** (Low): Encoding all comparison state (two vehicle UUIDs, annual mileage, petrol p/litre, electricity p/kWh, three tariff presets, three public charging tiers) into URL query params may produce URLs exceeding browser/server limits (~2,000 chars) or that are practically unshareable. UUID vehicle IDs alone consume 72 characters before any price params.

6. **`html2canvas` PNG Export Reliability** (Low): `html2canvas` is known to produce incomplete or blank exports for components using CSS transforms, SVG gradients (used by Recharts), or cross-origin fonts. PNG export is an explicit FR-011 requirement; silent failures here create a poor experience with no obvious error state for users.

7. **Vercel Postgres Cold-Start Latency** (Low): Serverless functions on Vercel spin up from cold on low-traffic deployments. Combined with Vercel Postgres connection establishment, cold-start latency can push p95 response times above the 500ms vehicle search target during off-peak hours — a risk that won't surface in load testing but will affect real users.

---

## Obstacles

- **No confirmed source for structured UK vehicle seed data**: DVLA open data (VES dataset) provides registration counts and CO2 figures but not MPG or EV efficiency. Manufacturer spec sheets exist but require per-make scraping or manual entry. The seed script (`scripts/seed-vehicles.ts`) is designed but the upstream CSV (`scripts/data/uk-vehicles.csv`) has no confirmed provenance — this blocks `petrol-vs-ev-cost-comparison-website-feat-vehicle-seed` entirely until a reliable data source is identified and formatted.

- **Existing component interfaces not yet audited**: The plan assumes `ComparisonPanel`, `useCarCatalog`, and `SearchBar` can be extended without forking, but no audit of their current prop types, internal state, or render assumptions has been documented. This is a prerequisite for `petrol-vs-ev-cost-comparison-website-feat-vehicle-search` and `petrol-vs-ev-cost-comparison-website-feat-comparison-panel` — the actual extension points need to be confirmed before implementation begins.

- **Admin pricing update workflow undefined**: The `PUT /api/admin/pricing` endpoint is designed, but there is no tooling, runbook, or scheduled automation confirmed for actually performing weekly price updates. Without this, FR-006 (pricing defaults updated at least weekly) is an aspirational requirement with no delivery mechanism.

- **Preview environment DB strategy unresolved**: The HLD notes that PR preview deployments use "a separate DB or read-only fixture data" but this is not decided. Without a concrete approach, PR previews either hit the production DB (a security/data integrity risk) or have no vehicle data (making frontend previews non-functional for reviewers).

---

## Assumptions

1. **DVLA/manufacturer data is sufficient for ≥200 vehicles with required fields**: The plan assumes a combined CSV can be assembled covering petrol, diesel, EV, hybrid, and PHEV vehicles from 2015–2025 with MPG, efficiency, battery, WLTP range, and CO2 populated. *Validation approach*: Before sprint start, download the DVLA VES dataset and at least two manufacturer spec CSVs; confirm field coverage for 20 representative vehicles across all fuel types. If MPG/efficiency gaps exceed 20%, the seed data strategy must change (e.g. supplement with Autotrader/What Car API or manual entry).

2. **Existing `ComparisonPanel`, `useCarCatalog`, and `SearchBar` components can be extended via props without forking**: The plan relies on these components having clean extension points. *Validation approach*: Read the current TypeScript interfaces for all three components before any frontend feature work begins; document the exact props to add and confirm no internal state conflicts with cost field injection.

3. **UK grid CO2 average of ~233 g CO2/kWh is accurate and stable enough for launch**: The EV CO2 calculation (FR-005) uses this constant. *Validation approach*: Cross-reference against the most recent National Grid ESO carbon intensity annual figures; if the figure has shifted >10% from 233 g/kWh, update the constant and add it to the admin-configurable pricing table rather than hardcoding it.

4. **Vercel Postgres connection pooling handles burst traffic within free/starter tier limits**: The scalability strategy relies on Vercel's built-in pooler being sufficient at launch-level traffic. *Validation approach*: Before go-live, run a 100-concurrent-user load test against `GET /api/vehicles` on the production DB tier; confirm p95 ≤500ms and no connection exhaustion errors. Identify the Vercel Postgres plan's connection limit in advance.

5. **The `x-api-key` rate-limiting via Vercel middleware is sufficient to protect the admin endpoint**: The security design assumes Vercel middleware can enforce 10 req/min rate limiting on `PUT /api/admin/pricing`. *Validation approach*: Verify Vercel Edge Middleware supports stateful rate limiting (it requires an external store like Upstash Redis for true rate limiting — stateless middleware alone cannot enforce per-IP limits across invocations). If not natively supported, replace with a lightweight token bucket backed by KV storage before the endpoint goes live.

---

## Mitigations

### Risk 1: Seed Data Quality & Completeness

- **Immediate**: Before writing `scripts/seed-vehicles.ts`, audit the DVLA VES open dataset and two manufacturer spec sources (e.g. Kia, Volkswagen press CSV packs) against the required schema fields. Produce a coverage matrix showing which fields are populated for a 20-vehicle sample.
- **Fallback data strategy**: If DVLA lacks MPG/efficiency fields, use the UK Government's SMMT (Society of Motor Manufacturers and Traders) fuel consumption data, which publishes combined MPG for new registrations annually.
- **Data validation in seed script**: Add a validation pass in `scripts/seed-vehicles.ts` that rejects rows missing `fuel_type`, `mpg_combined` (for ICE), or `efficiency_mpkwh` (for EV), and logs a summary of rejected rows — fail loudly rather than silently seeding incomplete records.
- **Accuracy QA test suite**: Before launch, manually verify cost-per-mile for 10 selected vehicles against RAC/AA published figures; automate these as fixture tests in `costEngine.test.ts` to catch regressions if seed data is re-imported.

### Risk 2: Existing Component Contract Coupling

- **Audit first**: Make reading the TypeScript interfaces of `ComparisonPanel`, `useCarCatalog`, and `SearchBar` a gating task before `petrol-vs-ev-cost-comparison-website-feat-vehicle-search` work begins. Document the extension strategy in a short ADR or code comment block.
- **Extend via optional props with defaults**: Add cost/CO2 fields as optional props with sensible `undefined` defaults so existing usages of `ComparisonPanel` continue to compile and render correctly without modification.
- **Integration test coverage**: Write React Testing Library tests for the extended `ComparisonPanel` with and without cost props to catch regressions if the base component is modified by other contributors.

### Risk 3: UK Grid CO2 Factor Staleness

- **Move to DB**: Store the grid CO2 factor (g CO2/kWh) in the `pricing_defaults` table alongside fuel prices rather than hardcoding it in `costEngine.ts`. Expose it via `GET /api/pricing` and include it in the admin `PUT /api/admin/pricing` update payload.
- **Source and cadence**: Link the `updated_by` audit field to the National Grid ESO carbon intensity annual report URL; include updating this figure in the weekly pricing update runbook.
- **Display transparency**: Show the grid CO2 figure in the UI tooltip on the EV CO2 result with a "Source: National Grid ESO, [year]" label so users can assess recency themselves.

### Risk 4: Pricing Data Freshness — Manual Process Risk

- **Automate the trigger**: Create a GitHub Actions scheduled workflow (cron `0 9 * * 1` — Monday 09:00 UTC) that fetches the latest petrol/diesel average from a stable BEIS or RAC data endpoint and calls `PUT /api/admin/pricing` automatically.
- **Staleness alerting**: The `updated_at` staleness check (alert if >8 days old) is already in the monitoring plan — confirm it is wired to a notification channel (Slack webhook or email) rather than just a dashboard metric.
- **Graceful degradation**: The fallback to last-known DB values with a staleness warning (noted in NFR) must be implemented explicitly — add a `staleness_warning: true` flag to the `GET /api/pricing` response when `updated_at` is >7 days old, and surface a banner in the UI.

### Risk 5: URL State Length With Full Price Overrides

- **Short param keys**: Already called out in the LLD — enforce a key budget (e.g. `v1`, `v2`, `mi`, `pp`, `ep`, `t`, `pc`) and document the full key mapping in `urlStateManager.ts`.
- **Omit defaults from URL**: Only encode price overrides that differ from the current API defaults — if the user hasn't changed petrol price, don't include it in the URL. This keeps the common case (no overrides) to just two vehicle IDs and mileage.
- **UUID shortening**: Consider base62-encoding UUIDs (22 chars vs 36) in URL params to halve vehicle ID length.
- **Test the worst case**: Add a unit test in `urlStateManager.test.ts` that serialises a fully-overridden state and asserts the resulting URL string is under 1,500 characters.

### Risk 6: `html2canvas` PNG Export Reliability

- **Test with Recharts SVG**: Before committing to `html2canvas`, create a spike rendering a `BreakevenChart` instance and capturing it with `html2canvas` in a real browser environment. Verify the output is correct with Recharts' default SVG output and Tailwind-styled containers.
- **Fallback to `recharts` native SVG export**: Recharts SVG elements can be serialised directly to a Blob URL without `html2canvas`. Implement this as a fallback: if `html2canvas` returns a blank canvas (detectable by checking pixel variance), switch to SVG serialisation.
- **User feedback on failure**: If export fails, show a clear error toast rather than silently delivering a blank image. Log the failure to Sentry for tracking.

### Risk 7: Vercel Postgres Cold-Start Latency

- **Connection pooling configuration**: Ensure the serverless functions use `@vercel/postgres` with connection caching across invocations (module-level client instance, not per-request instantiation) to amortise connection overhead.
- **Pre-warm critical path**: Add a lightweight `GET /api/health` endpoint that performs a `SELECT 1` and schedule a synthetic ping (e.g. via Better Uptime) every 5 minutes to keep functions warm during expected traffic windows.
- **Load test before launch**: Run k6 or Artillery with 100 concurrent users against `GET /api/vehicles?q=ford` on the staging environment; if p95 exceeds 400ms (leaving 100ms buffer), move vehicle catalog to a static JSON file generated at build time and served from CDN — this eliminates DB latency entirely for the most common query pattern.

---

## Appendix: Plan Documents

### PRD
# Product Requirements Document: Petrol vs EV Cost Comparison Website

Build a website that allows users to compare the running costs of petrol/diesel vehicles versus electric vehicles (EVs).

## Core Features

### Vehicle Database
- Comprehensive database of cars (make, model, year, variant)
- Petrol/diesel vehicles: MPG (miles per gallon) ratings — combined, city, motorway
- EV vehicles: battery capacity (kWh), range (miles), efficiency (miles per kWh / Wh/mi)
- Support for hybrid and plug-in hybrid (PHEV) vehicles too
- Data sourced from DVLA/manufacturer specs (UK-focused initially, with potential for US/EU)

### Fuel & Tariff Pricing Data
- Current UK petrol and diesel prices (pence per litre) — ideally live or regularly updated
- EV electricity tariffs — standard rate, Economy 7, dedicated EV tariffs (e.g. Octopus Go, OVO Drive Anytime)
- Public charging rates (rapid, ultra-rapid, slow)
- Ability for users to input their own fuel/tariff prices for personalised results

### Cost Comparison Engine
- Calculate cost per mile for petrol vs EV based on selected vehicles
- Annual cost estimates based on user-entered mileage
- Breakeven calculator: how many miles/years until EV is cheaper (factoring in purchase price difference if provided)
- CO2 emissions comparison alongside cost

### UI/UX
- Search and filter cars by make/model/year
- Side-by-side comparison view (petrol car vs EV equivalent)
- Charts/graphs showing cost over time
- Mobile responsive
- Shareable comparison URLs

## Data Requirements
- Need a seeded database of popular UK cars with MPG/efficiency data
- Regular price feed or manual update mechanism for fuel/electricity prices
- Consider using DVLA open data, manufacturer APIs, or scraping Zap-Map / PodPoint for tariff data

## Tech Stack Suggestion
- Frontend: React + TypeScript + Vite
- Backend: Node.js API or serverless functions
- Database: PostgreSQL with car/tariff data
- Hosting: Firebase or similar

## Target Audience
- UK drivers considering switching to EV
- Fleet managers comparing running costs
- Eco-conscious consumers wanting to understand their carbon footprint

**Created:** 2026-03-11T20:35:12Z
**Status:** Draft

## 1. Overview

**Concept:** Petrol vs EV Cost Comparison Website

Build a website that allows users to compare the running costs of petrol/diesel vehicles versus electric vehicles (EVs).

## Core Features

### Vehicle Database
- Comprehensive database of cars (make, model, year, variant)
- Petrol/diesel vehicles: MPG (miles per gallon) ratings — combined, city, motorway
- EV vehicles: battery capacity (kWh), range (miles), efficiency (miles per kWh / Wh/mi)
- Support for hybrid and plug-in hybrid (PHEV) vehicles too
- Data sourced from DVLA/manufacturer specs (UK-focused initially, with potential for US/EU)

### Fuel & Tariff Pricing Data
- Current UK petrol and diesel prices (pence per litre) — ideally live or regularly updated
- EV electricity tariffs — standard rate, Economy 7, dedicated EV tariffs (e.g. Octopus Go, OVO Drive Anytime)
- Public charging rates (rapid, ultra-rapid, slow)
- Ability for users to input their own fuel/tariff prices for personalised results

### Cost Comparison Engine
- Calculate cost per mile for petrol vs EV based on selected vehicles
- Annual cost estimates based on user-entered mileage
- Breakeven calculator: how many miles/years until EV is cheaper (factoring in purchase price difference if provided)
- CO2 emissions comparison alongside cost

### UI/UX
- Search and filter cars by make/model/year
- Side-by-side comparison view (petrol car vs EV equivalent)
- Charts/graphs showing cost over time
- Mobile responsive
- Shareable comparison URLs

## Data Requirements
- Need a seeded database of popular UK cars with MPG/efficiency data
- Regular price feed or manual update mechanism for fuel/electricity prices
- Consider using DVLA open data, manufacturer APIs, or scraping Zap-Map / PodPoint for tariff data

## Tech Stack Suggestion
- Frontend: React + TypeScript + Vite
- Backend: Node.js API or serverless functions
- Database: PostgreSQL with car/tariff data
- Hosting: Firebase or similar

## Target Audience
- UK drivers considering switching to EV
- Fleet managers comparing running costs
- Eco-conscious consumers wanting to understand their carbon footprint

**Description:** Petrol vs EV Cost Comparison Website

Build a website that allows users to compare the running costs of petrol/diesel vehicles versus electric vehicles (EVs).

## Core Features

### Vehicle Database
- Comprehensive database of cars (make, model, year, variant)
- Petrol/diesel vehicles: MPG (miles per gallon) ratings — combined, city, motorway
- EV vehicles: battery capacity (kWh), range (miles), efficiency (miles per kWh / Wh/mi)
- Support for hybrid and plug-in hybrid (PHEV) vehicles too
- Data sourced from DVLA/manufacturer specs (UK-focused initially, with potential for US/EU)

### Fuel & Tariff Pricing Data
- Current UK petrol and diesel prices (pence per litre) — ideally live or regularly updated
- EV electricity tariffs — standard rate, Economy 7, dedicated EV tariffs (e.g. Octopus Go, OVO Drive Anytime)
- Public charging rates (rapid, ultra-rapid, slow)
- Ability for users to input their own fuel/tariff prices for personalised results

### Cost Comparison Engine
- Calculate cost per mile for petrol vs EV based on selected vehicles
- Annual cost estimates based on user-entered mileage
- Breakeven calculator: how many miles/years until EV is cheaper (factoring in purchase price difference if provided)
- CO2 emissions comparison alongside cost

### UI/UX
- Search and filter cars by make/model/year
- Side-by-side comparison view (petrol car vs EV equivalent)
- Charts/graphs showing cost over time
- Mobile responsive
- Shareable comparison URLs

## Data Requirements
- Need a seeded database of popular UK cars with MPG/efficiency data
- Regular price feed or manual update mechanism for fuel/electricity prices
- Consider using DVLA open data, manufacturer APIs, or scraping Zap-Map / PodPoint for tariff data

## Tech Stack Suggestion
- Frontend: React + TypeScript + Vite
- Backend: Node.js API or serverless functions
- Database: PostgreSQL with car/tariff data
- Hosting: Firebase or similar

## Target Audience
- UK drivers considering switching to EV
- Fleet managers comparing running costs
- Eco-conscious consumers wanting to understand their carbon footprint

---

## 2. Goals

1. **Enable accurate cost comparison**: Users can compare petrol/diesel vs EV running costs per mile and annually with ≥95% calculation accuracy against real-world data.
2. **Deliver personalised results**: Users can override default UK fuel/tariff prices with their own, producing a personalised breakeven estimate within seconds.
3. **Cover popular UK vehicles**: Launch with ≥200 seeded UK vehicles (petrol, diesel, EV, hybrid, PHEV) covering top-selling makes/models from 2015–2025.
4. **Drive EV consideration**: At least 60% of users who complete a comparison reach the breakeven calculator, indicating genuine purchase-decision engagement.
5. **Reuse existing comparison infrastructure**: Leverage the existing `useCarCatalog`, `ComparisonPanel`, and `SearchBar` components to reduce build time and maintain UI consistency.

---

## 3. Non-Goals

1. **Vehicle purchasing or financing**: No integration with dealerships, finance calculators, or purchase workflows.
2. **Real-time telemetry or trip tracking**: No GPS, OBD-II, or live journey data — calculations are estimate-based only.
3. **Insurance or road tax comparison**: Running costs are fuel/electricity only; VED and insurance are excluded.
4. **US/EU market launch**: Initial scope is UK-only; internationalisation is a future phase.
5. **User accounts or saved comparisons (server-side)**: No authentication; shareable URLs cover the persistence use case.

---

## 4. User Stories

1. As a **UK driver considering an EV**, I want to select my current petrol car and an equivalent EV so that I can see a side-by-side running cost comparison.
2. As a **cost-conscious commuter**, I want to enter my annual mileage so that I can see my projected yearly fuel spend for both vehicle types.
3. As a **homeowner on an EV tariff**, I want to input my Octopus Go rate so that my EV cost estimate reflects my actual electricity price rather than a default.
4. As a **fleet manager**, I want to compare multiple petrol/EV pairings so that I can evaluate which EV models offer the lowest total running cost across a fleet.
5. As a **eco-conscious consumer**, I want to see CO2 emissions alongside cost so that I can understand the environmental as well as financial impact of switching.
6. As a **user who wants to share findings**, I want a shareable URL for my comparison so that I can send the results to a partner or colleague.
7. As a **prospective EV buyer**, I want a breakeven calculator so that I can see how many years it will take for the EV to pay for itself versus my current petrol car.
8. As a **public charging user**, I want to include rapid-charge rates in cost estimates so that I can model realistic costs without home charging.

---

## 5. Acceptance Criteria

**Story 1 — Side-by-side comparison**
- Given a user searches for a petrol vehicle and an EV, when both are selected, then a side-by-side panel displays cost-per-mile, annual cost (at default 10,000 mi/yr), and CO2 g/km for each.

**Story 2 — Annual mileage input**
- Given a comparison is active, when the user enters annual mileage (1,000–200,000 miles), then annual cost figures update in real time without page reload.

**Story 3 — Custom tariff input**
- Given the pricing panel is visible, when the user overrides the default electricity rate (p/kWh) or petrol price (p/litre), then all cost figures recalculate immediately using the custom values.

**Story 6 — Shareable URL**
- Given a comparison is configured (vehicles + mileage + prices), when the user copies the share URL, then loading that URL in a new browser session restores the identical comparison state.

**Story 7 — Breakeven calculator**
- Given a user enters a purchase price difference (£), when the breakeven section renders, then it displays years-to-breakeven and cumulative savings chart over 10 years.

---

## 6. Functional Requirements

- **FR-001** Vehicle catalog API returns make/model/year/variant with fuel type, MPG (combined/city/motorway) or kWh/100mi, battery capacity, and WLTP range.
- **FR-002** Cost engine calculates cost-per-mile: `(price_per_litre × 4.546) / MPG` for ICE; `(price_per_kWh) / efficiency_miles_per_kWh` for EV.
- **FR-003** Annual cost = cost-per-mile × user-entered annual mileage (default 10,000).
- **FR-004** Breakeven = purchase price delta ÷ annual savings; chart plots cumulative cost difference over 1–15 years.
- **FR-005** CO2 comparison: ICE uses WLTP g/km value from DB; EV uses UK grid average (currently ~233 g CO2/kWh) × kWh/mile.
- **FR-006** Pricing defaults sourced from a DB table updated at least weekly (UK petrol avg, standard electricity rate, 3 EV tariff presets, 3 public charging tiers).
- **FR-007** Users can override any price field; values persist in URL query params.
- **FR-008** Vehicle search supports make/model/year/fuel-type filters, debounced at 300ms, returning results in <500ms.
- **FR-009** Comparison state (vehicle IDs, mileage, prices) encoded in shareable URL; URL decoding restores full state on load.
- **FR-010** UI renders correctly on viewport widths 320px–2560px (mobile-first responsive).
- **FR-011** Charts (cost-over-time, breakeven) rendered via a charting library (e.g. Recharts); exportable as PNG.
- **FR-012** Vehicle DB seeded with ≥200 UK models; admin endpoint (auth-gated) to update pricing data.

---

## 7. Non-Functional Requirements

### Performance
- Initial page load (LCP) ≤2.5s on a 4G connection.
- Cost recalculation on input change ≤100ms client-side.
- Vehicle search API p95 response ≤500ms under 100 concurrent users.

### Security
- No PII collected; no authentication required for end users.
- Admin pricing-update endpoint protected by API key (env var, not committed).
- All external data fetches server-side to avoid exposing third-party API keys to the client.
- Input sanitisation on all user-supplied fields to prevent injection.

### Scalability
- Stateless API (serverless functions) scales horizontally without config changes.
- Vehicle catalog cached at CDN edge (TTL 24h); pricing data cached (TTL 1h).
- PostgreSQL connection pooling via PgBouncer or equivalent to handle burst traffic.

### Reliability
- Target 99.5% uptime (hosted on Firebase/Vercel with automatic failover).
- Graceful degradation: if live pricing feed is unavailable, fall back to last-known DB values with a staleness warning.
- All calculation logic unit-tested with ≥90% coverage.

---

## 8. Dependencies

| Dependency | Purpose |
|---|---|
| Existing `useCarCatalog` hook | Vehicle catalog loading, filtering, era-based sorting — reuse directly |
| Existing `ComparisonPanel` / `ComparisonView` | Side-by-side UI pattern — extend with cost fields |
| Existing `SearchBar` / `SearchBox` | Vehicle search input — reuse as-is |
| PostgreSQL | Vehicle and pricing data persistence |
| Recharts (or equivalent) | Cost-over-time and breakeven charts |
| DVLA / manufacturer specs | Seed data source for MPG and EV efficiency |
| UK petrol price feed (e.g. BEIS/RAC) | Weekly average petrol/diesel prices |
| Node.js serverless functions | Backend API for vehicle search and pricing |
| Firebase Hosting / Vercel | Static frontend hosting + serverless runtime |

---

## 9. Out of Scope

- User accounts, login, or server-persisted saved comparisons
- Insurance, road tax (VED), depreciation, or servicing cost calculations
- US, EU, or non-UK market data and price formats
- Real-time or per-journey fuel/energy tracking
- Vehicle image galleries or media assets
- Dealer or marketplace integrations (buy/finance links)
- Native mobile apps (iOS/Android)
- Crowd-sourced or user-submitted vehicle data

---

## 10. Success Metrics

| Metric | Target | Measurement |
|---|---|---|
| Vehicle catalog coverage | ≥200 UK models at launch | DB row count |
| Breakeven calculator engagement | ≥60% of comparison sessions reach breakeven section | Analytics event |
| Share URL usage | ≥15% of comparison sessions generate a share URL | Analytics event |
| Calculation accuracy | Cost-per-mile within ±2% of verified real-world figures for 10 test vehicles | Manual QA test suite |
| Core Web Vitals | LCP ≤2.5s, CLS ≤0.1, INP ≤200ms | Lighthouse CI |
| Pricing data freshness | Default prices updated within 7 days of RAC/BEIS published changes | Admin audit log |

---

## Appendix: Clarification Q&A

### Clarification Questions & Answers

### HLD
# High-Level Design: Petrol vs EV Cost Comparison Website

**Created:** 2026-03-11T20:36:53Z
**Status:** Draft

## 1. Architecture Overview

The system uses a **JAMstack architecture** with a React SPA frontend, serverless Node.js API functions, and a PostgreSQL database. All cost calculation logic runs client-side; the API serves only data (vehicle catalog, pricing defaults). No user sessions or server-side state are maintained.

```
┌─────────────────────────────────────────────────────┐
│                 CDN / Edge Cache                    │
│         (static assets TTL ∞, pricing TTL 1h,      │
│          vehicle catalog TTL 24h)                   │
└────────────────────┬────────────────────────────────┘
                     │
        ┌────────────▼────────────┐
        │   React SPA (Vite)     │
        │  - Vehicle search UI   │
        │  - Comparison panel    │
        │  - Cost engine (local) │
        │  - Breakeven charts    │
        │  - URL state manager   │
        └────────────┬────────────┘
                     │ REST (JSON)
        ┌────────────▼────────────┐
        │  Serverless Functions  │
        │  (Vercel/Firebase)     │
        │  - /api/vehicles       │
        │  - /api/pricing        │
        │  - /api/admin/pricing  │
        └────────────┬────────────┘
                     │
        ┌────────────▼────────────┐
        │     PostgreSQL DB      │
        │  - vehicles table      │
        │  - pricing_defaults    │
        └─────────────────────────┘
```

Key design choices:
- **Client-side calculation**: All FR-002–FR-005 math runs in the browser; no calculation round-trips.
- **URL as state**: Comparison state serialised into query params (FR-009); no backend session needed.
- **Stateless API**: Functions are pure data accessors — vehicle search and pricing reads only.

---

## 2. System Components

| Component | Responsibility |
|---|---|
| **React SPA** | UI rendering, user input, URL state management |
| **`useCarCatalog` hook** (existing) | Fetches/filters vehicle list from API; reused as-is |
| **`SearchBar` / `SearchBox`** (existing) | Debounced vehicle search input; reused as-is |
| **`ComparisonPanel`** (existing, extended) | Side-by-side display; extended with cost/CO2 fields |
| **`CostEngine` module** (new) | Pure TS functions: cost-per-mile, annual cost, CO2, breakeven |
| **`BreakevenChart`** (new) | Recharts wrapper for cumulative savings over 1–15 years |
| **`PricingPanel`** (new) | Editable tariff overrides (p/litre, p/kWh, EV tariff presets) |
| **`URLStateManager`** (new) | Serialises/deserialises comparison state to/from URL params |
| **`/api/vehicles`** serverless fn | Searches vehicle DB with make/model/year/fuel filters |
| **`/api/pricing`** serverless fn | Returns current default pricing row (petrol, electricity, tariffs) |
| **`/api/admin/pricing`** serverless fn | Auth-gated endpoint to update pricing defaults |
| **PostgreSQL** | Persistent store for vehicle catalog and pricing defaults |
| **DB seed scripts** | One-time import of ≥200 UK vehicles from DVLA/manufacturer data |

---

## 3. Data Model

### `vehicles`
```sql
CREATE TABLE vehicles (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  make          TEXT NOT NULL,
  model         TEXT NOT NULL,
  year          SMALLINT NOT NULL,
  variant       TEXT,
  fuel_type     TEXT NOT NULL,        -- 'petrol'|'diesel'|'ev'|'hybrid'|'phev'
  mpg_combined  NUMERIC(5,2),         -- ICE only
  mpg_city      NUMERIC(5,2),
  mpg_motorway  NUMERIC(5,2),
  efficiency_mpkwh NUMERIC(5,3),     -- EV: miles per kWh
  battery_kwh   NUMERIC(5,1),        -- EV/PHEV
  wltp_range_mi SMALLINT,            -- EV/PHEV
  co2_gkm       SMALLINT,            -- WLTP for ICE; NULL for EV
  created_at    TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON vehicles (make, model, year, fuel_type);
```

### `pricing_defaults`
```sql
CREATE TABLE pricing_defaults (
  id                     SERIAL PRIMARY KEY,
  petrol_ppl             NUMERIC(5,2) NOT NULL,  -- pence per litre
  diesel_ppl             NUMERIC(5,2) NOT NULL,
  electricity_ppkwh      NUMERIC(5,2) NOT NULL,  -- standard rate
  economy7_ppkwh         NUMERIC(5,2),
  octopus_go_ppkwh       NUMERIC(5,2),
  ovo_drive_ppkwh        NUMERIC(5,2),
  public_slow_ppkwh      NUMERIC(5,2),
  public_rapid_ppkwh     NUMERIC(5,2),
  public_ultrarapid_ppkwh NUMERIC(5,2),
  updated_at             TIMESTAMPTZ DEFAULT now(),
  updated_by             TEXT                    -- admin identifier
);
```

**Relationships:** None (flat catalog + single pricing config row). No user tables.

---

## 4. API Contracts

### `GET /api/vehicles`
```
Query params: make, model, year, fuel_type, q (freetext), limit (default 20)
Response 200:
{
  "vehicles": [
    {
      "id": "uuid",
      "make": "Tesla",
      "model": "Model 3",
      "year": 2023,
      "variant": "Long Range AWD",
      "fuel_type": "ev",
      "efficiency_mpkwh": 3.9,
      "battery_kwh": 75.0,
      "wltp_range_mi": 358,
      "co2_gkm": null
    }
  ],
  "total": 42
}
```
- Debounced client-side at 300ms; p95 ≤500ms (FR-008)

### `GET /api/pricing`
```
Response 200:
{
  "petrol_ppl": 145.2,
  "diesel_ppl": 151.4,
  "electricity_ppkwh": 24.5,
  "tariffs": {
    "economy7": 13.0,
    "octopus_go": 7.5,
    "ovo_drive": 9.0
  },
  "public_charging": {
    "slow": 30.0,
    "rapid": 55.0,
    "ultra_rapid": 79.0
  },
  "updated_at": "2026-03-10T12:00:00Z"
}
```

### `PUT /api/admin/pricing`
```
Header: x-api-key: <API_KEY>
Body: { "petrol_ppl": 146.0, ... }
Response 200: { "updated_at": "..." }
Response 401: { "error": "Unauthorized" }
```

---

## 5. Technology Stack

### Backend
- **Runtime:** Node.js 20 (LTS) serverless functions (Vercel Functions or Firebase Cloud Functions)
- **Framework:** Minimal — raw handler functions, no Express overhead
- **DB client:** `postgres` (node-postgres) with connection pooling via Vercel's built-in pooler or PgBouncer
- **Validation:** `zod` for admin endpoint input sanitisation

### Frontend
- **Framework:** React 18 + TypeScript 5 + Vite 5
- **State:** React context + `useReducer` for comparison state; URL sync via `URLSearchParams`
- **Charts:** Recharts (lightweight, tree-shakeable, PNG export via `html2canvas`)
- **Styling:** Tailwind CSS (mobile-first responsive, 320px–2560px)
- **Testing:** Vitest + React Testing Library; ≥90% coverage on `CostEngine`

### Infrastructure
- **Hosting:** Vercel (preferred over Firebase — native serverless functions + PostgreSQL add-on available)
- **CDN:** Vercel Edge Network (static assets, API response caching via `Cache-Control` headers)
- **CI/CD:** GitHub Actions — lint, test, Lighthouse CI, deploy on merge to `main`

### Data Storage
- **Primary DB:** PostgreSQL 16 (Vercel Postgres or Supabase)
- **Caching:** HTTP `Cache-Control` headers on API responses (`max-age=3600` for pricing, `max-age=86400` for vehicles); no Redis needed at this scale

---

## 6. Integration Points

| Integration | Direction | Mechanism | Frequency |
|---|---|---|---|
| BEIS/RAC petrol price data | Inbound | Manual admin update via `PUT /api/admin/pricing` or scheduled GitHub Action calling the endpoint | Weekly |
| DVLA / manufacturer specs | Inbound | One-time seed script (`scripts/seed-vehicles.ts`) parsing CSV/JSON exports | At launch + ad-hoc |
| Recharts PNG export | Internal | `html2canvas` capturing chart DOM node on button click | On demand |
| Analytics (e.g. Plausible) | Outbound | Privacy-respecting script tag; custom events for breakeven view, share URL generation | Continuous |

No real-time external API calls from the browser; all third-party keys stay server-side.

---

## 7. Security Architecture

- **No PII collected**: No user accounts, no cookies, no tracking beyond aggregate analytics.
- **Admin endpoint protection**: `x-api-key` header validated server-side against `ADMIN_API_KEY` env var (never committed). Rate-limited to 10 req/min via Vercel middleware.
- **Input sanitisation**: All query params validated with `zod` schemas before DB queries; parameterised SQL only (no string interpolation).
- **Secret management**: All env vars (`DATABASE_URL`, `ADMIN_API_KEY`) stored in Vercel project settings; excluded from client bundle.
- **CSP headers**: Strict Content-Security-Policy set in `vercel.json` to prevent XSS.
- **HTTPS only**: Enforced by Vercel; HSTS header enabled.
- **No server-side user data**: Comparison state lives in URL; server never touches it.

---

## 8. Deployment Architecture

```
GitHub (main branch)
        │
        ▼ GitHub Actions CI
   lint → test → Lighthouse CI
        │
        ▼ Vercel Deploy
  ┌─────────────────────────────┐
  │  Vercel Edge Network (CDN)  │
  │  - Static SPA bundle        │
  │  - Edge-cached API responses│
  └──────────┬──────────────────┘
             │
  ┌──────────▼──────────────────┐
  │  Vercel Serverless Functions │
  │  /api/vehicles              │
  │  /api/pricing               │
  │  /api/admin/pricing         │
  └──────────┬──────────────────┘
             │
  ┌──────────▼──────────────────┐
  │  Vercel Postgres (managed)  │
  │  + connection pooler        │
  └─────────────────────────────┘
```

- **Preview deployments** auto-generated for each PR (separate DB or read-only fixture data).
- **Migrations** managed with `node-pg-migrate`; run automatically in CI before deploy.
- **Seed script** run once post-deploy via `vercel run scripts/seed-vehicles.ts`.

---

## 9. Scalability Strategy

- **Stateless functions**: Each serverless invocation is independent; scales to thousands of concurrent requests automatically.
- **CDN caching**: Vehicle catalog responses cached 24h at edge; pricing cached 1h. Most traffic never reaches the DB.
- **Client-side calculation**: Zero server load for cost/breakeven computation — scales to unlimited users.
- **DB connection pooling**: Vercel Postgres built-in pooler handles burst traffic without connection exhaustion.
- **Read-heavy workload**: Vehicle catalog is append-rarely, read-frequently — ideal for CDN caching. Pricing table has a single row; trivially cacheable.
- **Future**: If traffic exceeds Vercel Postgres limits, migrate to Supabase or RDS with read replicas. Vehicle catalog could move to a static JSON file served from CDN entirely.

---

## 10. Monitoring & Observability

| Concern | Tool | Detail |
|---|---|---|
| Error tracking | Vercel built-in logs + Sentry (optional) | Function errors, unhandled rejections |
| Performance | Lighthouse CI in GitHub Actions | LCP, CLS, INP gated on every PR |
| Uptime | Vercel status dashboard + Better Uptime ping | Alert if `/api/pricing` returns non-200 |
| Analytics | Plausible (privacy-first, no cookie consent needed) | Page views, comparison completions, share URL clicks, breakeven views |
| Pricing data freshness | Admin audit log (`updated_at` + `updated_by` in DB) | Alert if `updated_at` > 8 days old via scheduled GitHub Action |
| DB health | Vercel Postgres metrics | Connection count, query latency |

---

## 11. Architectural Decisions (ADRs)

**ADR-1: Client-side cost calculation**
- *Decision:* All FR-002–FR-005 math executes in the browser.
- *Rationale:* Eliminates API round-trips for every slider/input change (≤100ms requirement); simplifies testing (pure functions); reduces server costs.
- *Trade-off:* Calculation logic visible in client bundle — acceptable as formulas are public knowledge.

**ADR-2: URL as sole persistence mechanism**
- *Decision:* Comparison state encoded in URL query params; no backend session or localStorage.
- *Rationale:* Satisfies shareable URL requirement (FR-009) with zero backend complexity; no PII stored; browser back/forward works naturally.
- *Trade-off:* URLs can become long with many params — mitigated by using short param keys.

**ADR-3: Vercel over Firebase**
- *Decision:* Deploy on Vercel with Vercel Postgres.
- *Rationale:* Native TypeScript serverless functions, built-in PostgreSQL add-on, automatic preview deployments, and superior DX vs Firebase Functions + Cloud SQL setup.
- *Trade-off:* Vendor lock-in to Vercel — mitigated by standard Node.js functions that can be extracted.

**ADR-4: Reuse existing UI components**
- *Decision:* Extend `ComparisonPanel`, reuse `useCarCatalog` and `SearchBar` without forking.
- *Rationale:* Explicit PRD goal (Goal 5); reduces build time and maintains UI consistency.
- *Trade-off:* Coupling to existing component contracts — document extension points clearly in LLD.

**ADR-5: No Redis / external cache layer**
- *Decision:* Use HTTP `Cache-Control` headers for caching; no Redis.
- *Rationale:* At expected traffic levels (public website, not enterprise), CDN-level caching is sufficient. Adding Redis adds operational complexity with no clear benefit at launch.
- *Revisit trigger:* If DB query latency degrades under load or pricing feed requires sub-minute freshness.

---

## Appendix: PRD Reference

*(See full PRD above in the prompt.)*

### LLD
The LLD has been written to `docs/concepts/petrol-vs-ev-cost-comparison-website/LLD.md`.

Key decisions reflected in the document:

- **File structure** follows the `what-s-the-temp/` sub-app pattern from the existing repo, placing the new feature in `petrol-vs-ev/`.
- **API handlers** live in `api/` at the repo root, matching Vercel's conventions and the existing `vercel.json`.
- **Existing components reused**: `useCarCatalog`, `SearchBar`, `SearchBox`, `ComparisonPanel` — extended via props rather than forked.
- **DB migrations** numbered `005`/`006` to continue the existing `db/migrations/` sequence.
- **CostEngine** is a pure TS module with full function signatures and ≥90% test coverage target.
- **URL state** uses short param keys to keep shareable URLs compact.
- **Rollback** is clean — both new migrations have down scripts, and new routes can be removed without affecting any existing pages.