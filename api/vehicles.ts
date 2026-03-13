/**
 * GET /api/vehicles — Vehicle Search API
 *
 * Serverless handler for the Petrol vs EV Cost Comparison Website.
 * Supports filtering by make, model, year, fuel_type, and freetext (q).
 * All user input is passed via parameterised SQL — no string interpolation.
 *
 * Response shape:
 *   { vehicles: VehicleRecord[], total: number }
 *
 * Response headers:
 *   Cache-Control: public, max-age=86400
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface VehicleRecord {
  id: string;
  make: string;
  model: string;
  year: number;
  variant: string | null;
  fuel_type: string;
  mpg_combined: number | null;
  mpg_city: number | null;
  mpg_motorway: number | null;
  efficiency_mpkwh: number | null;
  battery_kwh: number | null;
  wltp_range_mi: number | null;
  co2_gkm: number | null;
}

export interface VehiclesResponse {
  vehicles: VehicleRecord[];
  total: number;
}

export interface VehicleQueryParams {
  make?: string;
  model?: string;
  year?: number;
  fuel_type?: 'petrol' | 'diesel' | 'ev' | 'hybrid' | 'phev';
  q?: string;
  limit: number;
  offset: number;
}

export type ValidationError =
  | { field: string; message: string };

export type ParseResult =
  | { success: true; data: VehicleQueryParams }
  | { success: false; errors: ValidationError[] };

/** Allowed fuel_type values. */
const FUEL_TYPES = ['petrol', 'diesel', 'ev', 'hybrid', 'phev'] as const;
type FuelType = typeof FUEL_TYPES[number];

// ---------------------------------------------------------------------------
// Query-param validation
// ---------------------------------------------------------------------------

/**
 * Parses and validates raw query-string values from the incoming HTTP request.
 *
 * All user-supplied strings are validated but never interpolated into SQL.
 * The validated params are later bound via parameterised placeholders.
 */
export function parseQueryParams(
  raw: Record<string, string | string[] | undefined>,
): ParseResult {
  const errors: ValidationError[] = [];

  // Helpers -------------------------------------------------------------------

  function first(v: string | string[] | undefined): string | undefined {
    if (Array.isArray(v)) return v[0];
    return v;
  }

  function coerceInt(
    field: string,
    raw: string | string[] | undefined,
    min: number,
    max: number,
    defaultValue?: number,
  ): number | undefined {
    const s = first(raw);
    if (s === undefined || s === '') return defaultValue;
    const n = Number(s);
    if (!Number.isInteger(n)) {
      errors.push({ field, message: `${field} must be an integer` });
      return undefined;
    }
    if (n < min || n > max) {
      errors.push({ field, message: `${field} must be between ${min} and ${max}` });
      return undefined;
    }
    return n;
  }

  // Parse each param ----------------------------------------------------------

  const make = first(raw['make'])?.trim() || undefined;
  const model = first(raw['model'])?.trim() || undefined;

  const year = coerceInt('year', raw['year'], 1900, 2100);

  const rawFuelType = first(raw['fuel_type'])?.toLowerCase();
  let fuel_type: FuelType | undefined;
  if (rawFuelType !== undefined && rawFuelType !== '') {
    if (!(FUEL_TYPES as readonly string[]).includes(rawFuelType)) {
      errors.push({
        field: 'fuel_type',
        message: `fuel_type must be one of: ${FUEL_TYPES.join(', ')}`,
      });
    } else {
      fuel_type = rawFuelType as FuelType;
    }
  }

  const rawQ = first(raw['q'])?.trim();
  let q: string | undefined;
  if (rawQ !== undefined && rawQ !== '') {
    if (rawQ.length > 200) {
      errors.push({ field: 'q', message: 'q must be ≤ 200 characters' });
    } else {
      q = rawQ;
    }
  }

  const limit = coerceInt('limit', raw['limit'], 1, 100, 20) ?? 20;
  const offset = coerceInt('offset', raw['offset'], 0, Number.MAX_SAFE_INTEGER, 0) ?? 0;

  if (errors.length > 0) return { success: false, errors };

  return {
    success: true,
    data: { make, model, year, fuel_type, q, limit, offset },
  };
}

// ---------------------------------------------------------------------------
// Parameterised query builder
// ---------------------------------------------------------------------------

export interface BuiltQuery {
  /** Paginated SELECT statement with $n placeholders. */
  sql: string;
  /** Bound values for the SELECT, in placeholder order. */
  params: (string | number)[];
  /** COUNT(*) query sharing the same WHERE clause. */
  countSql: string;
  /** Bound values for the COUNT query. */
  countParams: (string | number)[];
}

/**
 * Builds parameterised SQL for the vehicles query.
 *
 * User-supplied strings (make, model, q) are NEVER interpolated into SQL.
 * Each value is assigned a numbered placeholder ($1, $2, …) and passed as a
 * separate bound parameter. This prevents SQL injection regardless of input.
 */
export function buildVehicleQuery(params: VehicleQueryParams): BuiltQuery {
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
    // Freetext: match against make, model, or variant (case-insensitive LIKE).
    // The search term is bound as a single parameter — never interpolated.
    const placeholder = `$${idx++}`;
    conditions.push(
      `(LOWER(make) LIKE ${placeholder} OR LOWER(model) LIKE ${placeholder} OR LOWER(COALESCE(variant,'')) LIKE ${placeholder})`,
    );
    filterValues.push(`%${params.q.toLowerCase()}%`);
  }

  const where = conditions.length > 0 ? `WHERE ${conditions.join(' AND ')}` : '';

  const countSql = `SELECT COUNT(*)::int AS total FROM vehicles ${where}`.trim();
  const countParams = [...filterValues];

  const sql = [
    'SELECT id, make, model, year, variant, fuel_type,',
    '       mpg_combined, mpg_city, mpg_motorway,',
    '       efficiency_mpkwh, battery_kwh, wltp_range_mi, co2_gkm',
    'FROM vehicles',
    where,
    'ORDER BY make, model, year',
    `LIMIT $${idx++} OFFSET $${idx++}`,
  ]
    .filter(Boolean)
    .join(' ')
    .replace(/\s+/g, ' ')
    .trim();

  const selectParams: (string | number)[] = [...filterValues, params.limit, params.offset];

  return { sql, params: selectParams, countSql, countParams };
}

// ---------------------------------------------------------------------------
// Database client interface (for dependency injection / mocking in tests)
// ---------------------------------------------------------------------------

export interface DbClient {
  query<T = Record<string, unknown>>(
    sql: string,
    params: (string | number)[],
  ): Promise<{ rows: T[] }>;
}

// ---------------------------------------------------------------------------
// Core handler (framework-agnostic, injected with db for testability)
// ---------------------------------------------------------------------------

export interface HandlerResult {
  status: number;
  body: unknown;
  headers: Record<string, string>;
}

/**
 * Framework-agnostic vehicle search handler.
 *
 * @param rawParams  - Raw query-string key/value pairs from the HTTP request.
 * @param db         - Database client (real or mock).
 * @returns          - HTTP-like result object with status, body, and headers.
 */
export async function vehiclesHandler(
  rawParams: Record<string, string | string[] | undefined>,
  db: DbClient,
): Promise<HandlerResult> {
  const parsed = parseQueryParams(rawParams);
  if (!parsed.success) {
    return {
      status: 400,
      body: { error: 'Invalid query parameters', details: parsed.errors },
      headers: { 'Content-Type': 'application/json' },
    };
  }

  const { sql, params, countSql, countParams } = buildVehicleQuery(parsed.data);

  const [vehicleResult, countResult] = await Promise.all([
    db.query<VehicleRecord>(sql, params),
    db.query<{ total: number }>(countSql, countParams),
  ]);

  const total = countResult.rows[0]?.total ?? 0;

  return {
    status: 200,
    body: { vehicles: vehicleResult.rows, total } satisfies VehiclesResponse,
    headers: {
      'Content-Type': 'application/json',
      'Cache-Control': 'public, max-age=86400',
    },
  };
}
