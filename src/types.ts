/**
 * Shared TypeScript types for the Costa vs Starbucks drink comparison app.
 */

/** Brand identifier */
export type Brand = 'starbucks' | 'costa';

/** Drink category */
export type Category = 'hot' | 'iced' | 'blended' | 'tea' | 'other';

/** Nutritional values for a single drink */
export interface DrinkNutrition {
  calories_kcal: number;
  sugar_g: number;
  fat_g: number;
  protein_g: number;
  caffeine_mg: number;
}

/** A single drink entry */
export interface Drink {
  id: string;
  brand: Brand;
  name: string;
  category: Category;
  size_ml: number;
  image: string;
  nutrition: DrinkNutrition;
}

/** Top-level JSON envelope for each brand's data file */
export interface DrinkCatalogEnvelope {
  schema_version: string;
  brand: Brand;
  updated: string;
  drinks: Drink[];
}

/** State for the side-by-side comparison panel (one drink per brand) */
export interface ComparisonState {
  starbucks: Drink | null;
  costa: Drink | null;
}

/** Active filter applied to the drink catalog */
export interface FilterState {
  category: Category | 'all';
  query: string;
}
