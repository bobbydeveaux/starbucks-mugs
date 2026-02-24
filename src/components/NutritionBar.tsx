import { BarChart, Bar, Cell, XAxis, YAxis, ResponsiveContainer } from 'recharts';

interface NutritionBarProps {
  /** Nutritional value for the Costa drink */
  costaValue: number;
  /** Nutritional value for the Starbucks drink */
  starbucksValue: number;
  /** Optional unit label, e.g. "kcal", "g", "mg" */
  unit?: string;
}

// Brand colours matching tailwind.config.ts tokens
const COSTA_COLOR = '#6B1E1E';
const STARBUCKS_COLOR = '#00704A';

/**
 * NutritionBar renders a proportional horizontal bar chart for a single
 * nutrient using Recharts BarChart. The bar widths are scaled relative to
 * the higher of the two compared values, making it easy to compare at a glance.
 *
 * Costa (red) is shown in the top row; Starbucks (green) in the bottom row.
 */
export function NutritionBar({ costaValue, starbucksValue, unit = '' }: NutritionBarProps) {
  // Guard against division-by-zero when both values are 0
  const max = Math.max(costaValue, starbucksValue) || 1;

  const data = [
    { brand: 'Costa', value: costaValue },
    { brand: 'Starbucks', value: starbucksValue },
  ];

  return (
    <div role="img" aria-label={`Costa ${costaValue}${unit} vs Starbucks ${starbucksValue}${unit}`}>
      <ResponsiveContainer width="100%" height={52}>
        <BarChart
          data={data}
          layout="vertical"
          margin={{ top: 2, right: 4, bottom: 2, left: 0 }}
          barCategoryGap="25%"
        >
          <XAxis type="number" domain={[0, max]} hide />
          <YAxis type="category" dataKey="brand" hide width={0} />
          <Bar dataKey="value" radius={[0, 3, 3, 0]} isAnimationActive={false}>
            <Cell fill={COSTA_COLOR} />
            <Cell fill={STARBUCKS_COLOR} />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

export default NutritionBar;
