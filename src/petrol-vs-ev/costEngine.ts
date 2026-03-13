/**
 * CostEngine — pure TypeScript calculation functions for petrol vs EV cost comparison.
 *
 * All functions are stateless and have no side-effects, making them easy to test
 * and reuse across both client-side rendering and server-side logic.
 *
 * Unit conventions:
 *  - fuel prices: pence per litre (petrol/diesel) or pence per kWh (electricity)
 *  - distances: miles
 *  - efficiency: MPG (miles per gallon) for ICE, miles per kWh for EV
 *  - costs returned: pence (unless noted)
 *  - CO2 returned: grams per mile
 */

/** Litres in one imperial gallon (exact). */
const LITRES_PER_GALLON = 4.546;

/** UK grid average CO2 intensity used for EV tailpipe-equivalent calculation (g/kWh). */
const GRID_CO2_G_PER_KWH = 233;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface IceCostPerMileParams {
  /** Petrol or diesel price in pence per litre. */
  fuelPricePpl: number;
  /** Vehicle fuel efficiency in miles per gallon (WLTP or real-world). */
  mpg: number;
}

export interface EvCostPerMileParams {
  /** Electricity price in pence per kWh. */
  electricityPricePpkwh: number;
  /** Vehicle efficiency in miles per kWh. */
  efficiencyMilesPerKwh: number;
}

export interface AnnualCostParams {
  /** Cost per mile in pence. */
  costPerMilePence: number;
  /** Expected annual mileage. */
  annualMiles: number;
}

export interface IceCo2PerMileParams {
  /** WLTP CO2 figure in g/km as published by the manufacturer. */
  wltpCo2GPerKm: number;
}

export interface EvCo2PerMileParams {
  /** Vehicle efficiency in miles per kWh. */
  efficiencyMilesPerKwh: number;
}

export interface BreakevenParams {
  /** Upfront price premium of the EV over the ICE vehicle in pence (may be negative). */
  priceDeltaPence: number;
  /** Annual fuel/energy cost saving of the EV over the ICE vehicle in pence. */
  annualSavingsPence: number;
}

// ---------------------------------------------------------------------------
// Calculation functions
// ---------------------------------------------------------------------------

/**
 * Calculate the running cost per mile for an ICE (petrol or diesel) vehicle.
 *
 * Formula: (fuelPricePpl × LITRES_PER_GALLON) / mpg
 *
 * @returns Cost in pence per mile.
 */
export function iceCostPerMile({ fuelPricePpl, mpg }: IceCostPerMileParams): number {
  if (mpg <= 0) return Infinity;
  return (fuelPricePpl * LITRES_PER_GALLON) / mpg;
}

/**
 * Calculate the running cost per mile for an EV.
 *
 * Formula: electricityPricePpkwh / efficiencyMilesPerKwh
 *
 * @returns Cost in pence per mile.
 */
export function evCostPerMile({ electricityPricePpkwh, efficiencyMilesPerKwh }: EvCostPerMileParams): number {
  if (efficiencyMilesPerKwh <= 0) return Infinity;
  return electricityPricePpkwh / efficiencyMilesPerKwh;
}

/**
 * Calculate the annual running cost for a vehicle given a cost-per-mile and mileage.
 *
 * Formula: costPerMilePence × annualMiles
 *
 * @returns Annual cost in pence.
 */
export function annualCost({ costPerMilePence, annualMiles }: AnnualCostParams): number {
  return costPerMilePence * annualMiles;
}

/**
 * Calculate the CO2 emissions per mile for an ICE vehicle using its WLTP figure.
 *
 * Converts the manufacturer's g/km figure to g/mile (1 mile ≈ 1.60934 km).
 *
 * @returns CO2 in grams per mile.
 */
export function iceCo2PerMile({ wltpCo2GPerKm }: IceCo2PerMileParams): number {
  return wltpCo2GPerKm * 1.60934;
}

/**
 * Calculate the equivalent CO2 emissions per mile for an EV using the UK grid average.
 *
 * Formula: GRID_CO2_G_PER_KWH / efficiencyMilesPerKwh
 *
 * @returns CO2 in grams per mile.
 */
export function evCo2PerMile({ efficiencyMilesPerKwh }: EvCo2PerMileParams): number {
  if (efficiencyMilesPerKwh <= 0) return Infinity;
  return GRID_CO2_G_PER_KWH / efficiencyMilesPerKwh;
}

/**
 * Calculate the breakeven point (in years) at which an EV recoups its price premium
 * through lower running costs.
 *
 * Returns `Infinity` when annualSavingsPence ≤ 0 (the EV never pays back).
 *
 * Formula: priceDeltaPence / annualSavingsPence
 *
 * @returns Years to breakeven, or Infinity if savings are zero or negative.
 */
export function breakevenYears({ priceDeltaPence, annualSavingsPence }: BreakevenParams): number {
  if (annualSavingsPence <= 0) return Infinity;
  return priceDeltaPence / annualSavingsPence;
}
