import type { Drink, Category, FilterState } from '../types';

/**
 * Filters an array of drinks by category and free-text search query.
 *
 * - Category `'all'` matches every drink regardless of its category.
 * - Search matching is case-insensitive and matches on the drink name.
 * - Both filters are applied simultaneously (AND logic).
 *
 * @param drinks - Full list of drinks to filter.
 * @param filter - Active category and search query.
 * @returns A new array containing only the drinks that match the filter.
 *
 * @example
 * filterDrinks(allDrinks, { category: 'hot', query: 'latte' });
 * // → drinks in the "hot" category whose name includes "latte" (case-insensitive)
 */
export function filterDrinks(drinks: Drink[], filter: FilterState): Drink[] {
  let result = drinks;

  if (filter.category !== 'all') {
    result = result.filter((d) => d.category === filter.category);
  }

  const trimmed = filter.query.trim().toLowerCase();
  if (trimmed) {
    result = result.filter((d) => d.name.toLowerCase().includes(trimmed));
  }

  return result;
}

/** All valid category values, including the synthetic "all" option. */
export const CATEGORIES: Array<Category | 'all'> = [
  'all',
  'hot',
  'iced',
  'blended',
  'tea',
  'other',
];

/** Human-readable label for each category value. */
export const CATEGORY_LABELS: Record<Category | 'all', string> = {
  all: 'All',
  hot: 'Hot',
  iced: 'Iced',
  blended: 'Blended',
  tea: 'Tea',
  other: 'Other',
};
