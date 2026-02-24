import type { Category } from '../types';

const CATEGORIES: Array<{ value: Category | 'all'; label: string }> = [
  { value: 'all', label: 'All' },
  { value: 'hot', label: 'Hot' },
  { value: 'iced', label: 'Iced' },
  { value: 'blended', label: 'Blended' },
  { value: 'tea', label: 'Tea' },
  { value: 'other', label: 'Other' },
];

interface FilterBarProps {
  category: Category | 'all';
  onCategoryChange: (category: Category | 'all') => void;
}

export function FilterBar({ category, onCategoryChange }: FilterBarProps) {
  return (
    <div role="group" aria-label="Filter by category" className="flex flex-wrap gap-2">
      {CATEGORIES.map(({ value, label }) => (
        <button
          key={value}
          type="button"
          onClick={() => onCategoryChange(value)}
          aria-pressed={category === value}
          className={[
            'px-3 py-1.5 rounded-full text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-offset-1',
            category === value
              ? 'bg-gray-900 text-white focus:ring-gray-900'
              : 'bg-white text-gray-700 border border-gray-300 hover:bg-gray-50 focus:ring-gray-300',
          ].join(' ')}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

export default FilterBar;
