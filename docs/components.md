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
