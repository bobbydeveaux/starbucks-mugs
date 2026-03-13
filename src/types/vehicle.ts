/**
 * TypeScript type definitions for the Petrol vs EV vehicle catalog.
 * Matches the vehicles table defined in db/migrations/005_vehicles.up.sql
 * and the API contract documented in docs/concepts/petrol-vs-ev-cost-comparison-website/HLD.md.
 */

// ---------------------------------------------------------------------------
// Enums / constants
// ---------------------------------------------------------------------------

/** Supported fuel types matching the vehicles.fuel_type column constraint. */
export type FuelType = 'petrol' | 'diesel' | 'ev' | 'hybrid' | 'phev';

/** Allowed fuel_type values — kept in sync with the FuelType union. */
export const VALID_FUEL_TYPES: readonly FuelType[] = [
  'petrol',
  'diesel',
  'ev',
  'hybrid',
  'phev',
];

/** Default number of results returned by GET /api/vehicles when limit is omitted. */
export const DEFAULT_VEHICLE_LIMIT = 20;

/**
 * Maximum number of results allowed per request.
 * Prevents abuse while allowing reasonable bulk fetches.
 */
export const MAX_VEHICLE_LIMIT = 100;

// ---------------------------------------------------------------------------
// Core data model
// ---------------------------------------------------------------------------

/**
 * A single vehicle record from the catalog.
 * Null fields indicate data not applicable to that fuel type
 * (e.g. mpg_combined is null for pure EVs; efficiency_mpkwh is null for ICE).
 */
export interface Vehicle {
  /** UUID primary key */
  id: string;
  /** Manufacturer name, e.g. "Toyota" */
  make: string;
  /** Model name, e.g. "Corolla" */
  model: string;
  /** Model year */
  year: number;
  /** Trim / variant descriptor, e.g. "Long Range AWD" — null if not specified */
  variant: string | null;
  /** Fuel type */
  fuel_type: FuelType;
  /** Combined MPG (ICE/hybrid only; null for pure EV) */
  mpg_combined: number | null;
  /** City MPG (ICE/hybrid only; null for pure EV) */
  mpg_city: number | null;
  /** Motorway MPG (ICE/hybrid only; null for pure EV) */
  mpg_motorway: number | null;
  /** Miles per kWh efficiency (EV/PHEV only; null for pure ICE) */
  efficiency_mpkwh: number | null;
  /** Usable battery capacity in kWh (EV/PHEV only; null for pure ICE) */
  battery_kwh: number | null;
  /** WLTP range in miles (EV/PHEV only; null for pure ICE) */
  wltp_range_mi: number | null;
  /** WLTP CO2 in g/km (ICE/hybrid only; null for pure EV) */
  co2_gkm: number | null;
}

// ---------------------------------------------------------------------------
// API request / response types
// ---------------------------------------------------------------------------

/**
 * Query parameters accepted by GET /api/vehicles.
 * All fields are optional; omitted fields are not filtered on.
 */
export interface VehicleSearchParams {
  /** Filter by manufacturer name (case-insensitive exact match) */
  make?: string | undefined;
  /** Filter by model name (case-insensitive exact match) */
  model?: string | undefined;
  /** Filter by model year */
  year?: number | undefined;
  /** Filter by fuel type */
  fuel_type?: FuelType | undefined;
  /** Free-text search across make, model, and variant (case-insensitive substring) */
  q?: string | undefined;
  /** Maximum number of results to return (default: 20, max: 100) */
  limit?: number | undefined;
}

/** Response shape for GET /api/vehicles */
export interface VehiclesResponse {
  vehicles: Vehicle[];
  /** Total number of matching vehicles (before limit is applied) */
  total: number;
}
