import type { Drink, Brand } from '../types';
import { DrinkCard } from './DrinkCard';

interface SelectedIds {
  starbucks: string | null;
  costa: string | null;
}

interface DrinkCatalogProps {
  drinks: Drink[];
  selectedIds: SelectedIds;
  onSelect: (drink: Drink) => void;
}

const BRAND_CONFIG: Record<Brand, { label: string; headingClass: string; dividerClass: string; emptyText: string }> = {
  starbucks: {
    label: 'Starbucks',
    headingClass: 'text-starbucks',
    dividerClass: 'border-starbucks',
    emptyText: 'No Starbucks drinks match your filters.',
  },
  costa: {
    label: 'Costa Coffee',
    headingClass: 'text-costa',
    dividerClass: 'border-costa',
    emptyText: 'No Costa drinks match your filters.',
  },
};

function BrandSection({
  brand,
  drinks,
  selectedId,
  onSelect,
}: {
  brand: Brand;
  drinks: Drink[];
  selectedId: string | null;
  onSelect: (drink: Drink) => void;
}) {
  const config = BRAND_CONFIG[brand];

  return (
    <section aria-label={`${config.label} drinks`}>
      <div className="mb-4 flex items-center gap-3">
        <h2
          className={`text-xl font-bold ${config.headingClass}`}
        >
          {config.label}
        </h2>
        <span className="text-sm text-gray-500">({drinks.length} drinks)</span>
        <div className={`flex-1 border-t ${config.dividerClass}`} />
      </div>

      {drinks.length === 0 ? (
        <p className="py-8 text-center text-sm text-gray-400">
          {config.emptyText}
        </p>
      ) : (
        <ul
          className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4"
          role="list"
          aria-label={`${config.label} drink cards`}
        >
          {drinks.map(drink => (
            <li key={drink.id} role="listitem">
              <DrinkCard
                drink={drink}
                isSelected={drink.id === selectedId}
                onSelect={onSelect}
              />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export function DrinkCatalog({ drinks, selectedIds, onSelect }: DrinkCatalogProps) {
  const starbucksDrinks = drinks.filter(d => d.brand === 'starbucks');
  const costaDrinks = drinks.filter(d => d.brand === 'costa');

  return (
    <div className="flex flex-col gap-10">
      <BrandSection
        brand="starbucks"
        drinks={starbucksDrinks}
        selectedId={selectedIds.starbucks}
        onSelect={onSelect}
      />
      <BrandSection
        brand="costa"
        drinks={costaDrinks}
        selectedId={selectedIds.costa}
        onSelect={onSelect}
      />
    </div>
  );
}

export default DrinkCatalog;
