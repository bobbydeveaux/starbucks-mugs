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