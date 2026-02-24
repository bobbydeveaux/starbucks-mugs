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
- `data-selected` attribute on the article element for test/CSS selection hooks
- `aria-pressed` on the CTA button for screen-reader toggle state

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

## ComparisonView

**File:** `src/components/ComparisonView.tsx`

Renders a side-by-side specification comparison panel for one Ferrari and one Lamborghini.

### Props

| Prop | Type | Description |
|------|------|-------------|
| `ferrari` | `CarModel \| null` | The selected Ferrari, or `null` |
| `lamborghini` | `CarModel \| null` | The selected Lamborghini, or `null` |
| `stats` | `ComparisonStat[]` | Per-stat winner annotations produced by `useComparison` |

### Features

- **Empty state** — shows a prompt to select cars when either slot is empty
- **Brand header row** — Ferrari (red badge) and Lamborghini (yellow badge) with model name, year, and engine config
- **Stat table** — four rows: Horsepower, Torque (lb-ft), 0–60 mph (s), Top Speed (mph)
- **Winner highlighting** — winning value shown in `ferrari-red` or `lambo-yellow`; losing value de-emphasised in gray
- **Score summary** — "Ferrari leads X–Y" / "Lamborghini leads X–Y" / "It's a tie!" beneath the table
- Each stat row has `data-winner` attribute for targeted styling or testing

### Usage

```tsx
const { selectedFerrari, selectedLambo, winners } = useComparison();

<ComparisonView
  ferrari={selectedFerrari}
  lamborghini={selectedLambo}
  stats={winners}
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
