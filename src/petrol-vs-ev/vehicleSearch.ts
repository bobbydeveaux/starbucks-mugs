/**
 * Vehicle search business logic for the Petrol vs EV Cost Comparison Website.
 *
 * This module contains pure, stateless functions for:
 *  - Parsing and validating raw query-string parameters
 *  - Building parameterised SQL (no string interpolation — safe against injection)
 *  - Mapping raw DB rows to typed Vehicle objects
 *  - Shaping the final API response
 *
 * It has no external runtime dependencies so it can be unit-tested in isolation
 * without a database connection.  The Vercel handler in api/vehicles.ts imports
 * these functions and wires in the real postgres client.
 */

import type { FuelType, Vehicle, VehicleSearchParams, VehiclesResponse } from '../types/vehicle';
import {
  DEFAULT_VEHICLE_LIMIT,
  MAX_VEHICLE_LIMIT,
  VALID_FUEL_TYPES,
} from '../types/vehicle';

// ---------------------------------------------------------------------------
// Parsed parameter type (internal, after validation)
// ---------------------------------------------------------------------------

/** Validated and normalised query parameters ready to be passed to buildVehicleQuery. */
export interface ParsedSearchParams {
  make: string | undefined;
  model: string | undefined;
  year: number | undefined;
  fuel_type: FuelType | undefined;
  q: string | undefined;
  /** Always a positive integer ≤ MAX_VEHICLE_LIMIT after parsing. */
  limit: number;
}

// ---------------------------------------------------------------------------
// Parse result discriminated union
// ---------------------------------------------------------------------------

export type ParseResult<T> =
  | { success: true; data: T }
  | { success: false; error: string };

// ---------------------------------------------------------------------------
// Parameter parsing
// ---------------------------------------------------------------------------

/**
 * Parses and validates raw query-string parameters from an incoming request.
 *
 * Accepts the `query` object from a Vercel/Express-style request where values
 * may be strings, string arrays (duplicate keys), or undefined.
 *
 * Returns `{ success: true, data }` on success or `{ success: false, error }`
 * with a human-readable message suitable for a 400 response body.
 */
export function parseSearchParams(
  query: Record<string, string | string[] | undefined>,
): ParseResult<ParsedSearchParams> {
  // make: optional string, max 100 chars
  const rawMake = typeof query.make === 'string' ? query.make.trim() : undefined;
  if (rawMake !== undefined && rawMake.length > 100) {
    return { success: false, error: 'make must be 100 characters or fewer' };
  }

  // model: optional string, max 100 chars
  const rawModel = typeof query.model === 'string' ? query.model.trim() : undefined;
  if (rawModel !== undefined && rawModel.length > 100) {
    return { success: false, error: 'model must be 100 characters or fewer' };
  }

  // year: optional integer 1900–2100
  let year: number | undefined;
  if (query.year !== undefined) {
    if (typeof query.year !== 'string') {
      return { success: false, error: 'year must be a single value' };
    }
    const parsed = parseInt(query.year, 10);
    if (isNaN(parsed) || String(parsed) !== query.year.trim()) {
      return { success: false, error: 'year must be an integer' };
    }
    if (parsed < 1900 || parsed > 2100) {
      return { success: false, error: 'year must be between 1900 and 2100' };
    }
    year = parsed;
  }

  // fuel_type: optional enum
  let fuel_type: FuelType | undefined;
  if (query.fuel_type !== undefined) {
    if (typeof query.fuel_type !== 'string') {
      return { success: false, error: 'fuel_type must be a single value' };
    }
    if (!(VALID_FUEL_TYPES as readonly string[]).includes(query.fuel_type)) {
      return {
        success: false,
        error: `fuel_type must be one of: ${VALID_FUEL_TYPES.join(', ')}`,
      };
    }
    fuel_type = query.fuel_type as FuelType;
  }

  // q: optional freetext, max 200 chars
  const rawQ = typeof query.q === 'string' ? query.q.trim() : undefined;
  if (rawQ !== undefined && rawQ.length > 200) {
    return { success: false, error: 'q must be 200 characters or fewer' };
  }

  // limit: optional integer, default DEFAULT_VEHICLE_LIMIT, max MAX_VEHICLE_LIMIT
  let limit = DEFAULT_VEHICLE_LIMIT;
  if (query.limit !== undefined) {
    if (typeof query.limit !== 'string') {
      return { success: false, error: 'limit must be a single value' };
    }
    const parsed = parseInt(query.limit, 10);
    if (isNaN(parsed) || parsed < 1) {
      return { success: false, error: 'limit must be a positive integer' };
    }
    limit = Math.min(parsed, MAX_VEHICLE_LIMIT);
  }

  return {
    success: true,
    data: {
      make: rawMake || undefined,
      model: rawModel || undefined,
      year,
      fuel_type,
      q: rawQ || undefined,
      limit,
    },
  };
}

// ---------------------------------------------------------------------------
// SQL building
// ---------------------------------------------------------------------------

/**
 * Result of buildVehicleQuery: SQL strings plus their ordered parameter values.
 *
 * Both queries share the same filter parameters (values[0..n-1]).
 * The main `sql` appends one extra parameter (limit) at the end.
 */
export interface VehicleQueryResult {
  /** Main SELECT query with $1, $2, … positional placeholders. */
  sql: string;
  /** COUNT query using the same filter parameters (no limit placeholder). */
  countSql: string;
  /** Ordered parameter values for the main query (includes limit as last element). */
  values: (string | number)[];
  /** Ordered parameter values for the count query (excludes limit). */
  countValues: (string | number)[];
}

/**
 * Builds parameterised SQL for searching the vehicles table.
 *
 * Uses positional placeholders ($1, $2, …) compatible with node-postgres and
 * the `postgres` package's `sql.unsafe()` method.  No user-supplied values are
 * interpolated into the SQL string — they are all passed as parameters.
 */
export function buildVehicleQuery(params: ParsedSearchParams): VehicleQueryResult {
  const conditions: string[] = [];
  const filterValues: (string | number)[] = [];
  let idx = 1;

  if (params.make !== undefined) {
    conditions.push(`LOWER(make) = LOWER($${idx++})`);
    filterValues.push(params.make);
  }

  if (params.model !== undefined) {
    conditions.push(`LOWER(model) = LOWER($${idx++})`);
    filterValues.push(params.model);
  }

  if (params.year !== undefined) {
    conditions.push(`year = $${idx++}`);
    filterValues.push(params.year);
  }

  if (params.fuel_type !== undefined) {
    conditions.push(`fuel_type = $${idx++}`);
    filterValues.push(params.fuel_type);
  }

  if (params.q !== undefined) {
    // Single placeholder reused three times within the same expression
    const placeholder = `$${idx++}`;
    conditions.push(
      `(LOWER(make) LIKE LOWER(${placeholder}) OR LOWER(model) LIKE LOWER(${placeholder}) OR LOWER(COALESCE(variant, '')) LIKE LOWER(${placeholder}))`,
    );
    filterValues.push(`%${params.q}%`);
  }

  const whereClause =
    conditions.length > 0 ? `WHERE ${conditions.join(' AND ')}` : '';

  const countSql = `SELECT COUNT(*)::integer AS total FROM vehicles ${whereClause}`.trim();

  const sql = `
SELECT
  id, make, model, year, variant, fuel_type,
  mpg_combined, mpg_city, mpg_motorway,
  efficiency_mpkwh, battery_kwh, wltp_range_mi, co2_gkm
FROM vehicles
${whereClause}
ORDER BY make, model, year
LIMIT $${idx}
`.trim();

  return {
    sql,
    countSql,
    values: [...filterValues, params.limit],
    countValues: filterValues,
  };
}

// ---------------------------------------------------------------------------
// Row mapping
// ---------------------------------------------------------------------------

/**
 * Maps a raw database row (plain object with unknown-typed fields) to a typed
 * Vehicle object.  Numeric columns returned as strings by some postgres drivers
 * are coerced with Number().
 */
export function mapDbRowToVehicle(row: Record<string, unknown>): Vehicle {
  return {
    id: row.id as string,
    make: row.make as string,
    model: row.model as string,
    year: Number(row.year),
    variant: (row.variant as string | null | undefined) ?? null,
    fuel_type: row.fuel_type as FuelType,
    mpg_combined: row.mpg_combined != null ? Number(row.mpg_combined) : null,
    mpg_city: row.mpg_city != null ? Number(row.mpg_city) : null,
    mpg_motorway: row.mpg_motorway != null ? Number(row.mpg_motorway) : null,
    efficiency_mpkwh:
      row.efficiency_mpkwh != null ? Number(row.efficiency_mpkwh) : null,
    battery_kwh: row.battery_kwh != null ? Number(row.battery_kwh) : null,
    wltp_range_mi: row.wltp_range_mi != null ? Number(row.wltp_range_mi) : null,
    co2_gkm: row.co2_gkm != null ? Number(row.co2_gkm) : null,
  };
}

// ---------------------------------------------------------------------------
// Response shaping
// ---------------------------------------------------------------------------

/**
 * Shapes raw query results into a VehiclesResponse suitable for JSON serialisation.
 *
 * @param rows  - Raw DB rows from the main SELECT query.
 * @param total - Total match count from the COUNT query.
 */
export function shapeVehiclesResponse(
  rows: Record<string, unknown>[],
  total: number,
): VehiclesResponse {
  return {
    vehicles: rows.map(mapDbRowToVehicle),
    total,
  };
}

// Re-export types needed by the Vercel handler
export type { VehicleSearchParams, VehiclesResponse };
