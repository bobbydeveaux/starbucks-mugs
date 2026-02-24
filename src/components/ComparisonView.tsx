import type { CarModel, ComparisonStat } from '../types';

interface ComparisonViewProps {
  ferrari: CarModel | null;
  lambo: CarModel | null;
  winners: ComparisonStat[];
  eraRivalSuggestion?: CarModel | null;
}

/** Text classes for each brand and tie state */
const WINNER_CLASSES = {
  ferrari: 'text-ferrari-red font-bold',
  lamborghini: 'text-lambo-yellow font-bold',
  tie: 'text-gray-600',
} as const;

/** Background highlight for the winning cell */
const WINNER_BG = {
  ferrari: 'bg-red-50',
  lamborghini: 'bg-yellow-50',
  tie: '',
} as const;

function CarColumn({
  car,
  brand,
}: {
  car: CarModel | null;
  brand: 'ferrari' | 'lamborghini';
}) {
  const isFerrari = brand === 'ferrari';
  const headingClass = isFerrari ? 'text-ferrari-red' : 'text-lambo-yellow';
  const borderClass = isFerrari ? 'border-ferrari-red' : 'border-lambo-yellow';
  const label = isFerrari ? 'Ferrari' : 'Lamborghini';

  return (
    <div className={`flex-1 border-t-4 ${borderClass} pt-4`}>
      <p className={`text-xs font-semibold uppercase tracking-wide ${headingClass} mb-1`}>
        {label}
      </p>
      {car ? (
        <>
          {car.image && (
            <div className="mb-3 aspect-video w-full overflow-hidden rounded-lg bg-gray-100">
              <img
                src={car.image}
                alt={`${car.brand} ${car.model} ${car.year}`}
                className="h-full w-full object-cover"
                loading="lazy"
                onError={(e) => {
                  (e.currentTarget as HTMLImageElement).src =
                    'https://placehold.co/640x360/e5e7eb/9ca3af?text=No+Image';
                }}
              />
            </div>
          )}
          <h3 className="font-bold text-gray-900 text-lg leading-tight">
            {car.year} {car.model}
          </h3>
          <p className="text-sm text-gray-500 mt-0.5">{car.specs.engineConfig}</p>
        </>
      ) : (
        <p className="text-gray-400 text-sm mt-2">No car selected</p>
      )}
    </div>
  );
}

function StatRow({ stat }: { stat: ComparisonStat }) {
  const { label, ferrariValue, lamboValue, winner } = stat;

  return (
    <tr className="border-b border-gray-100 last:border-0">
      <td
        className={`py-3 px-4 text-right tabular-nums ${
          winner === 'ferrari' ? `${WINNER_CLASSES.ferrari} ${WINNER_BG.ferrari}` : 'text-gray-700'
        }`}
      >
        {ferrariValue}
      </td>
      <td className="py-3 px-4 text-center text-xs font-medium text-gray-500 whitespace-nowrap">
        {label}
        {winner !== 'tie' && (
          <span
            className={`ml-1 text-xs ${winner === 'ferrari' ? 'text-ferrari-red' : 'text-lambo-yellow'}`}
            aria-label={`${winner} wins`}
          >
            ▲
          </span>
        )}
      </td>
      <td
        className={`py-3 px-4 text-left tabular-nums ${
          winner === 'lamborghini'
            ? `${WINNER_CLASSES.lamborghini} ${WINNER_BG.lamborghini}`
            : 'text-gray-700'
        }`}
      >
        {lamboValue}
      </td>
    </tr>
  );
}

/**
 * Side-by-side stat comparison panel for a selected Ferrari and Lamborghini.
 *
 * - Winning stat values are highlighted in the correct brand colour.
 * - When `eraRivalSuggestion` is provided, a hint is shown beneath the panel.
 * - Renders a clear empty state when neither car is selected yet.
 */
export function ComparisonView({ ferrari, lambo, winners, eraRivalSuggestion }: ComparisonViewProps) {
  const neitherSelected = !ferrari && !lambo;

  if (neitherSelected) {
    return (
      <section
        aria-label="Car comparison"
        className="mt-10 p-8 bg-white rounded-lg shadow-sm border border-gray-200 text-center"
      >
        <p className="text-gray-400 text-sm">
          Select a Ferrari and a Lamborghini above to see the head-to-head stat comparison.
        </p>
      </section>
    );
  }

  return (
    <section
      aria-label="Car comparison"
      className="mt-10 bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden"
    >
      {/* Car headers */}
      <div className="flex gap-6 p-6 border-b border-gray-100">
        <CarColumn car={ferrari} brand="ferrari" />
        <div className="hidden sm:flex items-center px-2">
          <span className="text-2xl font-bold text-gray-300">vs</span>
        </div>
        <CarColumn car={lambo} brand="lamborghini" />
      </div>

      {/* Stat table — only when both cars are selected */}
      {ferrari && lambo && winners.length > 0 ? (
        <table className="w-full" aria-label="Stat comparison table">
          <thead className="sr-only">
            <tr>
              <th scope="col">Ferrari value</th>
              <th scope="col">Stat</th>
              <th scope="col">Lamborghini value</th>
            </tr>
          </thead>
          <tbody>
            {winners.map((stat) => (
              <StatRow key={stat.label} stat={stat} />
            ))}
          </tbody>
        </table>
      ) : (
        <p className="py-6 px-6 text-sm text-gray-400 text-center">
          Select {!ferrari ? 'a Ferrari' : 'a Lamborghini'} to see the stat breakdown.
        </p>
      )}

      {/* Era-rival suggestion */}
      {eraRivalSuggestion && (
        <div className="border-t border-gray-100 px-6 py-4 bg-gray-50">
          <p className="text-xs text-gray-500">
            <span className="font-medium text-gray-700">Era-rival suggestion: </span>
            {eraRivalSuggestion.year} {eraRivalSuggestion.model} is a close contemporary
            from the opposing brand.
          </p>
        </div>
      )}
    </section>
  );
}

export default ComparisonView;
