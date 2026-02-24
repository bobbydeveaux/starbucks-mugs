import { useState, useMemo } from 'react';
import type { CarModel, ComparisonStat } from '../types';

/** Return shape of the useComparison hook */
export interface UseComparisonResult {
  /** Currently selected Ferrari, or null if none chosen */
  selectedFerrari: CarModel | null;
  /** Currently selected Lamborghini, or null if none chosen */
  selectedLambo: CarModel | null;
  /** Setter for the selected Ferrari */
  setSelectedFerrari: (car: CarModel | null) => void;
  /** Setter for the selected Lamborghini */
  setSelectedLambo: (car: CarModel | null) => void;
  /**
   * Per-stat winner annotations comparing the two selected cars.
   * Empty array when fewer than two cars are selected.
   */
  winners: ComparisonStat[];
}

/** Definition for a single numeric stat comparison */
interface StatDef {
  label: string;
  key: 'hp' | 'torqueLbFt' | 'zeroToSixtyMs' | 'topSpeedMph';
  /** If true, a higher value wins. If false (e.g. 0-60 time), a lower value wins. */
  higherWins: boolean;
}

const STAT_DEFS: StatDef[] = [
  { label: 'Horsepower', key: 'hp', higherWins: true },
  { label: 'Torque (lb-ft)', key: 'torqueLbFt', higherWins: true },
  { label: '0–60 mph (s)', key: 'zeroToSixtyMs', higherWins: false },
  { label: 'Top Speed (mph)', key: 'topSpeedMph', higherWins: true },
];

/**
 * Manages the selected Ferrari and Lamborghini for head-to-head comparison,
 * and computes per-stat winners between the two selected cars.
 *
 * @returns Selected cars, their setters, and a per-stat winners array.
 *
 * @example
 * const { selectedFerrari, setSelectedFerrari, winners } = useComparison();
 */
export function useComparison(): UseComparisonResult {
  const [selectedFerrari, setSelectedFerrari] = useState<CarModel | null>(null);
  const [selectedLambo, setSelectedLambo] = useState<CarModel | null>(null);

  const winners = useMemo<ComparisonStat[]>(() => {
    if (!selectedFerrari || !selectedLambo) {
      return [];
    }

    return STAT_DEFS.map(({ label, key, higherWins }) => {
      const ferrariValue = selectedFerrari.specs[key];
      const lamboValue = selectedLambo.specs[key];

      let winner: 'ferrari' | 'lamborghini' | 'tie';

      if (
        typeof ferrariValue !== 'number' ||
        typeof lamboValue !== 'number' ||
        ferrariValue === lamboValue
      ) {
        winner = 'tie';
      } else if (higherWins) {
        winner = ferrariValue > lamboValue ? 'ferrari' : 'lamborghini';
      } else {
        winner = ferrariValue < lamboValue ? 'ferrari' : 'lamborghini';
      }

      return { label, ferrariValue: ferrariValue ?? 0, lamboValue: lamboValue ?? 0, winner };
    });
  }, [selectedFerrari, selectedLambo]);

  return { selectedFerrari, selectedLambo, setSelectedFerrari, setSelectedLambo, winners };
}
