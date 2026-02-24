interface NutritionBarProps {
  /** Human-readable label for this nutrient row, e.g. "Calories" */
  label: string;
  /** Starbucks drink's value for this nutrient */
  starbucksValue: number;
  /** Costa drink's value for this nutrient */
  costaValue: number;
  /** Unit string appended to the displayed value, e.g. "kcal", "g", "mg" */
  unit: string;
  /**
   * Whether a lower value is considered better (default: true).
   * When true, the brand with the lower value gets a "winner" highlight.
   * Pass false for nutrients where higher is preferable (e.g. protein).
   */
  lowerIsBetter?: boolean;
}

const BRAND_COLORS = {
  starbucks: {
    bar: 'bg-starbucks',
    winner: 'font-bold text-starbucks',
    label: 'text-starbucks',
  },
  costa: {
    bar: 'bg-costa',
    winner: 'font-bold text-costa',
    label: 'text-costa',
  },
} as const;

function computeWidthPercent(value: number, maxValue: number): number {
  if (maxValue === 0) return 0;
  return Math.round((value / maxValue) * 100);
}

function getWinner(
  starbucksValue: number,
  costaValue: number,
  lowerIsBetter: boolean,
): 'starbucks' | 'costa' | 'tie' {
  if (starbucksValue === costaValue) return 'tie';
  if (lowerIsBetter) {
    return starbucksValue < costaValue ? 'starbucks' : 'costa';
  }
  return starbucksValue > costaValue ? 'starbucks' : 'costa';
}

interface BarRowProps {
  brand: 'starbucks' | 'costa';
  value: number;
  unit: string;
  widthPercent: number;
  isWinner: boolean;
}

function BarRow({ brand, value, unit, widthPercent, isWinner }: BarRowProps) {
  const colors = BRAND_COLORS[brand];
  const brandLabel = brand === 'starbucks' ? 'Starbucks' : 'Costa';

  return (
    <div className="flex items-center gap-2">
      <span
        className={`w-20 shrink-0 text-xs text-right ${isWinner ? colors.winner : 'text-gray-600'}`}
        aria-label={`${brandLabel}: ${value} ${unit}${isWinner ? ', lower' : ''}`}
      >
        {value} {unit}
      </span>
      <div
        className="flex-1 h-4 bg-gray-100 rounded-full overflow-hidden"
        role="meter"
        aria-label={`${brandLabel} ${unit}`}
        aria-valuenow={value}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <div
          className={`h-full rounded-full transition-all duration-300 ${colors.bar}`}
          style={{ width: `${widthPercent}%` }}
        />
      </div>
      <span className={`w-20 shrink-0 text-xs ${colors.label} font-medium`}>
        {brandLabel}
      </span>
    </div>
  );
}

/**
 * NutritionBar renders a side-by-side visual bar comparison for a single
 * nutrition metric between a Starbucks and a Costa drink.
 *
 * Each bar is scaled proportionally so the higher value spans the full
 * available width. The brand with the better value is highlighted.
 */
export function NutritionBar({
  label,
  starbucksValue,
  costaValue,
  unit,
  lowerIsBetter = true,
}: NutritionBarProps) {
  const maxValue = Math.max(starbucksValue, costaValue);
  const sbuxWidth = computeWidthPercent(starbucksValue, maxValue);
  const costaWidth = computeWidthPercent(costaValue, maxValue);
  const winner = getWinner(starbucksValue, costaValue, lowerIsBetter);

  return (
    <div className="flex flex-col gap-1" data-testid="nutrition-bar">
      <span className="text-xs font-semibold text-gray-700 uppercase tracking-wide">
        {label}
      </span>
      <BarRow
        brand="starbucks"
        value={starbucksValue}
        unit={unit}
        widthPercent={sbuxWidth}
        isWinner={winner === 'starbucks'}
      />
      <BarRow
        brand="costa"
        value={costaValue}
        unit={unit}
        widthPercent={costaWidth}
        isWinner={winner === 'costa'}
      />
    </div>
  );
}

export default NutritionBar;
