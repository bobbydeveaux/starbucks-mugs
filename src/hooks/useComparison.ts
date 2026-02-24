import { useState, useMemo } from 'react';
import type { CarModel, ComparisonStat } from '../types';

export interface UseComparisonResult {
  selectedFerrari: CarModel | null;
  selectedLambo: CarModel | null;
  setSelectedFerrari: (car: CarModel | null) => void;
  setSelectedLambo: (car: CarModel | null) => void;
  /** Per-stat winner annotations. Empty array when fewer than two cars are selected. */
  winners: ComparisonStat[];
}

interface StatConfig {
  label: string;
  getValue: (car: CarModel) => number;
  /** true → higher value wins; false → lower value wins (e.g. 0–60 time) */
  higherWins: boolean;
}

const STAT_CONFIGS: StatConfig[] = [
  { label: 'Horsepower',      getValue: (c) => c.specs.hp,            higherWins: true  },
  { label: 'Torque (lb-ft)', getValue: (c) => c.specs.torqueLbFt,    higherWins: true  },
  { label: '0–60 mph (s)',   getValue: (c) => c.specs.zeroToSixtyMs, higherWins: false },
  { label: 'Top Speed (mph)', getValue: (c) => c.specs.topSpeedMph,   higherWins: true  },
];

function computeWinner(
  ferrariValue: number,
  lamboValue: number,
  higherWins: boolean,
): 'ferrari' | 'lamborghini' | 'tie' {
  if (ferrariValue === lamboValue) return 'tie';
  if (higherWins) {
    return ferrariValue > lamboValue ? 'ferrari' : 'lamborghini';
  }
  return ferrariValue < lamboValue ? 'ferrari' : 'lamborghini';
}

/**
 * Manages which Ferrari and Lamborghini are selected for head-to-head comparison
 * and derives a per-stat winner annotation for each numeric spec.
 */
export function useComparison(): UseComparisonResult {
  const [selectedFerrari, setSelectedFerrari] = useState<CarModel | null>(null);
  const [selectedLambo, setSelectedLambo] = useState<CarModel | null>(null);

  const winners = useMemo<ComparisonStat[]>(() => {
    if (!selectedFerrari || !selectedLambo) return [];

    return STAT_CONFIGS.map(({ label, getValue, higherWins }) => {
      const ferrariValue = getValue(selectedFerrari);
      const lamboValue = getValue(selectedLambo);
      return {
        label,
        ferrariValue,
        lamboValue,
        winner: computeWinner(ferrariValue, lamboValue, higherWins),
      };
    });
  }, [selectedFerrari, selectedLambo]);

  return { selectedFerrari, selectedLambo, setSelectedFerrari, setSelectedLambo, winners };
}
