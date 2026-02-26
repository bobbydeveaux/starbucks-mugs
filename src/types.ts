/**
 * TypeScript type definitions for the Costa vs Starbucks comparison app.
 * Matches the data model defined in docs/concepts/costa-vs-starbucks/HLD.md.
 */

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
// TripWire CyberSecurity Tool — types
// ---------------------------------------------------------------------------

/** Tripwire sensor type that triggered the alert */
export type TripwireType = 'FILE' | 'NETWORK' | 'PROCESS';

/** Alert severity level */
export type Severity = 'INFO' | 'WARN' | 'CRITICAL';

/** Agent connection status as reported by the dashboard */
export type HostStatus = 'ONLINE' | 'OFFLINE' | 'DEGRADED';

/** Current state of a managed WebSocket connection */
export type WebSocketReadyState = 'CONNECTING' | 'OPEN' | 'CLOSING' | 'CLOSED';

/**
 * A single security alert pushed from the TripWire dashboard via WebSocket or
 * retrieved via the REST `/api/v1/alerts` endpoint.
 */
export interface TripwireAlert {
  /** UUID primary key */
  alert_id: string;
  /** UUID of the host that generated this alert */
  host_id: string;
  /** Human-readable hostname, e.g. "web-01" */
  hostname: string;
  /** ISO 8601 event occurrence timestamp (agent clock) */
  timestamp: string;
  /** Sensor type that triggered the alert */
  tripwire_type: TripwireType;
  /** Name of the rule that matched */
  rule_name: string;
  /** Alert severity */
  severity: Severity;
  /** Optional flexible payload: path, pid, port, user, etc. */
  event_detail?: Record<string, unknown>;
}

/**
 * Host inventory entry returned by `/api/v1/hosts`.
 */
export interface TripwireHost {
  host_id: string;
  hostname: string;
  ip_address: string;
  platform: string;
  agent_version: string;
  /** ISO 8601 timestamp of the last gRPC heartbeat */
  last_seen: string;
  status: HostStatus;
}

/**
 * Top-level JSON envelope pushed to browser WebSocket clients when a new
 * alert is ingested.  `type` is always `"alert"`.
 */
export interface WsAlertMessage {
  type: 'alert';
  data: TripwireAlert;
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

// ---------------------------------------------------------------------------
// TripWire Cybersecurity Tool — Host model
// ---------------------------------------------------------------------------

/**
 * A registered agent host as returned by `GET /api/v1/hosts`.
 * Maps to the `storage.Host` struct in the Go backend.
 */
export interface Host {
  /** Stable UUID assigned on first registration. Preserved across reconnects. */
  host_id: string;
  /** Agent hostname (derived from mTLS certificate CN when available). */
  hostname: string;
  /** Primary IP address of the agent, may be empty. */
  ip_address?: string;
  /** Operating system / platform string reported by the agent. */
  platform?: string;
  /** Agent binary version string. */
  agent_version?: string;
  /** ISO 8601 timestamp of the most recent heartbeat. May be absent for newly registered hosts. */
  last_seen?: string;
  /** Current liveness state of the host. */
  status: HostStatus;
}
