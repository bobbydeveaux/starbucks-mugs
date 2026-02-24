import type { Category } from '../types';
import { CATEGORIES, CATEGORY_LABELS } from '../utils/filterDrinks';

interface FilterBarProps {
  /** Currently active category filter. */
  category: Category | 'all';
  /** Called when the user selects a different category. */
  onCategoryChange: (category: Category | 'all') => void;
}

/**
 * FilterBar renders a row of toggle buttons — one per drink category plus an
 * "All" option — that allow the user to narrow the visible drink catalog.
 *
 * Only one category can be active at a time. Clicking the already-active
 * button is a no-op (it remains selected).
 */
export function FilterBar({ category, onCategoryChange }: FilterBarProps) {
  return (
    <div role="group" aria-label="Filter by category" className="flex flex-wrap gap-2">
      {CATEGORIES.map((cat) => {
        const isActive = cat === category;
        return (
          <button
            key={cat}
            type="button"
            onClick={() => onCategoryChange(cat)}
            aria-pressed={isActive}
            className={[
              'px-3 py-1.5 rounded-full text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-offset-1 focus:ring-starbucks',
              isActive
                ? 'bg-starbucks text-white'
                : 'bg-white text-gray-600 border border-gray-300 hover:border-starbucks hover:text-starbucks',
            ].join(' ')}
          >
            {CATEGORY_LABELS[cat]}
          </button>
        );
      })}
    </div>
  );
}

export default FilterBar;
