# Costa vs Starbucks — React Components

This document describes the React components that form the Costa vs Starbucks drink comparison UI.

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

## useCarCatalog hook

**File:** `src/hooks/useCarCatalog.ts`

Fetches both brand car catalog JSON files in parallel and exposes filtered, chronologically-sorted car arrays. Manages era decade filter state and debounced search query state internally.

### Return value

| Property | Type | Description |
|----------|------|-------------|
| `filteredFerraris` | `CarModel[]` | Ferrari models matching active filters, sorted by year |
| `filteredLambos` | `CarModel[]` | Lamborghini models matching active filters, sorted by year |
| `loading` | `boolean` | `true` while the initial JSON fetch is in flight |
| `error` | `string \| null` | Non-null when the fetch fails |
| `era` | `number \| undefined` | Currently active decade filter (e.g. `1980`); `undefined` = all eras |
| `setEra` | `(decade: number \| undefined) => void` | Set or clear the era decade filter |
| `search` | `string` | Raw (non-debounced) search string as typed by the user |
| `setSearch` | `(query: string) => void` | Update the search string; applied after 300 ms debounce |

### Behaviour

- Fetches `/data/ferrari.json` and `/data/lamborghini.json` in parallel on mount
- Sorts both arrays chronologically by year ascending
- Era filter: when set, only cars whose `decade` matches are returned
- Search filter: case-insensitive match on `model` name; debounced by 300 ms
- Both filters are applied simultaneously

### Usage

```tsx
const { filteredFerraris, filteredLambos, setEra, setSearch } = useCarCatalog();

// Filter to 1980s models
setEra(1980);

// Search model names (debounced 300 ms)
setSearch('Testarossa');

// Clear era filter
setEra(undefined);
```

---

## eraMatchSuggestion utility

**File:** `src/utils/eraMatchSuggestion.ts`

Pure function that maps any car model year to its decade bucket label. Used by the EraFilter component to render decade selector buttons.

### Signature

```typescript
function eraMatchSuggestion(year: number): string
```

### Examples

```typescript
eraMatchSuggestion(1984) // → "1980s"
eraMatchSuggestion(1963) // → "1960s"
eraMatchSuggestion(2023) // → "2020s"
eraMatchSuggestion(1960) // → "1960s"  (first year of decade)
eraMatchSuggestion(1969) // → "1960s"  (last year of decade)
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
| `CarModel` | Full car entity: id, brand, model, year, decade, imageUrl, price?, specs, eraRivals |
| `CarCatalogEnvelope` | Root JSON structure for each brand's car data file |
| `CatalogFilters` | `{ decade?: number; search?: string }` — used by `useCarCatalog` |
| `ComparisonStat` | Per-stat winner annotation: `{ label, ferrariValue, lamboValue, winner }` |
| `CarComparisonState` | `{ ferrari: CarModel \| null; lamborghini: CarModel \| null }` |
