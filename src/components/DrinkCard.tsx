import type { Drink } from '../types'

interface DrinkCardProps {
  drink: Drink
  isSelected: boolean
  onSelect: (drink: Drink) => void
}

const BRAND_STYLES = {
  starbucks: {
    border: 'border-starbucks',
    badge: 'bg-starbucks text-white',
    button: 'bg-starbucks hover:bg-starbucks-light text-white',
    selectedRing: 'ring-4 ring-starbucks ring-offset-2',
  },
  costa: {
    border: 'border-costa',
    badge: 'bg-costa text-white',
    button: 'bg-costa hover:bg-costa-light text-white',
    selectedRing: 'ring-4 ring-costa ring-offset-2',
  },
} as const

const CATEGORY_LABELS: Record<string, string> = {
  hot: 'Hot',
  iced: 'Iced',
  blended: 'Blended',
  tea: 'Tea',
  other: 'Other',
}

export function DrinkCard({ drink, isSelected, onSelect }: DrinkCardProps) {
  const styles = BRAND_STYLES[drink.brand]

  return (
    <article
      className={[
        'flex flex-col rounded-xl border-2 bg-white shadow-sm transition-all duration-200',
        styles.border,
        isSelected ? styles.selectedRing : 'hover:shadow-md',
      ].join(' ')}
      aria-selected={isSelected}
    >
      {/* Drink image */}
      <div className="aspect-square w-full overflow-hidden rounded-t-xl bg-gray-100">
        <img
          src={drink.image}
          alt={drink.name}
          className="h-full w-full object-cover"
          loading="lazy"
          onError={(e) => {
            ;(e.currentTarget as HTMLImageElement).src =
              'https://placehold.co/400x400/e5e7eb/9ca3af?text=No+Image'
          }}
        />
      </div>

      {/* Card body */}
      <div className="flex flex-1 flex-col gap-2 p-4">
        {/* Category badge */}
        <span
          className={`inline-block self-start rounded-full px-2 py-0.5 text-xs font-semibold uppercase tracking-wide ${styles.badge}`}
        >
          {CATEGORY_LABELS[drink.category] ?? drink.category}
        </span>

        {/* Drink name */}
        <h3 className="text-sm font-semibold leading-snug text-gray-900">
          {drink.name}
        </h3>

        {/* Quick nutrition summary */}
        <p className="text-xs text-gray-500">
          {drink.nutrition.calories_kcal} kcal &middot; {drink.size_ml} ml
        </p>

        {/* CTA */}
        <button
          type="button"
          onClick={() => onSelect(drink)}
          className={[
            'mt-auto rounded-lg px-3 py-2 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-1',
            styles.button,
            isSelected ? 'opacity-80' : '',
          ].join(' ')}
          aria-pressed={isSelected}
        >
          {isSelected ? '✓ Selected' : 'Select to Compare'}
        </button>
      </div>
    </article>
  )
}
