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
