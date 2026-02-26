/**
 * TypeScript type definitions for the Costa vs Starbucks comparison app.
 * Matches the data model defined in docs/concepts/costa-vs-starbucks/HLD.md.
 */

// ---------------------------------------------------------------------------
// Tripwire Cybersecurity Dashboard types
// ---------------------------------------------------------------------------

/** Alert severity levels */
export type Severity = 'INFO' | 'WARN' | 'CRITICAL';

/** Tripwire event types */
export type TripwireType = 'FILE' | 'NETWORK' | 'PROCESS';

/** Host connectivity status */
export type HostStatus = 'ONLINE' | 'OFFLINE' | 'DEGRADED';

/** A single security alert emitted by the tripwire agent */
export interface Alert {
  /** UUID primary key */
  alert_id: string;
  /** UUID of the host that generated this alert */
  host_id: string;
  /** ISO 8601 timestamp of when the event occurred on the agent clock */
  timestamp: string;
  /** Category of tripwire that fired */
  tripwire_type: TripwireType;
  /** Name of the rule that fired */
  rule_name: string;
  /** Type-specific event metadata (file path, pid, port, etc.) */
  event_detail: Record<string, unknown>;
  /** Severity level of the alert */
  severity: Severity;
  /** ISO 8601 timestamp of when the dashboard ingested this alert */
  received_at: string;
}

/** A registered monitoring host */
export interface Host {
  host_id: string;
  hostname: string;
  ip_address: string;
  platform: string;
  agent_version: string;
  /** ISO 8601 timestamp of the last gRPC heartbeat, or null if never seen */
  last_seen: string | null;
  status: HostStatus;
}

/** Preset time-range options for the dashboard */
export type TimeRange = '1h' | '6h' | '24h' | '7d' | '30d';

/** Active filter state for the alert feed and trend chart */
export interface AlertFilters {
  /** Selected host IDs; empty array means all hosts */
  hostIds: string[];
  /** Severity filter; 'ALL' means no filter */
  severity: Severity | 'ALL';
  /** Tripwire type filter; 'ALL' means no filter */
  tripwireType: TripwireType | 'ALL';
  /** Relative time window */
  timeRange: TimeRange;
}

// ---------------------------------------------------------------------------
// Enums / discriminated union types
// ---------------------------------------------------------------------------

/** Brand enum — one value per chain supported by the app */
export type Brand = 'starbucks' | 'costa';

/** Drink category enum — matches the categories used in both chains' menus */
export type Category = 'hot' | 'iced' | 'blended' | 'tea' | 'other';

// ---------------------------------------------------------------------------
// Core data model
// ---------------------------------------------------------------------------

/** Nutritional values for a single drink */
export interface DrinkNutrition {
  calories_kcal: number;
  sugar_g: number;
  fat_g: number;
  protein_g: number;
  caffeine_mg: number;
}

/** A single drink entry from either brand's JSON file */
export interface Drink {
  /** Slug-style unique identifier, e.g. "sbux-flat-white" or "costa-flat-white". */
  id: string;
  brand: Brand;
  name: string;
  category: Category;
  /** Serving size in millilitres. */
  size_ml: number;
  /** Path to the drink image relative to the public root, e.g. "/images/sbux-flat-white.webp". */
  image?: string;
  nutrition: DrinkNutrition;
}

// ---------------------------------------------------------------------------
// JSON data envelope
// ---------------------------------------------------------------------------

/**
 * Top-level structure for each static JSON data file
 * (`public/data/starbucks.json` and `public/data/costa.json`).
 */
export interface DrinkCatalogEnvelope {
  schema_version: string;
  brand: Brand;
  /** ISO 8601 date string indicating when this data file was last updated. */
  updated: string;
  drinks: Drink[];
}

// ---------------------------------------------------------------------------
// Application state
// ---------------------------------------------------------------------------

/**
 * Tracks which drink has been selected for comparison from each brand.
 * `null` means no drink is currently selected for that brand.
 */
export interface ComparisonState {
  starbucks: Drink | null;
  costa: Drink | null;
}

/** Active filter state — category filter and free-text search query */
export interface FilterState {
  /** Selected category, or "all" to show every category. */
  category: Category | 'all';
  /** Free-text search string. Empty string means no search filter is active. */
  query: string;
}

// ---------------------------------------------------------------------------
// Ferrari vs Lamborghini — Enums / discriminated union types
// ---------------------------------------------------------------------------

/** Car brand enum — one value per manufacturer supported by the app */
export type CarBrand = 'ferrari' | 'lamborghini';

// ---------------------------------------------------------------------------
// Ferrari vs Lamborghini — Core data model
// ---------------------------------------------------------------------------

/** Performance and engineering specifications for a single car model */
export interface CarSpecs {
  /** Horsepower output, e.g. 485 */
  hp: number;
  /** Peak torque in lb-ft, e.g. 339 */
  torqueLbFt: number;
  /** 0–60 mph time in seconds, e.g. 5.2 */
  zeroToSixtyMs: number;
  /** Top speed in mph, e.g. 181 */
  topSpeedMph: number;
  /** Engine configuration string, e.g. "Flat-12, 4.9L" */
  engineConfig: string;
}

/** A single car model entry from either brand's JSON catalog */
export interface CarModel {
  /** Slug-style unique identifier, e.g. "ferrari-testarossa-1984" */
  id: string;
  brand: CarBrand;
  /** Model name, e.g. "Testarossa" */
  model: string;
  /** Model year, e.g. 1984 */
  year: number;
  /** Decade the model belongs to (year rounded down to nearest 10), e.g. 1980 */
  decade: number;
  /** Path to the car image relative to the public root, e.g. "/images/ferrari/testarossa.jpg" */
  image: string;
  /** Approximate base price in USD at time of launch (optional) */
  price?: number;
  specs: CarSpecs;
  /** IDs of close contemporaries from the opposing brand, used for era-match suggestions */
  eraRivals: string[];
}

// ---------------------------------------------------------------------------
// Ferrari vs Lamborghini — JSON data envelope
// ---------------------------------------------------------------------------

/**
 * Top-level structure for each static car catalog JSON file
 * (`public/data/ferrari.json` and `public/data/lamborghini.json`).
 */
export interface CarCatalogEnvelope {
  schema_version: string;
  brand: CarBrand;
  /** ISO 8601 date string indicating when this data file was last updated */
  updated: string;
  cars: CarModel[];
}

// ---------------------------------------------------------------------------
// Ferrari vs Lamborghini — Hook / application state
// ---------------------------------------------------------------------------

/** Filter options accepted by the useCarCatalog hook */
export interface CatalogFilters {
  /** Decade filter, e.g. 1980 narrows results to models from 1980–1989. Omit for all decades. */
  decade?: number;
  /** Case-insensitive model name search string. Omit or empty string for no search filter. */
  search?: string;
}

/**
 * Per-stat comparison result produced by the useComparison hook.
 * Annotates each numeric spec with which brand wins (or "tie").
 */
export interface ComparisonStat {
  /** Human-readable stat label, e.g. "Horsepower" */
  label: string;
  ferrariValue: number;
  lamboValue: number;
  winner: 'ferrari' | 'lamborghini' | 'tie';
}

/**
 * Tracks which car has been selected for comparison from each brand.
 * `null` means no car is currently selected for that brand.
 */
export interface CarComparisonState {
  ferrari: CarModel | null;
  lamborghini: CarModel | null;
}
