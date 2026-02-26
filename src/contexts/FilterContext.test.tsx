import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { FilterProvider, useFilterContext } from './FilterContext';
import { DEFAULT_ALERT_FILTERS } from '../types/alert';
import type { AlertFilterState } from '../types/alert';

// ---------------------------------------------------------------------------
// Helper component that surfaces filter state values for testing
// ---------------------------------------------------------------------------

function FilterConsumer() {
  const {
    filters,
    setSeverity,
    setTripwireType,
    setHostId,
    setFrom,
    setTo,
    setLimit,
    setOffset,
    resetFilters,
  } = useFilterContext();

  return (
    <div>
      <span data-testid="severity">{filters.severity ?? 'none'}</span>
      <span data-testid="type">{filters.tripwire_type ?? 'none'}</span>
      <span data-testid="host">{filters.host_id ?? 'none'}</span>
      <span data-testid="from">{filters.from ?? 'none'}</span>
      <span data-testid="to">{filters.to ?? 'none'}</span>
      <span data-testid="limit">{filters.limit}</span>
      <span data-testid="offset">{filters.offset}</span>
      <button onClick={() => setSeverity('CRITICAL')}>set severity</button>
      <button onClick={() => setSeverity(undefined)}>clear severity</button>
      <button onClick={() => setTripwireType('FILE')}>set type</button>
      <button onClick={() => setHostId('host-xyz')}>set host</button>
      <button onClick={() => setFrom('2026-01-01T00:00:00Z')}>set from</button>
      <button onClick={() => setTo('2026-01-31T23:59:59Z')}>set to</button>
      <button onClick={() => setLimit(10)}>set limit</button>
      <button onClick={() => setOffset(20)}>set offset</button>
      <button onClick={resetFilters}>reset</button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('FilterProvider', () => {
  it('provides default filter values on mount', () => {
    render(
      <FilterProvider>
        <FilterConsumer />
      </FilterProvider>,
    );

    expect(screen.getByTestId('severity').textContent).toBe('none');
    expect(screen.getByTestId('type').textContent).toBe('none');
    expect(screen.getByTestId('host').textContent).toBe('none');
    expect(screen.getByTestId('limit').textContent).toBe(String(DEFAULT_ALERT_FILTERS.limit));
    expect(screen.getByTestId('offset').textContent).toBe('0');
  });

  it('accepts and uses custom initialFilters', () => {
    const custom: AlertFilterState = {
      ...DEFAULT_ALERT_FILTERS,
      severity: 'WARN',
      limit: 10,
    };
    render(
      <FilterProvider initialFilters={custom}>
        <FilterConsumer />
      </FilterProvider>,
    );

    expect(screen.getByTestId('severity').textContent).toBe('WARN');
    expect(screen.getByTestId('limit').textContent).toBe('10');
  });

  it('setSeverity updates the severity filter', () => {
    render(
      <FilterProvider>
        <FilterConsumer />
      </FilterProvider>,
    );

    fireEvent.click(screen.getByText('set severity'));
    expect(screen.getByTestId('severity').textContent).toBe('CRITICAL');
  });

  it('setSeverity resets offset to 0', () => {
    render(
      <FilterProvider initialFilters={{ ...DEFAULT_ALERT_FILTERS, offset: 50 }}>
        <FilterConsumer />
      </FilterProvider>,
    );

    fireEvent.click(screen.getByText('set severity'));
    expect(screen.getByTestId('offset').textContent).toBe('0');
  });

  it('setSeverity(undefined) clears the severity filter', () => {
    render(
      <FilterProvider initialFilters={{ ...DEFAULT_ALERT_FILTERS, severity: 'CRITICAL' }}>
        <FilterConsumer />
      </FilterProvider>,
    );

    fireEvent.click(screen.getByText('clear severity'));
    expect(screen.getByTestId('severity').textContent).toBe('none');
  });

  it('setTripwireType updates the tripwire type filter', () => {
    render(
      <FilterProvider>
        <FilterConsumer />
      </FilterProvider>,
    );

    fireEvent.click(screen.getByText('set type'));
    expect(screen.getByTestId('type').textContent).toBe('FILE');
  });

  it('setHostId updates the host filter', () => {
    render(
      <FilterProvider>
        <FilterConsumer />
      </FilterProvider>,
    );

    fireEvent.click(screen.getByText('set host'));
    expect(screen.getByTestId('host').textContent).toBe('host-xyz');
  });

  it('setFrom and setTo update time window filters', () => {
    render(
      <FilterProvider>
        <FilterConsumer />
      </FilterProvider>,
    );

    fireEvent.click(screen.getByText('set from'));
    fireEvent.click(screen.getByText('set to'));
    expect(screen.getByTestId('from').textContent).toBe('2026-01-01T00:00:00Z');
    expect(screen.getByTestId('to').textContent).toBe('2026-01-31T23:59:59Z');
  });

  it('setLimit updates the limit and resets offset', () => {
    render(
      <FilterProvider initialFilters={{ ...DEFAULT_ALERT_FILTERS, offset: 50 }}>
        <FilterConsumer />
      </FilterProvider>,
    );

    fireEvent.click(screen.getByText('set limit'));
    expect(screen.getByTestId('limit').textContent).toBe('10');
    expect(screen.getByTestId('offset').textContent).toBe('0');
  });

  it('setOffset updates the pagination offset', () => {
    render(
      <FilterProvider>
        <FilterConsumer />
      </FilterProvider>,
    );

    fireEvent.click(screen.getByText('set offset'));
    expect(screen.getByTestId('offset').textContent).toBe('20');
  });

  it('resetFilters restores all defaults', () => {
    render(
      <FilterProvider
        initialFilters={{
          ...DEFAULT_ALERT_FILTERS,
          severity: 'CRITICAL',
          tripwire_type: 'FILE',
          host_id: 'host-xyz',
          offset: 100,
        }}
      >
        <FilterConsumer />
      </FilterProvider>,
    );

    fireEvent.click(screen.getByText('reset'));

    expect(screen.getByTestId('severity').textContent).toBe('none');
    expect(screen.getByTestId('type').textContent).toBe('none');
    expect(screen.getByTestId('host').textContent).toBe('none');
    expect(screen.getByTestId('offset').textContent).toBe('0');
  });
});

describe('useFilterContext', () => {
  it('throws when used outside a FilterProvider', () => {
    const originalError = console.error;
    console.error = () => {};

    expect(() => render(<FilterConsumer />)).toThrow(
      'useFilterContext must be used inside a FilterProvider',
    );

    console.error = originalError;
  });
});
