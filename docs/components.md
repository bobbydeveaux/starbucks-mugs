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

## NutritionBar

**File:** `src/components/NutritionBar.tsx`

Renders a proportional horizontal bar chart for a single nutrient using Recharts `BarChart`. Bar widths are scaled relative to the higher of the two compared values, making it easy to compare nutrients at a glance.

### Props

| Prop | Type | Default | Description |
|------|------|---------|-------------|
| `costaValue` | `number` | — | Nutritional value for the Costa drink |
| `starbucksValue` | `number` | — | Nutritional value for the Starbucks drink |
| `unit` | `string` | `''` | Unit label appended to values in the accessible label (e.g. `"kcal"`, `"g"`) |

### Features

- Costa (red `#6B1E1E`) shown in the top bar; Starbucks (green `#00704A`) in the bottom bar
- Both bars scale proportionally to the maximum of the two values (domain `[0, max]`)
- Animations disabled (`isAnimationActive={false}`) for test stability
- `role="img"` wrapper with a descriptive `aria-label` for screen readers
- Handles zero values gracefully (defaults domain max to `1` to avoid division-by-zero)

### Usage

```tsx
<NutritionBar costaValue={144} starbucksValue={190} unit="kcal" />
```

---

## ComparisonPanel

**File:** `src/components/ComparisonPanel.tsx`

Displays a side-by-side nutritional comparison of one Costa drink and one Starbucks drink. Each of the five nutritional fields is visualised with a `NutritionBar`. Renders `null` when both drinks are `null`.

### Props

| Prop | Type | Description |
|------|------|-------------|
| `starbucks` | `Drink \| null` | Selected Starbucks drink, or `null` |
| `costa` | `Drink \| null` | Selected Costa drink, or `null` |
| `onClear` | `() => void` | Callback to clear both selections |

### Nutritional fields shown

| Field | Unit |
|-------|------|
| Calories | kcal |
| Sugar | g |
| Fat | g |
| Protein | g |
| Caffeine | mg |

### Behaviour

- Renders `null` when both `starbucks` and `costa` are `null`
- Shows drink names in brand-coloured headers (Costa red / Starbucks green)
- When only one drink is selected, shows a prompt to select from the other brand
- When both drinks are selected, renders full nutritional comparison rows with `NutritionBar`
- Provides a "Clear" button that calls `onClear` to reset both selections

### Usage

```tsx
<ComparisonPanel
  starbucks={comparison.starbucks}
  costa={comparison.costa}
  onClear={handleClearComparison}
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
