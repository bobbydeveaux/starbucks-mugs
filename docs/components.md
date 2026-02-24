# React Components

This document describes the React components and hooks for both the Costa vs Starbucks drink comparison and the Ferrari vs Lamborghini car catalog.

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
| `CarModel` | Full car entity: id, brand, model, year, decade, imageUrl, price?, specs, eraRivals |
| `CarCatalogEnvelope` | Root JSON structure for each brand's car data file |
| `CatalogFilters` | `{ decade?: number; search?: string }` — used by `useCarCatalog` |
| `ComparisonStat` | Per-stat winner annotation: `{ label, ferrariValue, lamboValue, winner }` |
| `CarComparisonState` | `{ ferrari: CarModel \| null; lamborghini: CarModel \| null }` |

---

## CarCard

**File:** `src/components/CarCard.tsx`

Renders a single car model as a card in the catalog grid.

### Props

| Prop | Type | Description |
|------|------|-------------|
| `car` | `CarModel` | The car data to display |
| `isSelected` | `boolean` | Whether this card is currently selected for comparison |
| `onSelect` | `(car: CarModel) => void` | Callback fired when the CTA button is clicked |

### Features

- Displays the car model name, year, engine config badge, and four key specs (HP, torque, 0–60, top speed)
- Brand-coloured border (Ferrari red `#DC143C` / Lamborghini yellow `#FFC72C`) for immediate brand identification
- Lazy-loads the car image with a graceful fallback placeholder on error
- "Select to Compare" CTA button that toggles to "Selected ✓" when active
- Highlighted ring when `isSelected` is `true` (distinct visual state)
- `data-selected` and `aria-pressed` attributes for accessibility

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

**File:** `src/components/CatalogPage.tsx`

Reusable catalog page for a single car brand. Fetches the brand's static JSON catalog, renders decade-filter pill buttons, a search input, and a responsive grid of `CarCard` components.

### Props

| Prop | Type | Description |
|------|------|-------------|
| `brand` | `CarBrand` | Which brand to display (`'ferrari'` or `'lamborghini'`) |

### Features

- Brand-themed header (Ferrari red / Lamborghini yellow)
- Free-text search input filtering by model name (case-insensitive)
- Decade pill filter buttons (All, 1950s, 1960s, …) derived from the catalog data
- Clicking the active decade pill deselects it (returns to "All")
- Responsive CSS grid: 1 → 2 → 3 → 4 columns across breakpoints
- Loading spinner while data is being fetched
- Error alert if the fetch fails
- Empty-state message when no cars match the active filters
- Click-to-toggle car selection (clicking a selected card deselects it)

### Usage

```tsx
// In FerrariPage.tsx
<CatalogPage brand="ferrari" />

// In LamborghiniPage.tsx
<CatalogPage brand="lamborghini" />
```

---

## useCarCatalog

**File:** `src/hooks/useCarCatalog.ts`

Fetches a single brand's car catalog JSON from `public/data/{brand}.json` and exposes a filtered list based on the given `CatalogFilters`.

### Signature

```ts
function useCarCatalog(brand: CarBrand, filters?: CatalogFilters): UseCarCatalogResult
```

### Return value

| Field | Type | Description |
|-------|------|-------------|
| `cars` | `CarModel[]` | Cars matching the current filters |
| `loading` | `boolean` | True while the initial fetch is in flight |
| `error` | `string \| null` | Non-null when the fetch fails |
| `decades` | `number[]` | Sorted unique decades from the full (unfiltered) catalog |

### Example

```ts
const { cars, loading, error, decades } = useCarCatalog('ferrari', { decade: 1980, search: 'F40' });
```
