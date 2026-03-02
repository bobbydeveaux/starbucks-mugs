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