import { useState, useMemo } from 'react';
import type { CarModel, ComparisonStat } from '../types';

/** Return shape of the useComparison hook */
export interface UseComparisonResult {
  /** Currently selected Ferrari model, or null if none selected */
  selectedFerrari: CarModel | null;
  /** Currently selected Lamborghini model, or null if none selected */
  selectedLambo: CarModel | null;
  /** Setter for the selected Ferrari */
  setSelectedFerrari: (car: CarModel | null) => void;
  /** Setter for the selected Lamborghini */
  setSelectedLambo: (car: CarModel | null) => void;
  /**
   * Per-stat comparison results computed from the two selected cars.
   * Empty array when either car is not yet selected.
   */
  winners: ComparisonStat[];
}

/**
 * Determines the winner for a single numeric stat.
 * @param ferrariValue - Ferrari's value for the stat.
 * @param lamboValue   - Lamborghini's value for the stat.
 * @param lowerIsBetter - True for stats where a lower value is better (e.g. 0-60 time).
 */
function winnerFor(
  ferrariValue: number,
  lamboValue: number,
  lowerIsBetter: boolean,
): 'ferrari' | 'lamborghini' | 'tie' {
  if (ferrariValue === lamboValue) return 'tie';
  if (lowerIsBetter) {
    return ferrariValue < lamboValue ? 'ferrari' : 'lamborghini';
  }
  return ferrariValue > lamboValue ? 'ferrari' : 'lamborghini';
}

/**
 * Manages the selected Ferrari and Lamborghini models and computes a
 * per-stat winners breakdown whenever both cars are selected.
 *
 * @returns Selected cars, their setters, and an array of ComparisonStat objects.
 *
 * @example
 * const { selectedFerrari, setSelectedFerrari, winners } = useComparison();
 */
export function useComparison(): UseComparisonResult {
  const [selectedFerrari, setSelectedFerrari] = useState<CarModel | null>(null);
  const [selectedLambo, setSelectedLambo] = useState<CarModel | null>(null);

  const winners = useMemo((): ComparisonStat[] => {
    if (!selectedFerrari || !selectedLambo) return [];

    const f = selectedFerrari.specs;
    const l = selectedLambo.specs;

    return [
      {
        label: 'Horsepower',
        ferrariValue: f.hp,
        lamboValue: l.hp,
        winner: winnerFor(f.hp, l.hp, false),
      },
      {
        label: 'Torque (lb-ft)',
        ferrariValue: f.torqueLbFt,
        lamboValue: l.torqueLbFt,
        winner: winnerFor(f.torqueLbFt, l.torqueLbFt, false),
      },
      {
        label: '0–60 mph (s)',
        ferrariValue: f.zeroToSixtyMs,
        lamboValue: l.zeroToSixtyMs,
        winner: winnerFor(f.zeroToSixtyMs, l.zeroToSixtyMs, true),
      },
      {
        label: 'Top Speed (mph)',
        ferrariValue: f.topSpeedMph,
        lamboValue: l.topSpeedMph,
        winner: winnerFor(f.topSpeedMph, l.topSpeedMph, false),
      },
    ];
  }, [selectedFerrari, selectedLambo]);

  return { selectedFerrari, selectedLambo, setSelectedFerrari, setSelectedLambo, winners };
}
