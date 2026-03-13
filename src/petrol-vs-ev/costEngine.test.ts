import { describe, it, expect } from 'vitest';
import {
  iceCostPerMile,
  evCostPerMile,
  annualCost,
  iceCo2PerMile,
  evCo2PerMile,
  breakevenYears,
} from './costEngine';

// ---------------------------------------------------------------------------
// Constants mirrored from the implementation for use in assertions
// ---------------------------------------------------------------------------

const LITRES_PER_GALLON = 4.546;
const GRID_CO2_G_PER_KWH = 233;
const KM_PER_MILE = 1.60934;

// ---------------------------------------------------------------------------
// iceCostPerMile
// ---------------------------------------------------------------------------

describe('iceCostPerMile', () => {
  it('returns correct pence-per-mile for typical petrol car', () => {
    // 150 ppl, 40 MPG → (150 × 4.546) / 40 = 17.0475 p/mile
    const result = iceCostPerMile({ fuelPricePpl: 150, mpg: 40 });
    expect(result).toBeCloseTo((150 * LITRES_PER_GALLON) / 40, 5);
  });

  it('returns correct pence-per-mile for diesel car with high MPG', () => {
    // 160 ppl, 60 MPG → (160 × 4.546) / 60 ≈ 12.123 p/mile
    const result = iceCostPerMile({ fuelPricePpl: 160, mpg: 60 });
    expect(result).toBeCloseTo((160 * LITRES_PER_GALLON) / 60, 5);
  });

  it('returns correct result when MPG is 1 (extreme inefficiency)', () => {
    const result = iceCostPerMile({ fuelPricePpl: 100, mpg: 1 });
    expect(result).toBeCloseTo(100 * LITRES_PER_GALLON, 5);
  });

  it('scales linearly with fuel price', () => {
    const low = iceCostPerMile({ fuelPricePpl: 100, mpg: 40 });
    const high = iceCostPerMile({ fuelPricePpl: 200, mpg: 40 });
    expect(high).toBeCloseTo(low * 2, 5);
  });

  it('scales inversely with MPG', () => {
    const low = iceCostPerMile({ fuelPricePpl: 150, mpg: 30 });
    const high = iceCostPerMile({ fuelPricePpl: 150, mpg: 60 });
    expect(high).toBeCloseTo(low / 2, 5);
  });

  it('returns Infinity when MPG is zero', () => {
    expect(iceCostPerMile({ fuelPricePpl: 150, mpg: 0 })).toBe(Infinity);
  });

  it('returns Infinity when MPG is negative', () => {
    expect(iceCostPerMile({ fuelPricePpl: 150, mpg: -10 })).toBe(Infinity);
  });

  it('returns 0 when fuel price is zero', () => {
    expect(iceCostPerMile({ fuelPricePpl: 0, mpg: 40 })).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// evCostPerMile
// ---------------------------------------------------------------------------

describe('evCostPerMile', () => {
  it('returns correct pence-per-mile for typical EV', () => {
    // 28 ppkWh, 4 miles/kWh → 28 / 4 = 7 p/mile
    const result = evCostPerMile({ electricityPricePpkwh: 28, efficiencyMilesPerKwh: 4 });
    expect(result).toBeCloseTo(7, 5);
  });

  it('returns correct result for public charger tariff', () => {
    // 65 ppkWh, 3.5 miles/kWh → 65 / 3.5 ≈ 18.571 p/mile
    const result = evCostPerMile({ electricityPricePpkwh: 65, efficiencyMilesPerKwh: 3.5 });
    expect(result).toBeCloseTo(65 / 3.5, 5);
  });

  it('scales linearly with electricity price', () => {
    const low = evCostPerMile({ electricityPricePpkwh: 20, efficiencyMilesPerKwh: 4 });
    const high = evCostPerMile({ electricityPricePpkwh: 40, efficiencyMilesPerKwh: 4 });
    expect(high).toBeCloseTo(low * 2, 5);
  });

  it('scales inversely with efficiency', () => {
    const low = evCostPerMile({ electricityPricePpkwh: 28, efficiencyMilesPerKwh: 3 });
    const high = evCostPerMile({ electricityPricePpkwh: 28, efficiencyMilesPerKwh: 6 });
    expect(high).toBeCloseTo(low / 2, 5);
  });

  it('returns Infinity when efficiency is zero', () => {
    expect(evCostPerMile({ electricityPricePpkwh: 28, efficiencyMilesPerKwh: 0 })).toBe(Infinity);
  });

  it('returns Infinity when efficiency is negative', () => {
    expect(evCostPerMile({ electricityPricePpkwh: 28, efficiencyMilesPerKwh: -4 })).toBe(Infinity);
  });

  it('returns 0 when electricity price is zero', () => {
    expect(evCostPerMile({ electricityPricePpkwh: 0, efficiencyMilesPerKwh: 4 })).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// annualCost
// ---------------------------------------------------------------------------

describe('annualCost', () => {
  it('returns correct annual cost for typical ICE vehicle', () => {
    // 17 p/mile × 10000 miles = 170000 pence (£1700)
    expect(annualCost({ costPerMilePence: 17, annualMiles: 10000 })).toBe(170000);
  });

  it('returns correct annual cost for typical EV', () => {
    // 7 p/mile × 10000 miles = 70000 pence (£700)
    expect(annualCost({ costPerMilePence: 7, annualMiles: 10000 })).toBe(70000);
  });

  it('returns 0 for zero annual miles', () => {
    expect(annualCost({ costPerMilePence: 17, annualMiles: 0 })).toBe(0);
  });

  it('returns 0 for zero cost per mile', () => {
    expect(annualCost({ costPerMilePence: 0, annualMiles: 10000 })).toBe(0);
  });

  it('scales linearly with annual miles', () => {
    const low = annualCost({ costPerMilePence: 17, annualMiles: 5000 });
    const high = annualCost({ costPerMilePence: 17, annualMiles: 10000 });
    expect(high).toBe(low * 2);
  });

  it('scales linearly with cost per mile', () => {
    const low = annualCost({ costPerMilePence: 10, annualMiles: 10000 });
    const high = annualCost({ costPerMilePence: 20, annualMiles: 10000 });
    expect(high).toBe(low * 2);
  });

  it('propagates Infinity cost per mile to annual cost', () => {
    expect(annualCost({ costPerMilePence: Infinity, annualMiles: 10000 })).toBe(Infinity);
  });
});

// ---------------------------------------------------------------------------
// iceCo2PerMile
// ---------------------------------------------------------------------------

describe('iceCo2PerMile', () => {
  it('converts WLTP g/km to g/mile for a typical petrol car', () => {
    // 120 g/km → 120 × 1.60934 ≈ 193.12 g/mile
    const result = iceCo2PerMile({ wltpCo2GPerKm: 120 });
    expect(result).toBeCloseTo(120 * KM_PER_MILE, 3);
  });

  it('converts WLTP g/km to g/mile for a low-emission petrol hybrid', () => {
    // 70 g/km → 70 × 1.60934 ≈ 112.65 g/mile
    const result = iceCo2PerMile({ wltpCo2GPerKm: 70 });
    expect(result).toBeCloseTo(70 * KM_PER_MILE, 3);
  });

  it('converts WLTP g/km to g/mile for a high-emission vehicle', () => {
    // 250 g/km → 250 × 1.60934 ≈ 402.34 g/mile
    const result = iceCo2PerMile({ wltpCo2GPerKm: 250 });
    expect(result).toBeCloseTo(250 * KM_PER_MILE, 3);
  });

  it('returns 0 for a zero-emission ICE (theoretical)', () => {
    expect(iceCo2PerMile({ wltpCo2GPerKm: 0 })).toBe(0);
  });

  it('scales linearly with WLTP figure', () => {
    const low = iceCo2PerMile({ wltpCo2GPerKm: 100 });
    const high = iceCo2PerMile({ wltpCo2GPerKm: 200 });
    expect(high).toBeCloseTo(low * 2, 5);
  });
});

// ---------------------------------------------------------------------------
// evCo2PerMile
// ---------------------------------------------------------------------------

describe('evCo2PerMile', () => {
  it('returns correct g/mile for typical EV using grid average', () => {
    // 233 g/kWh ÷ 4 miles/kWh = 58.25 g/mile
    const result = evCo2PerMile({ efficiencyMilesPerKwh: 4 });
    expect(result).toBeCloseTo(GRID_CO2_G_PER_KWH / 4, 5);
  });

  it('returns correct g/mile for efficient EV', () => {
    // 233 g/kWh ÷ 5 miles/kWh = 46.6 g/mile
    const result = evCo2PerMile({ efficiencyMilesPerKwh: 5 });
    expect(result).toBeCloseTo(GRID_CO2_G_PER_KWH / 5, 5);
  });

  it('returns correct g/mile for less efficient EV', () => {
    // 233 g/kWh ÷ 2.5 miles/kWh = 93.2 g/mile
    const result = evCo2PerMile({ efficiencyMilesPerKwh: 2.5 });
    expect(result).toBeCloseTo(GRID_CO2_G_PER_KWH / 2.5, 5);
  });

  it('scales inversely with efficiency', () => {
    const low = evCo2PerMile({ efficiencyMilesPerKwh: 3 });
    const high = evCo2PerMile({ efficiencyMilesPerKwh: 6 });
    expect(high).toBeCloseTo(low / 2, 5);
  });

  it('returns Infinity when efficiency is zero', () => {
    expect(evCo2PerMile({ efficiencyMilesPerKwh: 0 })).toBe(Infinity);
  });

  it('returns Infinity when efficiency is negative', () => {
    expect(evCo2PerMile({ efficiencyMilesPerKwh: -3 })).toBe(Infinity);
  });
});

// ---------------------------------------------------------------------------
// breakevenYears
// ---------------------------------------------------------------------------

describe('breakevenYears', () => {
  it('returns correct breakeven for a £5000 premium with £1000/year savings', () => {
    // 500000 pence ÷ 100000 pence/year = 5 years
    const result = breakevenYears({ priceDeltaPence: 500000, annualSavingsPence: 100000 });
    expect(result).toBeCloseTo(5, 5);
  });

  it('returns correct breakeven for a £3000 premium with £750/year savings', () => {
    // 300000 pence ÷ 75000 pence/year = 4 years
    const result = breakevenYears({ priceDeltaPence: 300000, annualSavingsPence: 75000 });
    expect(result).toBeCloseTo(4, 5);
  });

  it('returns fractional years when savings do not divide evenly', () => {
    // 100000 pence ÷ 30000 pence/year ≈ 3.333 years
    const result = breakevenYears({ priceDeltaPence: 100000, annualSavingsPence: 30000 });
    expect(result).toBeCloseTo(100000 / 30000, 5);
  });

  it('returns Infinity when annual savings are zero', () => {
    expect(breakevenYears({ priceDeltaPence: 500000, annualSavingsPence: 0 })).toBe(Infinity);
  });

  it('returns Infinity when annual savings are negative (EV costs more to run)', () => {
    expect(breakevenYears({ priceDeltaPence: 500000, annualSavingsPence: -10000 })).toBe(Infinity);
  });

  it('returns negative years when EV is cheaper upfront (instant payback)', () => {
    // -£1000 delta (EV is cheaper) with savings → negative breakeven = already broken even
    const result = breakevenYears({ priceDeltaPence: -100000, annualSavingsPence: 50000 });
    expect(result).toBeCloseTo(-2, 5);
  });

  it('returns 0 when price delta is zero', () => {
    expect(breakevenYears({ priceDeltaPence: 0, annualSavingsPence: 50000 })).toBe(0);
  });

  it('scales linearly with price delta', () => {
    const low = breakevenYears({ priceDeltaPence: 200000, annualSavingsPence: 50000 });
    const high = breakevenYears({ priceDeltaPence: 400000, annualSavingsPence: 50000 });
    expect(high).toBeCloseTo(low * 2, 5);
  });

  it('scales inversely with annual savings', () => {
    const low = breakevenYears({ priceDeltaPence: 500000, annualSavingsPence: 100000 });
    const high = breakevenYears({ priceDeltaPence: 500000, annualSavingsPence: 50000 });
    expect(high).toBeCloseTo(low * 2, 5);
  });
});
