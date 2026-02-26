/**
 * FilterContext — provides dashboard alert filter state to all consumers.
 *
 * Wraps the alert filter state and exposes individual setters so child
 * components can update filters without knowing about the full state shape.
 */

import { createContext, useContext, useState } from 'react';
import type { ReactNode } from 'react';
import { DEFAULT_ALERT_FILTERS } from '../types/alert';
import type { AlertFilterState, Severity, TripwireType } from '../types/alert';

// ---------------------------------------------------------------------------
// Context shape
// ---------------------------------------------------------------------------

export interface FilterContextValue {
  /** Current filter state */
  filters: AlertFilterState;
  /** Set the severity filter; pass undefined to clear */
  setSeverity: (severity: Severity | undefined) => void;
  /** Set the tripwire type filter; pass undefined to clear */
  setTripwireType: (type: TripwireType | undefined) => void;
  /** Set the host ID filter; pass undefined to clear */
  setHostId: (hostId: string | undefined) => void;
  /** Set the time window start; pass undefined to clear */
  setFrom: (from: string | undefined) => void;
  /** Set the time window end; pass undefined to clear */
  setTo: (to: string | undefined) => void;
  /** Set the number of alerts per page */
  setLimit: (limit: number) => void;
  /** Jump to a specific pagination offset */
  setOffset: (offset: number) => void;
  /** Reset all filters back to their defaults */
  resetFilters: () => void;
}

// ---------------------------------------------------------------------------
// Context creation
// ---------------------------------------------------------------------------

const FilterContext = createContext<FilterContextValue | null>(null);

// ---------------------------------------------------------------------------
// Provider
// ---------------------------------------------------------------------------

interface FilterProviderProps {
  children: ReactNode;
  /** Initial filters — useful for testing */
  initialFilters?: AlertFilterState;
}

/**
 * FilterProvider must wrap any component tree that uses useFilterContext.
 *
 * @example
 * <FilterProvider>
 *   <AlertDashboardPage />
 * </FilterProvider>
 */
export function FilterProvider({ children, initialFilters }: FilterProviderProps) {
  const [filters, setFilters] = useState<AlertFilterState>(
    initialFilters ?? DEFAULT_ALERT_FILTERS,
  );

  const setSeverity = (severity: Severity | undefined) =>
    setFilters((prev) => ({ ...prev, severity, offset: 0 }));

  const setTripwireType = (tripwire_type: TripwireType | undefined) =>
    setFilters((prev) => ({ ...prev, tripwire_type, offset: 0 }));

  const setHostId = (host_id: string | undefined) =>
    setFilters((prev) => ({ ...prev, host_id, offset: 0 }));

  const setFrom = (from: string | undefined) =>
    setFilters((prev) => ({ ...prev, from, offset: 0 }));

  const setTo = (to: string | undefined) =>
    setFilters((prev) => ({ ...prev, to, offset: 0 }));

  const setLimit = (limit: number) =>
    setFilters((prev) => ({ ...prev, limit, offset: 0 }));

  const setOffset = (offset: number) =>
    setFilters((prev) => ({ ...prev, offset }));

  const resetFilters = () => setFilters(DEFAULT_ALERT_FILTERS);

  const value: FilterContextValue = {
    filters,
    setSeverity,
    setTripwireType,
    setHostId,
    setFrom,
    setTo,
    setLimit,
    setOffset,
    resetFilters,
  };

  return <FilterContext.Provider value={value}>{children}</FilterContext.Provider>;
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

/**
 * Returns the current filter context value.
 * Must be used inside a FilterProvider.
 *
 * @throws {Error} When called outside a FilterProvider.
 *
 * @example
 * const { filters, setSeverity } = useFilterContext();
 */
export function useFilterContext(): FilterContextValue {
  const ctx = useContext(FilterContext);
  if (ctx === null) {
    throw new Error('useFilterContext must be used inside a FilterProvider');
  }
  return ctx;
}
