# React Components

This document describes the React components and hooks for the Costa vs Starbucks drink comparison, the Ferrari vs Lamborghini car catalog, and the **Tripwire Real-Time Security Dashboard**.

---

## Tripwire Security Dashboard

### TrendChart

**File:** `src/components/TrendChart.tsx`

Renders a real-time alert volume trend as a stacked Recharts `AreaChart` with one area series per severity level (INFO / WARN / CRITICAL). Data is aggregated client-side from a flat `Alert[]` array so the chart stays in sync with WebSocket-pushed events without additional API round-trips.

#### Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `alerts` | `Alert[]` | — | Raw alert objects to bin and visualise |
| `from` | `Date` | — | Inclusive window start for bucket alignment |
| `to` | `Date` | — | Inclusive window end for bucket alignment |
| `timeRange` | `TimeRange` | — | Active preset shown in the `TimeRangeSelector` |
| `onTimeRangeChange` | `(range: TimeRange) => void` | — | Called when the user selects a different preset |
| `loading` | `boolean` | `false` | Shows a loading overlay while the REST fetch is in flight |
| `error` | `string \| null` | `null` | Shows an error overlay when non-null |
| `className` | `string` | `''` | Extra CSS classes applied to the outermost `<section>` |

#### Features

- **Three severity series** — INFO (blue `#3B82F6`), WARN (amber `#F59E0B`), CRITICAL (red `#EF4444`)
- **Automatic bucket sizing** — hourly buckets for windows ≤ 24 h; daily buckets for longer windows
- **Zero-gap X axis** — every bucket in [from, to] is always present, even when empty
- **Reactive updates** — re-renders within one cycle when the `alerts` prop changes (e.g. WebSocket push)
- **Three states** — loading spinner, error message, empty-state copy, and the chart itself
- **TimeRangeSelector** — five preset buttons (1h / 6h / 24h / 7d / 30d) with `aria-pressed` toggling
- **Accessible** — root `<section aria-label="Alert volume trend chart">`, group label on selector

#### Usage

```tsx
import { TrendChart } from './components/TrendChart';

<TrendChart
  alerts={alerts}
  from={from}
  to={to}
  timeRange={filters.timeRange}
  onTimeRangeChange={(range) => setFilters(f => ({ ...f, timeRange: range }))}
  loading={loading}
  error={error}
/>
```

---

### DashboardPage

**File:** `src/pages/DashboardPage.tsx`

Wires the `useAlerts` hook (REST + WebSocket) to `TrendChart`. Mounted at the `/dashboard` route.

#### Features

- Severity filter (`ALL | INFO | WARN | CRITICAL`) and tripwire-type filter (`ALL | FILE | NETWORK | PROCESS`)
- Alert count badge in the top nav updates in real time as WS events arrive

---

### useAlerts

**File:** `src/hooks/useAlerts.ts`

Fetches alerts from the REST API and patches in live WebSocket events so both the feed and the trend chart update within one render cycle.

#### Signature

```ts
function useAlerts(filters: AlertFilters): UseAlertsResult
```

#### UseAlertsResult

| Field | Type | Description |
|-------|------|-------------|
| `alerts` | `Alert[]` | Combined REST + WS alert list (newest first) |
| `loading` | `boolean` | `true` while the initial fetch is in flight |
| `error` | `string \| null` | Non-null when the fetch fails |
| `from` | `Date` | Computed window start (from `timeRange` preset) |
| `to` | `Date` | Computed window end |

---

### useWebSocket

**File:** `src/hooks/useWebSocket.ts`

Manages a WebSocket connection with automatic exponential-backoff reconnection (1 s → 30 s cap) and optional bearer-token auth via `?token=<value>`.

#### Signature

```ts
function useWebSocket<T>(options: UseWebSocketOptions<T>): void
```

#### UseWebSocketOptions

| Field | Type | Description |
|-------|------|-------------|
| `url` | `string` | Full WebSocket URL |
| `token` | `string?` | Optional bearer token |
| `onMessage` | `(msg: WebSocketMessage<T>) => void` | Called for every successfully parsed JSON frame |
| `enabled` | `boolean` | `true` — set `false` to skip connecting |

---

### aggregateAlertsByTime

**File:** `src/utils/aggregateAlerts.ts`

Aggregates a flat alert list into uniformly-spaced `TrendBucket` objects for recharts.

#### Signature

```ts
function aggregateAlertsByTime(alerts: Alert[], from: Date, to: Date): TrendBucket[]
```

#### TrendBucket shape

```ts
interface TrendBucket {
  time: string;    // X-axis label ("14:00" or "Feb 25")
  timeMs: number;  // Epoch ms — used for sort order
  INFO: number;
  WARN: number;
  CRITICAL: number;
}
```

#### timeRangeToDates

```ts
function timeRangeToDates(preset: TimeRange, now?: Date): { from: Date; to: Date }
```

Converts a `TimeRange` preset string to absolute `[from, to]` dates relative to `now` (defaults to `new Date()`).

---

### Tripwire TypeScript Types

**File:** `src/types.ts`

| Type | Description |
|------|-------------|
| `Severity` | `'INFO' \| 'WARN' \| 'CRITICAL'` |
| `TripwireType` | `'FILE' \| 'NETWORK' \| 'PROCESS'` |
| `HostStatus` | `'ONLINE' \| 'OFFLINE' \| 'DEGRADED'` |
| `Alert` | Full alert entity: `alert_id`, `host_id`, `timestamp`, `tripwire_type`, `rule_name`, `event_detail`, `severity`, `received_at` |
| `Host` | Registered monitoring host: `host_id`, `hostname`, `ip_address`, `platform`, `agent_version`, `last_seen`, `status` |
| `TimeRange` | `'1h' \| '6h' \| '24h' \| '7d' \| '30d'` |
| `AlertFilters` | `{ hostIds, severity, tripwireType, timeRange }` — passed to `useAlerts` |

---

## DrinkCard

**File:** `src/components/DrinkCard.tsx`

Renders a single drink as a card in the catalog grid.

### Props

| Prop | Type | Description |
|------|------|-------------|
| `drink` | `Drink` | The drink data to display |
| `isSelected` | `boolean` | Whether this card is currently selected for comparison |
| `onSelect` | `(drink: Drink) => void` | Callback fired when the CTA button is clicked |

### Features

- Displays the drink name, category badge, calories, and serving size
- Brand-coloured border (Starbucks green `#00704A` / Costa red `#6B1E1E`) for immediate brand identification
- Lazy-loads the drink image with a graceful fallback placeholder on error
- "Select to Compare" CTA button that toggles to "Selected ✓" when active
- Highlighted ring when `isSelected` is `true` (distinct visual state)
- `data-selected` attribute on the `<article>` for test selection hooks; `aria-pressed` on the `<button>` for accessibility

### Starbucks example

```tsx
<DrinkCard
  drink={{ id: 'sbux-flat-white', brand: 'starbucks', name: 'Flat White', ... }}
  isSelected={false}
  onSelect={(drink) => console.log('selected', drink)}
/>
```

---

## DrinkCatalog

**File:** `src/components/DrinkCatalog.tsx`

Renders two brand sections, each containing a responsive grid of `DrinkCard` components.

### Props

| Prop | Type | Description |
|------|------|-------------|
| `drinks` | `Drink[]` | Full list of drinks (both brands); component splits by brand internally |
| `selectedIds` | `{ starbucks: string \| null; costa: string \| null }` | Currently selected drink ID per brand |
| `onSelect` | `(drink: Drink) => void` | Callback forwarded to each `DrinkCard` |

### Features

- Two labelled sections: **Starbucks** (green heading) and **Costa Coffee** (red heading)
- Responsive CSS grid: 2 → 3 → 4 → 5 columns across breakpoints
- Drink count badge per section
- Empty-state message when no drinks match the active filters
- Each section is a `<section>` with an accessible `aria-label`

### Usage

```tsx
<DrinkCatalog
  drinks={allDrinks}
  selectedIds={{ starbucks: 'sbux-flat-white', costa: null }}
  onSelect={handleSelect}
/>
```

---

## Utilities

### filterDrinks

**File:** `src/utils/filterDrinks.ts`

Pure utility function that filters a drinks array by category and/or search query. Consumed by `useDrinks` to apply the active `FilterState`.

#### Signature

```typescript
function filterDrinks(
  drinks: Drink[],
  category: Category | 'all',
  query: string,
): Drink[]
```

#### Behaviour

| Scenario | Result |
|----------|--------|
| `category === 'all'`, empty query | All drinks returned unchanged |
| Specific category | Only drinks with that `category` value |
| Non-empty query | Case-insensitive substring match on `drink.name`; leading/trailing whitespace trimmed |
| Both category and query active | AND logic — must satisfy both conditions |
| Empty input array | Empty array returned without errors |

#### Example

```typescript
import { filterDrinks } from '../utils/filterDrinks';

// Only hot drinks whose name contains "flat" (case-insensitive)
const result = filterDrinks(allDrinks, 'hot', 'flat');
```

---

## FilterBar

**File:** `src/components/FilterBar.tsx`

Renders a row of pill-shaped toggle buttons — one per drink category plus an "All" option — that narrow the visible drink catalog to a single category.

### Props

| Prop | Type | Description |
|------|------|-------------|
| `category` | `Category \| 'all'` | Currently active category filter |
| `onCategoryChange` | `(category: Category \| 'all') => void` | Called when the user selects a different category |

### Features

- Six buttons: **All**, **Hot**, **Iced**, **Blended**, **Tea**, **Other**
- Active button is highlighted with the Starbucks green fill; inactive buttons use a bordered outline style
- `aria-pressed` on each button for screen-reader accessibility
- Wrapped in a `role="group"` container with `aria-label="Filter by category"`

### Usage

```tsx
<FilterBar
  category={filter.category}
  onCategoryChange={(category) => setFilter(f => ({ ...f, category }))}
/>
```

---

## SearchBox

**File:** `src/components/SearchBox.tsx`

Renders a controlled text input that triggers instant client-side filtering of the drink catalog on each keystroke.

### Props

| Prop | Type | Description |
|------|------|-------------|
| `query` | `string` | Current search query string |
| `onQueryChange` | `(query: string) => void` | Called on every keystroke with the updated query |

### Features

- `type="search"` input with browser-native clear button support
- Visually-hidden `<label>` keeps the input accessible without cluttering the UI
- Rounded pill styling consistent with `FilterBar`
- Wired to `useDrinks` via `FilterState.query`; both category and text filters apply simultaneously

### Usage

```tsx
<SearchBox
  query={filter.query}
  onQueryChange={(query) => setFilter(f => ({ ...f, query }))}
/>
```

---

## ComparisonPanel

**File:** `src/components/ComparisonPanel.tsx`

Renders a side-by-side nutritional comparison of one Starbucks and one Costa drink.

### Props

| Prop | Type | Description |
|------|------|-------------|
| `starbucksDrink` | `Drink \| null` | The selected Starbucks drink, or `null` if none selected |
| `costaDrink` | `Drink \| null` | The selected Costa drink, or `null` if none selected |
| `onClear` | `() => void` | Callback fired when the "Clear" button is clicked |

### Features

- Returns `null` (renders nothing) when both drink slots are empty
- Displays a prompt to select the missing brand when only one drink is selected
- Renders a full side-by-side nutrition table once both slots are filled
- Nutrition rows use `getNutritionRows` from `src/utils/getNutritionRows.ts`
- Lower value in each row is highlighted in the brand's colour for quick visual scanning
- "Clear" button calls `onClear` to reset both selections

### Usage

```tsx
<ComparisonPanel
  starbucksDrink={comparison.starbucks}
  costaDrink={comparison.costa}
  onClear={() => setComparison({ starbucks: null, costa: null })}
/>
```

---

## NutritionRow utility

**File:** `src/utils/getNutritionRows.ts`

Produces a labelled comparison row for every nutritional field.

### Signature

```ts
function getNutritionRows(starbucksDrink: Drink, costaDrink: Drink): NutritionRow[]
```

### NutritionRow shape

```ts
interface NutritionRow {
  label: string;         // e.g. "Calories"
  unit: string;          // e.g. "kcal"
  starbucksValue: number;
  costaValue: number;
}
```

### Fields returned (in order)

| # | Label | Unit |
|---|-------|------|
| 1 | Calories | kcal |
| 2 | Sugar | g |
| 3 | Fat | g |
| 4 | Protein | g |
| 5 | Caffeine | mg |

---

## NutritionBar

**File:** `src/components/NutritionBar.tsx`

Renders a side-by-side visual bar comparison for a single nutrition metric between a Starbucks and a Costa drink. Each bar is scaled proportionally so the brand with the higher value spans the full available width.

### Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `label` | `string` | — | Human-readable nutrient label, e.g. `"Calories"` |
| `starbucksValue` | `number` | — | Starbucks drink's value for this nutrient |
| `costaValue` | `number` | — | Costa drink's value for this nutrient |
| `unit` | `string` | — | Unit appended to displayed values, e.g. `"kcal"`, `"g"`, `"mg"` |
| `lowerIsBetter` | `boolean` | `true` | When `true`, the lower value is highlighted as the winner. Pass `false` for protein where higher is preferable. |

### Features

- Bar widths are scaled proportionally: the higher of the two values occupies 100% of the available width
- Winner highlighting: the brand with the better value is bolded and coloured in its brand colour
- Tie state: neither brand is highlighted when values are equal
- Starbucks bar uses `bg-starbucks` (`#00704A`) / Costa bar uses `bg-costa` (`#6B1E1E`)
- Each bar is rendered as a `role="meter"` element with `aria-valuenow`, `aria-valuemin`, and `aria-valuemax` for accessibility
- Zero-safe: when both values are 0, both bars render at 0% width without errors

### Usage

```tsx
// Lower is better (calories, sugar, fat — default)
<NutritionBar
  label="Calories"
  starbucksValue={160}
  costaValue={144}
  unit="kcal"
/>

// Higher is better (protein)
<NutritionBar
  label="Protein"
  starbucksValue={9}
  costaValue={8}
  unit="g"
  lowerIsBetter={false}
/>
```

### Typical usage inside a ComparisonPanel

```tsx
import { NutritionBar } from './NutritionBar';

// Render one row per nutrient
<div className="flex flex-col gap-4">
  <NutritionBar label="Calories"  starbucksValue={sbux.nutrition.calories_kcal} costaValue={costa.nutrition.calories_kcal} unit="kcal" />
  <NutritionBar label="Sugar"     starbucksValue={sbux.nutrition.sugar_g}       costaValue={costa.nutrition.sugar_g}       unit="g" />
  <NutritionBar label="Fat"       starbucksValue={sbux.nutrition.fat_g}         costaValue={costa.nutrition.fat_g}         unit="g" />
  <NutritionBar label="Protein"   starbucksValue={sbux.nutrition.protein_g}     costaValue={costa.nutrition.protein_g}     unit="g"  lowerIsBetter={false} />
  <NutritionBar label="Caffeine"  starbucksValue={sbux.nutrition.caffeine_mg}   costaValue={costa.nutrition.caffeine_mg}   unit="mg" />
</div>
```

---

## CarCard

**File:** `src/components/CarCard.tsx`

Renders a single car model as a top-trump-style stat card in the catalog grid.

### Props

| Prop | Type | Description |
|------|------|-------------|
| `car` | `CarModel` | The car data to display |
| `isSelected` | `boolean` | Whether this card is currently selected for comparison |
| `onSelect` | `(car: CarModel) => void` | Callback fired when the CTA button is clicked |

### Features

- Displays model name, year, decade badge, and all six key stats: HP, torque, 0–60, top speed, engine config, and car image
- Brand-coloured border (`ferrari-red` `#DC143C` / `lambo-yellow` `#FFC72C`) for immediate brand identification
- Lazy-loads the car image with a graceful fallback placeholder on error
- "Select to Compare" CTA button that toggles to "✓ Selected" when active
- Highlighted ring when `isSelected` is `true` (distinct visual state)
- `aria-pressed` and `data-selected` attributes for accessibility

### Ferrari example

```tsx
<CarCard
  car={{ id: 'ferrari-testarossa-1984', brand: 'ferrari', model: 'Testarossa', year: 1984, ... }}
  isSelected={false}
  onSelect={(car) => console.log('selected', car)}
/>
```

---

## CatalogPage

**File:** `src/pages/CatalogPage.tsx`

Renders two brand sections — Ferrari and Lamborghini — each containing a responsive grid of `CarCard` components. Wired to the `/catalog` route in the app shell.

### Features

- Uses `useCarCatalog` to fetch and display car data sorted chronologically
- Two labelled sections: **Ferrari** (red heading) and **Lamborghini** (yellow heading)
- Responsive CSS grid: 1 → 2 → 3 → 4 columns across breakpoints
- Model count badge per section
- Empty-state message when no cars match active filters
- Loading spinner while data is being fetched
- Error alert when the fetch fails

---

## useCarCatalog hook

**File:** `src/hooks/useCarCatalog.ts`

Fetches both brand JSON files in parallel and exposes filtered, chronologically sorted car arrays.

### Signature

```ts
function useCarCatalog(filters?: CatalogFilters): UseCarCatalogResult
```

### UseCarCatalogResult

```ts
interface UseCarCatalogResult {
  ferrariCars: CarModel[];   // filtered & sorted by year
  lamboCars: CarModel[];     // filtered & sorted by year
  loading: boolean;
  error: string | null;
}
```

### Notes

- Fetches `/data/ferrari.json` and `/data/lamborghini.json` in parallel via `fetch`
- Maps the JSON `image` field directly on `CarModel` to match the TypeScript type
- Aborts in-flight requests when the component unmounts

---

## ComparisonView

**File:** `src/components/ComparisonView.tsx`

Renders a side-by-side specification comparison panel for one Ferrari and one Lamborghini.

### Props

| Prop | Type | Description |
|------|------|-------------|
| `ferrari` | `CarModel \| null` | The selected Ferrari, or `null` |
| `lamborghini` | `CarModel \| null` | The selected Lamborghini, or `null` |
| `stats` | `ComparisonStat[]` | Per-stat winner annotations produced by `useComparison` |

### Features

- **Empty state** — shows a prompt to select cars when either slot is empty
- **Brand header row** — Ferrari (red badge) and Lamborghini (yellow badge) with model name, year, and engine config
- **Stat table** — four rows: Horsepower, Torque (lb-ft), 0–60 mph (s), Top Speed (mph)
- **Winner highlighting** — winning value shown in `ferrari-red` or `lambo-yellow`; losing value de-emphasised in gray
- **Score summary** — "Ferrari leads X–Y" / "Lamborghini leads X–Y" / "It's a tie!" beneath the table
- Each stat row has `data-winner` attribute for targeted styling or testing

### Usage

```tsx
const { selectedFerrari, selectedLambo, winners } = useComparison();

<ComparisonView
  ferrari={selectedFerrari}
  lamborghini={selectedLambo}
  stats={winners}
/>
```

---

## TypeScript Types

**File:** `src/types.ts`

### Costa vs Starbucks types

| Type | Description |
|------|-------------|
| `Brand` | `'starbucks' \| 'costa'` |
| `Category` | `'hot' \| 'iced' \| 'blended' \| 'tea' \| 'other'` |
| `DrinkNutrition` | `{ calories_kcal, sugar_g, fat_g, protein_g, caffeine_mg }` |
| `Drink` | Full drink entity including brand, category, size, image, and nutrition |
| `DrinkCatalogEnvelope` | Root JSON structure for each brand's data file |
| `ComparisonState` | `{ starbucks: Drink \| null; costa: Drink \| null }` |
| `FilterState` | `{ category: Category \| 'all'; query: string }` |

### Ferrari vs Lamborghini types

| Type | Description |
|------|-------------|
| `CarBrand` | `'ferrari' \| 'lamborghini'` |
| `CarSpecs` | `{ hp, torqueLbFt, zeroToSixtyMs, topSpeedMph, engineConfig }` |
| `CarModel` | Full car entity: id, brand, model, year, decade, image, price?, specs, eraRivals |
| `CarCatalogEnvelope` | Root JSON structure for each brand's car data file |
| `CatalogFilters` | `{ decade?: number; search?: string }` — used by `useCarCatalog` |
| `ComparisonStat` | Per-stat winner annotation: `{ label, ferrariValue, lamboValue, winner }` |
| `CarComparisonState` | `{ ferrari: CarModel \| null; lamborghini: CarModel \| null }` |

---

## Ferrari vs Lamborghini — Filter Components

### useCarCatalog hook

**File:** `src/hooks/useCarCatalog.ts`

Fetches both car catalog JSON files in parallel and exposes filtered, era-bucketed car arrays.

#### Return value

| Field | Type | Description |
|-------|------|-------------|
| `ferraris` | `CarModel[]` | All raw Ferrari cars (unfiltered, sorted by year) |
| `lambos` | `CarModel[]` | All raw Lamborghini cars (unfiltered, sorted by year) |
| `filteredFerraris` | `CarModel[]` | Ferraris matching the current era and search filters |
| `filteredLambos` | `CarModel[]` | Lamborghinis matching the current era and search filters |
| `availableDecades` | `number[]` | Sorted unique decades derived from both catalogs |
| `loading` | `boolean` | True while the initial JSON fetch is in flight |
| `error` | `string \| null` | Non-null when the fetch fails |
| `era` | `number \| null` | Currently selected decade filter |
| `setEra` | `(era: number \| null) => void` | Update the era filter |
| `search` | `string` | Current raw search query (for controlled input binding) |
| `setSearch` | `(search: string) => void` | Update the search query; filtering is debounced by 300 ms |

#### Usage

```tsx
const { filteredFerraris, filteredLambos, era, setEra, search, setSearch, availableDecades } = useCarCatalog();
```

---

### EraFilter

**File:** `src/components/EraFilter.tsx`

Renders a row of decade-selector buttons that filter the car catalog by era.

#### Props

| Prop | Type | Description |
|------|------|-------------|
| `era` | `number \| null` | Currently selected decade, or `null` for "All Eras" |
| `availableDecades` | `number[]` | Sorted list of decades to render as buttons |
| `onChange` | `(era: number \| null) => void` | Called when the user selects or clears a decade |

#### Features

- "All Eras" button deselects any active decade filter
- Active decade button is highlighted in ferrari-red (`bg-ferrari-red text-white`)
- All buttons expose `aria-pressed` for accessibility
- Clicking the already-selected decade toggles it off (passes `null` to `onChange`)

#### Usage

```tsx
<EraFilter
  era={era}
  availableDecades={[1960, 1970, 1980, 1990, 2000]}
  onChange={setEra}
/>
```

---

### SearchBar

**File:** `src/components/SearchBar.tsx`

Controlled text input for filtering car models by name. Debouncing is handled inside `useCarCatalog` so this component stays a pure controlled input.

#### Props

| Prop | Type | Description |
|------|------|-------------|
| `value` | `string` | Current search value (controlled) |
| `onChange` | `(value: string) => void` | Called on every keystroke |
| `placeholder` | `string` | Optional placeholder text (default: `"Search models…"`) |

#### Features

- Focus ring uses ferrari-red (`focus:border-ferrari-red`)
- Clear (×) button appears when the input is non-empty; calls `onChange('')`
- Accessible `<label>` with `for` linking to the input

#### Usage

```tsx
<SearchBar value={search} onChange={setSearch} />
```

---

### CatalogFilters

**File:** `src/components/CatalogFilters.tsx`

Wrapper that composes `EraFilter` and `SearchBar` into a single filter bar. Renders a "Clear all filters" shortcut when either filter is active.

#### Props

| Prop | Type | Description |
|------|------|-------------|
| `era` | `number \| null` | Currently selected decade |
| `availableDecades` | `number[]` | Passed through to `EraFilter` |
| `onEraChange` | `(era: number \| null) => void` | Era change callback |
| `search` | `string` | Current search query |
| `onSearchChange` | `(search: string) => void` | Search change callback |

#### Usage

```tsx
<CatalogFilters
  era={era}
  availableDecades={availableDecades}
  onEraChange={setEra}
  search={search}
  onSearchChange={setSearch}
/>
```
