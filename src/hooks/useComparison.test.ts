import { describe, it, expect } from 'vitest';
import { renderHook, act } from '@testing-library/react';
import { useComparison } from './useComparison';
import type { CarModel } from '../types';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeCar(overrides: Partial<CarModel> & Pick<CarModel, 'id' | 'brand' | 'model' | 'year' | 'specs'>): CarModel {
  return {
    decade: Math.floor(overrides.year / 10) * 10,
    imageUrl: `/images/${overrides.brand}/${overrides.id}.jpg`,
    eraRivals: [],
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const ferrari = makeCar({
  id: 'ferrari-f40-1987',
  brand: 'ferrari',
  model: 'F40',
  year: 1987,
  specs: { hp: 478, torqueLbFt: 424, zeroToSixtyMs: 3.8, topSpeedMph: 201, engineConfig: 'V8 TT, 2.9L' },
});

const lambo = makeCar({
  id: 'lamborghini-countach-1987',
  brand: 'lamborghini',
  model: 'Countach LP5000 QV',
  year: 1987,
  specs: { hp: 455, torqueLbFt: 369, zeroToSixtyMs: 4.9, topSpeedMph: 183, engineConfig: 'V12, 5.2L' },
});

// A car that ties with ferrari on HP for tie testing
const lamboTie = makeCar({
  id: 'lamborghini-tie-1987',
  brand: 'lamborghini',
  model: 'TieCar',
  year: 1987,
  specs: { hp: 478, torqueLbFt: 478, zeroToSixtyMs: 3.8, topSpeedMph: 201, engineConfig: 'V12, 5.0L' },
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('useComparison', () => {
  it('starts with both selections null and empty winners', () => {
    const { result } = renderHook(() => useComparison());
    expect(result.current.selectedFerrari).toBeNull();
    expect(result.current.selectedLambo).toBeNull();
    expect(result.current.winners).toHaveLength(0);
  });

  it('exposes selectedFerrari after setSelectedFerrari is called', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrari);
    });
    expect(result.current.selectedFerrari).toBe(ferrari);
    expect(result.current.selectedLambo).toBeNull();
    // winners still empty because lambo not selected
    expect(result.current.winners).toHaveLength(0);
  });

  it('exposes selectedLambo after setSelectedLambo is called', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedLambo(lambo);
    });
    expect(result.current.selectedLambo).toBe(lambo);
    expect(result.current.selectedFerrari).toBeNull();
    expect(result.current.winners).toHaveLength(0);
  });

  it('computes winners when both cars are selected', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrari);
      result.current.setSelectedLambo(lambo);
    });

    const { winners } = result.current;
    expect(winners).toHaveLength(4);

    // HP: ferrari 478 > lambo 455 → ferrari wins
    const hp = winners.find((s) => s.label === 'Horsepower');
    expect(hp?.winner).toBe('ferrari');
    expect(hp?.ferrariValue).toBe(478);
    expect(hp?.lamboValue).toBe(455);

    // Torque: ferrari 424 > lambo 369 → ferrari wins
    const torque = winners.find((s) => s.label === 'Torque (lb-ft)');
    expect(torque?.winner).toBe('ferrari');

    // 0-60: ferrari 3.8 < lambo 4.9 → ferrari wins (lower is better)
    const sprint = winners.find((s) => s.label === '0–60 mph (s)');
    expect(sprint?.winner).toBe('ferrari');

    // Top speed: ferrari 201 > lambo 183 → ferrari wins
    const topSpeed = winners.find((s) => s.label === 'Top Speed (mph)');
    expect(topSpeed?.winner).toBe('ferrari');
  });

  it('identifies lamborghini as winner when it has better stats', () => {
    // Give lambo a bigger engine, more HP, and slower F40
    const slowFerrari = makeCar({
      id: 'ferrari-slow-1987',
      brand: 'ferrari',
      model: 'SlowFerrari',
      year: 1987,
      specs: { hp: 300, torqueLbFt: 250, zeroToSixtyMs: 6.0, topSpeedMph: 150, engineConfig: 'V8, 3.0L' },
    });

    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(slowFerrari);
      result.current.setSelectedLambo(lambo);
    });

    const hp = result.current.winners.find((s) => s.label === 'Horsepower');
    expect(hp?.winner).toBe('lamborghini');
  });

  it('records "tie" when both values are equal', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrari);
      result.current.setSelectedLambo(lamboTie);
    });

    const hp = result.current.winners.find((s) => s.label === 'Horsepower');
    expect(hp?.winner).toBe('tie');

    const sprint = result.current.winners.find((s) => s.label === '0–60 mph (s)');
    expect(sprint?.winner).toBe('tie');
  });

  it('clears selection when null is passed', () => {
    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrari);
      result.current.setSelectedLambo(lambo);
    });
    expect(result.current.winners).toHaveLength(4);

    act(() => {
      result.current.setSelectedFerrari(null);
    });
    expect(result.current.selectedFerrari).toBeNull();
    expect(result.current.winners).toHaveLength(0);
  });

  it('replaces the existing selection when a new car is set', () => {
    const ferrari2 = makeCar({
      id: 'ferrari-enzo-2002',
      brand: 'ferrari',
      model: 'Enzo',
      year: 2002,
      specs: { hp: 651, torqueLbFt: 485, zeroToSixtyMs: 3.1, topSpeedMph: 218, engineConfig: 'V12, 6.0L' },
    });

    const { result } = renderHook(() => useComparison());
    act(() => {
      result.current.setSelectedFerrari(ferrari);
    });
    expect(result.current.selectedFerrari?.id).toBe('ferrari-f40-1987');

    act(() => {
      result.current.setSelectedFerrari(ferrari2);
    });
    expect(result.current.selectedFerrari?.id).toBe('ferrari-enzo-2002');
  });
});
