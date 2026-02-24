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

const BRAND_CONFIG: Record<Brand, { label: string; headingClass: string }> = {
  starbucks: {
    label: 'Starbucks',
    headingClass: 'text-starbucks border-b-2 border-starbucks',
  },
  costa: {
    label: 'Costa Coffee',
    headingClass: 'text-costa border-b-2 border-costa',
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
    <section aria-labelledby={`${brand}-heading`}>
      <h2
        id={`${brand}-heading`}
        className={`text-xl font-bold pb-2 mb-4 ${config.headingClass}`}
      >
        {config.label}
      </h2>

      {drinks.length === 0 ? (
        <p className="text-gray-500 text-sm py-4">No drinks match your current filters.</p>
      ) : (
        <ul
          className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4"
          aria-label={`${config.label} drinks`}
        >
          {drinks.map(drink => (
            <li key={drink.id}>
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
