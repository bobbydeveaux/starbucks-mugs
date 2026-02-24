import type { Drink } from '../types';

interface DrinkCardProps {
  drink: Drink;
  isSelected: boolean;
  onSelect: (drink: Drink) => void;
}

const BRAND_STYLES: Record<string, { border: string; badge: string; button: string; selectedRing: string }> = {
  starbucks: {
    border: 'border-starbucks',
    badge: 'bg-starbucks-light text-starbucks',
    button: 'bg-starbucks hover:bg-green-700 text-white',
    selectedRing: 'ring-2 ring-starbucks ring-offset-2',
  },
  costa: {
    border: 'border-costa',
    badge: 'bg-costa-light text-costa',
    button: 'bg-costa hover:bg-red-900 text-white',
    selectedRing: 'ring-2 ring-costa ring-offset-2',
  },
};

const CATEGORY_LABELS: Record<string, string> = {
  hot: 'Hot',
  iced: 'Iced',
  blended: 'Blended',
  tea: 'Tea',
  other: 'Other',
};

export function DrinkCard({ drink, isSelected, onSelect }: DrinkCardProps) {
  const styles = BRAND_STYLES[drink.brand] ?? BRAND_STYLES.starbucks;

  return (
    <article
      className={[
        'bg-white rounded-lg border-2 flex flex-col transition-shadow hover:shadow-md',
        styles.border,
        isSelected ? styles.selectedRing : '',
      ]
        .filter(Boolean)
        .join(' ')}
      aria-label={`${drink.name}, ${drink.brand}, ${drink.category}`}
      data-selected={isSelected}
    >
      {/* Drink image */}
      {drink.image && (
        <div className="aspect-square w-full overflow-hidden rounded-t-lg bg-gray-100">
          <img
            src={drink.image}
            alt={drink.name}
            className="h-full w-full object-cover"
            loading="lazy"
            onError={(e) => {
              (e.currentTarget as HTMLImageElement).src =
                'https://placehold.co/400x400/e5e7eb/9ca3af?text=No+Image';
            }}
          />
        </div>
      )}

      <div className="p-4 flex flex-col gap-3 flex-1">
        <div className="flex items-start justify-between gap-2">
          <h3 className="font-semibold text-gray-900 text-sm leading-snug">{drink.name}</h3>
          <span
            className={`shrink-0 text-xs font-medium px-2 py-0.5 rounded-full capitalize ${styles.badge}`}
          >
            {CATEGORY_LABELS[drink.category] ?? drink.category}
          </span>
        </div>

        <p className="text-xs text-gray-500">{drink.size_ml} ml</p>

        <dl className="text-xs text-gray-600 grid grid-cols-2 gap-x-4 gap-y-1">
          <div>
            <dt className="inline">Cal: </dt>
            <dd className="inline font-medium">{drink.nutrition.calories_kcal} kcal</dd>
          </div>
          <div>
            <dt className="inline">Caffeine: </dt>
            <dd className="inline font-medium">{drink.nutrition.caffeine_mg} mg</dd>
          </div>
          <div>
            <dt className="inline">Sugar: </dt>
            <dd className="inline font-medium">{drink.nutrition.sugar_g} g</dd>
          </div>
          <div>
            <dt className="inline">Fat: </dt>
            <dd className="inline font-medium">{drink.nutrition.fat_g} g</dd>
          </div>
        </dl>

        <button
          type="button"
          onClick={() => onSelect(drink)}
          className={`mt-auto w-full py-2 px-4 rounded text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-offset-1 ${styles.button} ${
            isSelected ? 'opacity-80' : ''
          }`}
          aria-pressed={isSelected}
        >
          {isSelected ? '✓ Selected' : 'Select to Compare'}
        </button>
      </div>
    </article>
  );
}

export default DrinkCard;
