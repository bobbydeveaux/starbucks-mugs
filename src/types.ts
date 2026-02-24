/**
 * TypeScript type definitions for the Costa vs Starbucks comparison app.
 * Matches the data model defined in docs/concepts/costa-vs-starbucks/HLD.md.
 */

// ---------------------------------------------------------------------------
// Enums / discriminated union types
// ---------------------------------------------------------------------------

/** Brand enum — one value per chain supported by the app */
export type Brand = 'starbucks' | 'costa';

/** Drink category enum — matches the categories used in both chains' menus */
export type Category = 'hot' | 'iced' | 'blended' | 'tea' | 'other';

// ---------------------------------------------------------------------------
// Core data model
// ---------------------------------------------------------------------------

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
  /** Slug-style unique identifier, e.g. "sbux-flat-white" or "costa-flat-white". */
  id: string;
  brand: Brand;
  name: string;
  category: Category;
  /** Serving size in millilitres. */
  size_ml: number;
  /** Path to the drink image relative to the public root, e.g. "/images/sbux-flat-white.webp". */
  image?: string;
  nutrition: Nutrition;
}

// ---------------------------------------------------------------------------
// JSON data envelope
// ---------------------------------------------------------------------------

/**
 * Top-level structure for each static JSON data file
 * (`public/data/starbucks.json` and `public/data/costa.json`).
 */
export interface DrinkCatalogEnvelope {
  schema_version: string;
  brand: Brand;
  /** ISO 8601 date string indicating when this data file was last updated. */
  updated: string;
  drinks: Drink[];
}

// ---------------------------------------------------------------------------
// Application state
// ---------------------------------------------------------------------------

/**
 * Tracks which drink has been selected for comparison from each brand.
 * `null` means no drink is currently selected for that brand.
 */
export interface ComparisonState {
  starbucks: Drink | null;
  costa: Drink | null;
}

/** Active filter state — category filter and free-text search query */
export interface FilterState {
  /** Selected category, or "all" to show every category. */
  category: Category | 'all';
  /** Free-text search string. Empty string means no search filter is active. */
  query: string;
}
