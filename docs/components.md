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
- `data-selected` attribute on the article element for test hooks; `aria-pressed` on the button for accessibility

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
- Each section is a `<section aria-labelledby>` with an accessible landmark role

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
