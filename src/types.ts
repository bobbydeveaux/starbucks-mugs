/** Brand enum — one value per chain supported by the app */
export type Brand = 'starbucks' | 'costa';

/** Drink category enum — matches the categories used in both chains' menus */
export type Category = 'hot' | 'iced' | 'blended' | 'tea' | 'other';

/** Nutritional data for a single drink */
export interface Nutrition {
  calories_kcal: number;
  sugar_g: number;
  fat_g: number;
  protein_g: number;
  caffeine_mg: number;
}

/** A single drink entry from either brand's JSON file */
export interface Drink {
  id: string;
  brand: Brand;
  name: string;
  category: Category;
  size_ml: number;
  image?: string;
  nutrition: Nutrition;
}

/** Top-level JSON envelope wrapping the drinks array for each brand */
export interface DrinkCatalogEnvelope {
  schema_version: string;
  brand: Brand;
  updated: string;
  drinks: Drink[];
}

/** Comparison state — at most one selected drink per brand */
export interface ComparisonState {
  starbucks: Drink | null;
  costa: Drink | null;
}

/** Active filter state — category filter and free-text search query */
export interface FilterState {
  category: Category | 'all';
  query: string;
}
