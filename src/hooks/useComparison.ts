import { useState, useMemo } from 'react';
import type { CarModel, ComparisonStat, CarComparisonState } from '../types';

/** Return shape of the useComparison hook */
export interface UseComparisonResult {
  /** Currently selected Ferrari, or null if none selected */
  selectedFerrari: CarModel | null;
  /** Currently selected Lamborghini, or null if none selected */
  selectedLambo: CarModel | null;
  /** Select or replace the Ferrari slot */
  setSelectedFerrari: (car: CarModel | null) => void;
  /** Select or replace the Lamborghini slot */
  setSelectedLambo: (car: CarModel | null) => void;
  /**
   * Per-stat comparison results, computed from the currently selected cars.
   * Empty array when either slot is empty.
   */
  winners: ComparisonStat[];
}

/**
 * Determines which brand wins a given stat.
 * Higher is better for HP, torque, and top speed.
 * Lower is better for 0–60 time.
 */
function computeWinner(
  label: string,
  ferrariValue: number,
  lamboValue: number,
  higherIsBetter: boolean,
): ComparisonStat {
  let winner: ComparisonStat['winner'];

  if (ferrariValue === lamboValue) {
    winner = 'tie';
  } else if (higherIsBetter) {
    winner = ferrariValue > lamboValue ? 'ferrari' : 'lamborghini';
  } else {
    winner = ferrariValue < lamboValue ? 'ferrari' : 'lamborghini';
  }

  return { label, ferrariValue, lamboValue, winner };
}

/**
 * Manages the selected Ferrari and Lamborghini for a head-to-head comparison
 * and computes per-stat winners whenever both selections are present.
 *
 * @example
 * const { selectedFerrari, setSelectedFerrari, winners } = useComparison();
 */
export function useComparison(): UseComparisonResult {
  const [comparison, setComparison] = useState<CarComparisonState>({
    ferrari: null,
    lamborghini: null,
  });

  const setSelectedFerrari = (car: CarModel | null) =>
    setComparison((prev) => ({ ...prev, ferrari: car }));

  const setSelectedLambo = (car: CarModel | null) =>
    setComparison((prev) => ({ ...prev, lamborghini: car }));

  const winners = useMemo<ComparisonStat[]>(() => {
    const { ferrari, lamborghini } = comparison;

    if (!ferrari || !lamborghini) {
      return [];
    }

    return [
      computeWinner('Horsepower', ferrari.specs.hp, lamborghini.specs.hp, true),
      computeWinner('Torque (lb-ft)', ferrari.specs.torqueLbFt, lamborghini.specs.torqueLbFt, true),
      computeWinner('0–60 mph (s)', ferrari.specs.zeroToSixtyMs, lamborghini.specs.zeroToSixtyMs, false),
      computeWinner('Top Speed (mph)', ferrari.specs.topSpeedMph, lamborghini.specs.topSpeedMph, true),
    ];
  }, [comparison]);

  return {
    selectedFerrari: comparison.ferrari,
    selectedLambo: comparison.lamborghini,
    setSelectedFerrari,
    setSelectedLambo,
    winners,
  };
}
