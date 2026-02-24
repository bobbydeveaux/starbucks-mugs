import type { CarModel } from '../types';

interface CarCardProps {
  car: CarModel;
  isSelected: boolean;
  onSelect: (car: CarModel) => void;
}

const BRAND_STYLES: Record<string, { border: string; badge: string; button: string; selectedRing: string }> = {
  ferrari: {
    border: 'border-ferrari-red',
    badge: 'bg-red-100 text-ferrari-red',
    button: 'bg-ferrari-red hover:bg-red-700 text-white focus:ring-ferrari-red',
    selectedRing: 'ring-2 ring-ferrari-red ring-offset-2',
  },
  lamborghini: {
    border: 'border-lambo-yellow',
    badge: 'bg-yellow-100 text-yellow-800',
    button: 'bg-lambo-yellow hover:bg-yellow-400 text-gray-900 focus:ring-lambo-yellow',
    selectedRing: 'ring-2 ring-lambo-yellow ring-offset-2',
  },
};

export function CarCard({ car, isSelected, onSelect }: CarCardProps) {
  const styles = BRAND_STYLES[car.brand] ?? BRAND_STYLES.ferrari;

  return (
    <article
      className={[
        'bg-white rounded-lg border-2 flex flex-col transition-shadow hover:shadow-md',
        styles.border,
        isSelected ? styles.selectedRing : '',
      ]
        .filter(Boolean)
        .join(' ')}
      aria-label={`${car.model} ${car.year}, ${car.brand}`}
      data-selected={isSelected}
    >
      {/* Car image */}
      <div className="aspect-video w-full overflow-hidden rounded-t-lg bg-gray-100">
        <img
          src={car.imageUrl}
          alt={`${car.model} ${car.year}`}
          className="h-full w-full object-cover"
          loading="lazy"
          onError={(e) => {
            (e.currentTarget as HTMLImageElement).src =
              'https://placehold.co/400x225/e5e7eb/9ca3af?text=No+Image';
          }}
        />
      </div>

      <div className="p-4 flex flex-col gap-3 flex-1">
        {/* Header: model name + era badge */}
        <div className="flex items-start justify-between gap-2">
          <div>
            <h3 className="font-semibold text-gray-900 text-sm leading-snug">{car.model}</h3>
            <p className="text-xs text-gray-500 mt-0.5">{car.year}</p>
          </div>
          <span
            className={`shrink-0 text-xs font-medium px-2 py-0.5 rounded-full ${styles.badge}`}
          >
            {car.decade}s
          </span>
        </div>

        {/* Specs */}
        <dl className="text-xs text-gray-600 grid grid-cols-2 gap-x-4 gap-y-1">
          <div>
            <dt className="inline">HP: </dt>
            <dd className="inline font-medium">{car.specs.hp}</dd>
          </div>
          <div>
            <dt className="inline">Torque: </dt>
            <dd className="inline font-medium">{car.specs.torqueLbFt} lb-ft</dd>
          </div>
          <div>
            <dt className="inline">0–60: </dt>
            <dd className="inline font-medium">{car.specs.zeroToSixtyMs}s</dd>
          </div>
          <div>
            <dt className="inline">Top Speed: </dt>
            <dd className="inline font-medium">{car.specs.topSpeedMph} mph</dd>
          </div>
          <div className="col-span-2">
            <dt className="inline">Engine: </dt>
            <dd className="inline font-medium">{car.specs.engineConfig}</dd>
          </div>
        </dl>

        <button
          type="button"
          onClick={() => onSelect(car)}
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

export default CarCard;
