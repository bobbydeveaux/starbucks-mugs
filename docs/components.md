# React Components

This document describes the React components that power the Costa vs Starbucks and Ferrari vs Lamborghini comparison UIs.

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
- "Select to Compare" CTA button that toggles to "✓ Selected" when active
- Highlighted ring when `isSelected` is `true` (distinct visual state)
- `aria-selected` and `aria-pressed` attributes for accessibility

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

## ComparisonView

**File:** `src/components/ComparisonView.tsx`

Side-by-side stat comparison panel for a selected Ferrari and Lamborghini model.

### Props

| Prop | Type | Description |
|------|------|-------------|
| `ferrari` | `CarModel \| null` | Selected Ferrari (or `null`) |
| `lambo` | `CarModel \| null` | Selected Lamborghini (or `null`) |
| `winners` | `ComparisonStat[]` | Per-stat winner annotations produced by `useComparison` |
| `eraRivalSuggestion` | `CarModel \| null \| undefined` | Optional era-rival hint shown beneath the panel |

### Features

- Brand-coloured top border (Ferrari red `#DC143C` / Lamborghini yellow `#FFC72C`)
- Car image with year + model name header per column
- Stat table with winning value highlighted in the correct brand colour per row
- Winner indicator arrow (▲) displayed next to the stat label
- Era-rival suggestion footer when `eraRivalSuggestion` is provided
- Clean empty-state message when neither car is selected

### Usage

```tsx
<ComparisonView
  ferrari={selectedFerrari}
  lambo={selectedLambo}
  winners={winners}
  eraRivalSuggestion={suggestion}
/>
```

---

## Ferrari vs Lamborghini — Hooks

### useComparison

**File:** `src/hooks/useComparison.ts`

Manages which Ferrari and Lamborghini are selected for comparison and derives per-stat winner annotations.

| Return value | Type | Description |
|---|---|---|
| `selectedFerrari` | `CarModel \| null` | Currently selected Ferrari |
| `selectedLambo` | `CarModel \| null` | Currently selected Lamborghini |
| `setSelectedFerrari` | `(car: CarModel \| null) => void` | Setter for Ferrari selection |
| `setSelectedLambo` | `(car: CarModel \| null) => void` | Setter for Lamborghini selection |
| `winners` | `ComparisonStat[]` | Stat comparison results; empty when fewer than two cars selected |

Stats compared: Horsepower (higher wins), Torque (higher wins), 0–60 mph (lower wins), Top Speed (higher wins).

### useCarCatalog

**File:** `src/hooks/useCarCatalog.ts`

Fetches both brand JSON catalogs in parallel and returns chronologically sorted car arrays, mirroring the `useDrinks` pattern.

| Return value | Type | Description |
|---|---|---|
| `ferrariCars` | `CarModel[]` | All Ferrari models, sorted by year ascending |
| `lamboCars` | `CarModel[]` | All Lamborghini models, sorted by year ascending |
| `loading` | `boolean` | True while JSON fetch is in flight |
| `error` | `string \| null` | Non-null on fetch failure |

---

## Ferrari vs Lamborghini — Utilities

### eraMatchSuggestion

**File:** `src/utils/eraMatchSuggestion.ts`

Pure function that pairs a selected car with its closest-year era rival using the `eraRivals` id list embedded in the JSON catalog.

```ts
eraMatchSuggestion(selected: CarModel, opponentCatalog: CarModel[]): CarModel | null
```

- Filters `opponentCatalog` to only the IDs listed in `selected.eraRivals`
- Returns the candidate whose year is closest to `selected.year`
- Returns `null` when `eraRivals` is empty, the catalog is empty, or no rival IDs are found
