import type { Drink, Category } from '../types';

/**
 * Filters a drinks array by category and/or search query.
 *
 * - Category filter: pass `'all'` to include every category, or a specific
 *   `Category` value to narrow results.
 * - Search filter: case-insensitive substring match on the drink's `name`
 *   field; leading/trailing whitespace in the query is ignored.
 * - Both filters are applied simultaneously (AND logic).
 * - An empty input array returns an empty array without errors.
 *
 * @param drinks - The full list of drinks to filter.
 * @param category - Active category filter, or `'all'` to skip category filtering.
 * @param query - Free-text search string; empty string disables search filtering.
 * @returns A new array containing only the drinks that match all active filters.
 *
 * @example
 * const result = filterDrinks(allDrinks, 'hot', 'flat white');
 * // Returns hot drinks whose name contains "flat white" (case-insensitive)
 */
export function filterDrinks(
  drinks: Drink[],
  category: Category | 'all',
  query: string,
): Drink[] {
  let result = drinks;

  if (category !== 'all') {
    result = result.filter((d) => d.category === category);
  }

  const trimmed = query.trim().toLowerCase();
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
