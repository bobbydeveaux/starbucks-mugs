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