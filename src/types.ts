export type Brand = 'starbucks' | 'costa';

export type Category = 'hot' | 'iced' | 'blended' | 'tea' | 'other';

export interface Nutrition {
  calories_kcal: number;
  sugar_g: number;
  fat_g: number;
  protein_g: number;
  caffeine_mg: number;
}

export interface Drink {
  id: string;
  brand: Brand;
  name: string;
  category: Category;
  size_ml: number;
  image: string;
  nutrition: Nutrition;
}

export interface DrinkCatalogEnvelope {
  schema_version: string;
  brand: Brand;
  updated: string;
  drinks: Drink[];
}

export interface ComparisonState {
  starbucks: Drink | null;
  costa: Drink | null;
}

export interface FilterState {
  category: Category | 'all';
  query: string;
}
