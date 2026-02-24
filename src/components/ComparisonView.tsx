import type { CarModel, ComparisonStat } from '../types';

interface ComparisonViewProps {
  ferrari: CarModel | null;
  lamborghini: CarModel | null;
  stats: ComparisonStat[];
}

const WINNER_STYLES: Record<ComparisonStat['winner'], { ferrari: string; lambo: string }> = {
  ferrari: {
    ferrari: 'text-ferrari-red font-bold',
    lambo: 'text-gray-500',
  },
  lamborghini: {
    ferrari: 'text-gray-500',
    lambo: 'text-lambo-yellow font-bold',
  },
  tie: {
    ferrari: 'text-gray-700 font-medium',
    lambo: 'text-gray-700 font-medium',
  },
};

/**
 * Side-by-side stat comparison panel.
 *
 * - Highlights the winning value per stat in the brand's colour token
 *   (`ferrari-red` for Ferrari, `lambo-yellow` for Lamborghini).
 * - Renders an empty-state prompt when either car slot is empty.
 */
export function ComparisonView({ ferrari, lamborghini, stats }: ComparisonViewProps) {
  // Empty state — neither or only one car selected
  if (!ferrari || !lamborghini) {
    return (
      <section
        aria-label="Comparison panel"
        className="mt-8 p-6 bg-white rounded-lg shadow-sm border border-gray-200 text-center"
      >
        <p className="text-gray-400 text-sm">
          {!ferrari && !lamborghini
            ? 'Select a Ferrari and a Lamborghini to compare their stats.'
            : !ferrari
            ? 'Select a Ferrari to complete the comparison.'
            : 'Select a Lamborghini to complete the comparison.'}
        </p>
      </section>
    );
  }

  return (
    <section aria-label="Head-to-head comparison" className="mt-8">
      {/* Brand header row */}
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-4 mb-4">
        <div className="text-center">
          <span className="inline-block px-3 py-1 rounded-full bg-ferrari-red text-white text-xs font-semibold uppercase tracking-wide">
            Ferrari
          </span>
          <p className="mt-1 font-bold text-gray-900 text-sm">
            {ferrari.model} ({ferrari.year})
          </p>
          <p className="text-xs text-gray-500">{ferrari.specs.engineConfig}</p>
        </div>

        <div className="text-center text-gray-400 text-xs font-medium uppercase tracking-wider">
          vs
        </div>

        <div className="text-center">
          <span className="inline-block px-3 py-1 rounded-full bg-lambo-yellow text-gray-900 text-xs font-semibold uppercase tracking-wide">
            Lamborghini
          </span>
          <p className="mt-1 font-bold text-gray-900 text-sm">
            {lamborghini.model} ({lamborghini.year})
          </p>
          <p className="text-xs text-gray-500">{lamborghini.specs.engineConfig}</p>
        </div>
      </div>

      {/* Stat rows */}
      <div className="bg-white rounded-lg shadow-sm border border-gray-200 overflow-hidden">
        <table className="w-full text-sm" aria-label="Specification comparison">
          <thead className="sr-only">
            <tr>
              <th scope="col">Ferrari value</th>
              <th scope="col">Stat</th>
              <th scope="col">Lamborghini value</th>
            </tr>
          </thead>
          <tbody>
            {stats.map((stat, idx) => {
              const styles = WINNER_STYLES[stat.winner];
              return (
                <tr
                  key={stat.label}
                  className={idx % 2 === 0 ? 'bg-white' : 'bg-gray-50'}
                  data-winner={stat.winner}
                >
                  <td className={`py-3 px-4 text-right tabular-nums ${styles.ferrari}`}>
                    {stat.ferrariValue}
                  </td>
                  <td className="py-3 px-2 text-center text-xs font-medium text-gray-500 whitespace-nowrap">
                    {stat.label}
                  </td>
                  <td className={`py-3 px-4 text-left tabular-nums ${styles.lambo}`}>
                    {stat.lamboValue}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Winner badge */}
      {stats.length > 0 && (
        <div className="mt-4 text-center text-xs text-gray-500">
          {(() => {
            const ferrariWins = stats.filter((s) => s.winner === 'ferrari').length;
            const lamboWins = stats.filter((s) => s.winner === 'lamborghini').length;
            if (ferrariWins > lamboWins) {
              return (
                <span className="text-ferrari-red font-semibold">
                  Ferrari leads {ferrariWins}–{lamboWins}
                </span>
              );
            } else if (lamboWins > ferrariWins) {
              return (
                <span className="text-lambo-yellow font-semibold">
                  Lamborghini leads {lamboWins}–{ferrariWins}
                </span>
              );
            }
            return <span className="text-gray-600 font-medium">It's a tie!</span>;
          })()}
        </div>
      )}
    </section>
  );
}
