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

Renders a side-by-side nutritional comparison of one Costa and one Starbucks drink. Uses `getNutritionRows` to build the rows.

### Props

| Prop | Type | Description |
|------|------|-------------|
| `comparison` | `ComparisonState` | Currently selected drinks (`{ starbucks: Drink \| null; costa: Drink \| null }`) |
| `onClear` | `() => void` | Callback fired when the Clear button is clicked; should reset both selections to `null` |

### Features

- Renders **nothing** when both slots are `null` (no drinks selected)
- Shows a prompt message when only one drink is selected, asking the user to also select a drink from the other brand
- Renders a **guard/error alert** (`role="alert"`) when both selected drinks happen to share the same brand
- Renders a **3-column table** (Nutrient / Costa / Starbucks) with 5 rows: Calories, Sugar, Fat, Protein, Caffeine when two valid drinks are selected
- Lower-value cells for each nutrient are highlighted in brand colour with a `↓` indicator
- Drink names are displayed in the column headers
- Includes a **Clear** button that calls `onClear` to reset both selections

### Usage

```tsx
<ComparisonPanel
  comparison={{ starbucks: selectedStarbucksDrink, costa: selectedCostaDrink }}
  onClear={() => setComparison({ starbucks: null, costa: null })}
/>
```

---

## getNutritionRows

**File:** `src/utils/getNutritionRows.ts`

Pure utility function that maps two `Drink` objects into an ordered array of labelled nutrition rows consumed by `ComparisonPanel`.

### Signature

```ts
function getNutritionRows(costa: Drink, starbucks: Drink): NutritionRow[]
```

### `NutritionRow` shape

```ts
interface NutritionRow {
  label: string;       // e.g. "Calories"
  costaValue: number;
  starbucksValue: number;
  unit: string;        // e.g. "kcal", "g", "mg"
}
```

Returns 5 rows in this order: **Calories** (kcal), **Sugar** (g), **Fat** (g), **Protein** (g), **Caffeine** (mg).

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
