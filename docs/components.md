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

## filterDrinks

**File:** `src/utils/filterDrinks.ts`

Pure utility function that filters a drinks array by category and free-text search query. Has no UI or React dependency and can be used anywhere.

### Signature

```ts
function filterDrinks(drinks: Drink[], filter: FilterState): Drink[]
```

### Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `drinks` | `Drink[]` | Full list of drinks to filter |
| `filter` | `FilterState` | Active category and search query |

### Behaviour

- When `filter.category` is `'all'`, no category filter is applied.
- `filter.query` is trimmed and lowercased before matching; matching is case-insensitive substring search on `drink.name`.
- Both filters are applied simultaneously — a drink must satisfy both to appear in the result.
- Does **not** mutate the input array.

### Example

```ts
import { filterDrinks } from '../utils/filterDrinks';

// Hot drinks only
filterDrinks(allDrinks, { category: 'hot', query: '' });

// Name search across all categories
filterDrinks(allDrinks, { category: 'all', query: 'latte' });

// Category + name combined
filterDrinks(allDrinks, { category: 'hot', query: 'flat white' });
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
