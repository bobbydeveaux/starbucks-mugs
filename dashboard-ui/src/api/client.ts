/**
 * TripWire Dashboard API Client
 *
 * Handles bearer token storage, Authorization header attachment,
 * and typed fetch helpers for all REST endpoints.
 */

import type {
  Alert,
  AlertsQueryParams,
  AuditEntry,
  AuditQueryParams,
  HealthResponse,
  Host,
} from './types';

// ---------------------------------------------------------------------------
// Token storage
// ---------------------------------------------------------------------------

const TOKEN_STORAGE_KEY = 'tripwire_access_token';

/** Store the bearer token (in-memory + localStorage for session persistence). */
export function setToken(token: string): void {
  localStorage.setItem(TOKEN_STORAGE_KEY, token);
}

/** Retrieve the stored bearer token, or null if absent. */
export function getToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY);
}

/** Remove the stored bearer token (logout). */
export function clearToken(): void {
  localStorage.removeItem(TOKEN_STORAGE_KEY);
}

/** Returns true when a token is currently stored. */
export function isAuthenticated(): boolean {
  return getToken() !== null;
}

// ---------------------------------------------------------------------------
// Core fetch helper
// ---------------------------------------------------------------------------

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '';

export class ApiResponseError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: string,
  ) {
    super(`API error ${status}: ${body}`);
    this.name = 'ApiResponseError';
  }
}

async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const token = getToken();

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string>),
  };

  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    const body = await response.text();
    throw new ApiResponseError(response.status, body);
  }

  // 204 No Content or empty body
  const text = await response.text();
  if (!text) return undefined as T;

  return JSON.parse(text) as T;
}

// ---------------------------------------------------------------------------
// Typed endpoint helpers
// ---------------------------------------------------------------------------

/** GET /healthz — no auth required. */
export async function getHealth(): Promise<HealthResponse> {
  return apiFetch<HealthResponse>('/healthz');
}

/**
 * GET /api/v1/alerts — returns paginated alert list.
 * Requires bearer token.
 */
export async function getAlerts(params: AlertsQueryParams): Promise<Alert[]> {
  const query = buildQuery(params as unknown as Record<string, unknown>);
  return apiFetch<Alert[]>(`/api/v1/alerts?${query}`);
}

/**
 * GET /api/v1/hosts — returns all registered hosts.
 * Requires bearer token.
 */
export async function getHosts(): Promise<Host[]> {
  return apiFetch<Host[]>('/api/v1/hosts');
}

/**
 * GET /api/v1/audit — returns tamper-evident audit log entries.
 * Requires bearer token.
 */
export async function getAudit(params: AuditQueryParams): Promise<AuditEntry[]> {
  const query = buildQuery(params as unknown as Record<string, unknown>);
  return apiFetch<AuditEntry[]>(`/api/v1/audit?${query}`);
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function buildQuery(params: Record<string, unknown>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null) {
      search.set(key, String(value));
    }
  }
  return search.toString();
}
