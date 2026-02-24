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
- "Select to Compare" CTA button that toggles to "Selected ✓" when active
- Highlighted ring when `isSelected` is `true` (distinct visual state)
- `data-selected` attribute on the article element (for test hooks); `aria-pressed` on the button for accessibility

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

---

## Ferrari vs Lamborghini Components

### SearchBar

**File:** `src/components/SearchBar.tsx`

Controlled text input for filtering car models by name. Intentionally "dumb" — it renders the current value and forwards keystrokes to `onChange`. The 300 ms debounce is centralised in `useCarCatalog`.

#### Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `value` | `string` | — | Current (un-debounced) input value |
| `onChange` | `(query: string) => void` | — | Called on every keystroke |
| `placeholder` | `string` | `"Search model names…"` | Placeholder text |

#### Features

- Search icon rendered via inline SVG (no external dependency)
- Clear button appears when the input has content; clears on click by calling `onChange('')`
- `aria-label` on the input for screen reader compatibility
- Focus ring in `ferrari-red` on keyboard focus

#### Usage

```tsx
const { searchValue, setSearch } = useCarCatalog();

<SearchBar value={searchValue} onChange={setSearch} />
```

---

### EraFilter

**File:** `src/components/EraFilter.tsx`

Decade-selector filter rendered as a pill button group. Selecting a decade calls `onChange(decade)`; clicking the active decade toggles it off (calls `onChange(undefined)`).

#### Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `value` | `number \| undefined` | — | Currently active decade (undefined = "All") |
| `onChange` | `(decade: number \| undefined) => void` | — | Called when selection changes |
| `decades` | `number[]` | `[1950, 1960, …, 2020]` | Ordered list of decades to render |

#### Features

- "All" pill button always present; pressing it clears the era filter
- Active pill highlighted in `ferrari-red`
- `aria-pressed` on each button for screen reader state
- Wraps onto multiple rows on narrow viewports via `flex-wrap`

#### Usage

```tsx
const { era, setEra } = useCarCatalog();

<EraFilter value={era} onChange={setEra} />
```

---

### CatalogFilters

**File:** `src/components/CatalogFilters.tsx`

Composite filter bar combining `SearchBar` and `EraFilter` inside a styled container. Renders a "Clear all filters" button whenever at least one filter is active.

#### Props

| Prop | Type | Description |
|------|------|-------------|
| `era` | `number \| undefined` | Currently active decade filter |
| `onEraChange` | `(decade: number \| undefined) => void` | Forwarded to `EraFilter` |
| `searchValue` | `string` | Current search input value |
| `onSearchChange` | `(query: string) => void` | Forwarded to `SearchBar` |

#### Usage

```tsx
const { era, setEra, searchValue, setSearch } = useCarCatalog();

<CatalogFilters
  era={era}
  onEraChange={setEra}
  searchValue={searchValue}
  onSearchChange={setSearch}
/>
```

---

### useCarCatalog (hook)

**File:** `src/hooks/useCarCatalog.ts`

Fetches both car catalog JSON files in parallel and exposes filtered, chronologically-sorted arrays for each brand.

#### Filtering

| Filter | Type | Behaviour |
|--------|------|-----------|
| `era` | `number \| undefined` | Narrows results to models whose `decade` matches (e.g. `1980` → 1980–1989) |
| `search` | `string` | Case-insensitive substring match against `CarModel.model`; **debounced 300 ms** |

#### Return value

| Field | Type | Description |
|-------|------|-------------|
| `filteredFerraris` | `CarModel[]` | Ferrari models matching active filters, sorted by `year` ascending |
| `filteredLambos` | `CarModel[]` | Lamborghini models matching active filters, sorted by `year` ascending |
| `loading` | `boolean` | True while the initial fetch is in flight |
| `error` | `string \| null` | Error message if the fetch failed |
| `era` | `number \| undefined` | Current decade filter |
| `setEra` | `(decade: number \| undefined) => void` | Update the decade filter |
| `searchValue` | `string` | Current raw (un-debounced) search string |
| `setSearch` | `(query: string) => void` | Update the search string (debounce applied internally) |

#### Data sources

```
public/data/ferrari.json      → CarCatalogEnvelope for Ferrari
public/data/lamborghini.json  → CarCatalogEnvelope for Lamborghini
```

Both are fetched via `fetch('/data/…')` on mount; the AbortController cleans up on unmount.

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
