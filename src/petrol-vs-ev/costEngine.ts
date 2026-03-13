/**
 * CostEngine — pure TypeScript module for petrol vs EV cost comparison.
 *
 * All functions are stateless and side-effect free. UK conventions are used:
 *   - Fuel prices in pence per litre (ppl) or pence per kWh (ppkwh)
 *   - Consumption in MPG (miles per imperial gallon) or miles per kWh
 *   - 1 imperial gallon = 4.546 litres
 *   - UK grid carbon intensity constant: 233 g CO₂/kWh
 */

/** Litres in one UK imperial gallon. */
const LITRES_PER_GALLON = 4.546;

/** UK average grid carbon intensity in grams of CO₂ per kWh (National Grid ESO). */
export const GRID_CO2_G_PER_KWH = 233;

/**
 * Calculates the fuel cost per mile for an ICE (petrol or diesel) vehicle.
 *
 * Formula: (pricePpl × LITRES_PER_GALLON) / mpg
 *
 * @param pricePpl - Petrol/diesel price in pence per litre.
 * @param mpg - Vehicle fuel economy in miles per imperial gallon (WLTP combined).
 * @returns Cost per mile in pence.
 */
export function iceCostPerMile(pricePpl: number, mpg: number): number {
  return (pricePpl * LITRES_PER_GALLON) / mpg;
}

/**
 * Calculates the electricity cost per mile for an EV.
 *
 * Formula: pricePpkwh / efficiencyMpkwh
 *
 * @param pricePpkwh - Electricity tariff in pence per kWh.
 * @param efficiencyMpkwh - Vehicle efficiency in miles per kWh (WLTP).
 * @returns Cost per mile in pence.
 */
export function evCostPerMile(pricePpkwh: number, efficiencyMpkwh: number): number {
  return pricePpkwh / efficiencyMpkwh;
}

/**
 * Calculates the annual running cost for a vehicle.
 *
 * Formula: costPerMile × annualMiles
 *
 * @param costPerMile - Running cost per mile in pence.
 * @param annualMiles - Estimated annual mileage.
 * @returns Annual cost in pence.
 */
export function annualCost(costPerMile: number, annualMiles: number): number {
  return costPerMile * annualMiles;
}

/**
 * Calculates the CO₂ emissions per mile for an EV using the UK grid average.
 *
 * Formula: GRID_CO2_G_PER_KWH / efficiencyMpkwh
 *   where GRID_CO2_G_PER_KWH = 233 g/kWh
 *
 * ICE vehicles use their WLTP co2_gkm figure directly from the vehicle record;
 * EV emissions must be derived from grid intensity × energy consumed per mile.
 *
 * @param efficiencyMpkwh - Vehicle efficiency in miles per kWh (WLTP).
 * @returns CO₂ in grams per mile.
 */
export function evCo2PerMile(efficiencyMpkwh: number): number {
  return GRID_CO2_G_PER_KWH / efficiencyMpkwh;
}

/**
 * Calculates the breakeven point (in years) for switching from ICE to EV.
 *
 * Formula: priceDelta / annualSavings
 *
 * Returns `Infinity` when annual savings ≤ 0, meaning the EV never recovers
 * its purchase premium at current running costs.
 *
 * @param priceDelta - Upfront price difference in £ (EV purchase price − ICE purchase price).
 * @param annualSavings - Annual running-cost saving in £ (ICE annual cost − EV annual cost).
 * @returns Breakeven point in years, or `Infinity` if annual savings ≤ 0.
 */
export function breakevenYears(priceDelta: number, annualSavings: number): number {
  if (annualSavings <= 0) return Infinity;
  return priceDelta / annualSavings;
}
