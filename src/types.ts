/** Coffee brand identifier */
export type Brand = 'starbucks' | 'costa'

/** Drink category */
export type Category = 'hot' | 'iced' | 'blended' | 'tea' | 'other'

/** Nutritional information per serving */
export interface Nutrition {
  calories_kcal: number
  sugar_g: number
  fat_g: number
  protein_g: number
  caffeine_mg: number
}

/** A single drink entry from either brand */
export interface Drink {
  id: string
  brand: Brand
  name: string
  category: Category
  size_ml: number
  image: string
  nutrition: Nutrition
}

/** Top-level JSON envelope for each brand's data file */
export interface DrinkCatalogEnvelope {
  schema_version: string
  brand: Brand
  updated: string
  drinks: Drink[]
}

/** State tracking the currently selected drinks for comparison */
export interface ComparisonState {
  starbucks: Drink | null
  costa: Drink | null
}

/** State for active filters */
export interface FilterState {
  category: Category | 'all'
  query: string
}
