import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { AlertFeed } from './AlertFeed';
import type { TripwireAlert } from '../types';

// ---------------------------------------------------------------------------
// Mock react-window
// ---------------------------------------------------------------------------

/**
 * react-window's FixedSizeList requires a measured container and calculates
 * which rows to render based on scroll position.  In jsdom there is no layout
 * engine, so we replace FixedSizeList with a simple implementation that
 * renders ALL items unconditionally — sufficient for unit tests.
 */
vi.mock('react-window', () => ({
  FixedSizeList: ({
    itemCount,
    itemData,
    children: RowComponent,
  }: {
    height: number;
    width: string | number;
    itemCount: number;
    itemSize: number;
    itemData: unknown;
    overscanCount?: number;
    children: React.ComponentType<{ index: number; style: React.CSSProperties; data: unknown }>;
  }) => (
    <div data-testid="fixed-size-list">
      {Array.from({ length: itemCount }, (_, i) => (
        <RowComponent key={i} index={i} style={{}} data={itemData} />
      ))}
    </div>
  ),
}));

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeAlert(overrides: Partial<TripwireAlert> = {}): TripwireAlert {
  return {
    alert_id: crypto.randomUUID(),
    host_id: 'host-001',
    hostname: 'web-01',
    timestamp: new Date().toISOString(),
    tripwire_type: 'FILE',
    rule_name: 'etc-passwd-watch',
    severity: 'CRITICAL',
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('AlertFeed', () => {
  // ── Empty state ────────────────────────────────────────────────────────────

  it('renders an empty-state message when alerts array is empty', () => {
    render(<AlertFeed alerts={[]} />);
    expect(screen.getByText(/no alerts/i)).toBeInTheDocument();
  });

  it('has role="status" and aria-live="polite" on the empty-state container', () => {
    render(<AlertFeed alerts={[]} />);
    const status = screen.getByRole('status');
    expect(status).toHaveAttribute('aria-live', 'polite');
  });

  // ── Alert list rendering ───────────────────────────────────────────────────

  it('renders a FixedSizeList (virtualized container) when alerts are present', () => {
    render(<AlertFeed alerts={[makeAlert()]} />);
    expect(screen.getByTestId('fixed-size-list')).toBeInTheDocument();
  });

  it('renders one row for each alert', () => {
    const alerts = [
      makeAlert({ rule_name: 'rule-a' }),
      makeAlert({ rule_name: 'rule-b' }),
      makeAlert({ rule_name: 'rule-c' }),
    ];
    render(<AlertFeed alerts={alerts} />);
    expect(screen.getByText('rule-a')).toBeInTheDocument();
    expect(screen.getByText('rule-b')).toBeInTheDocument();
    expect(screen.getByText('rule-c')).toBeInTheDocument();
  });

  it('displays the hostname in each row', () => {
    const alert = makeAlert({ hostname: 'prod-server-42' });
    render(<AlertFeed alerts={[alert]} />);
    expect(screen.getByText('prod-server-42')).toBeInTheDocument();
  });

  // ── Severity styling ───────────────────────────────────────────────────────

  it('renders a CRITICAL severity badge', () => {
    render(<AlertFeed alerts={[makeAlert({ severity: 'CRITICAL' })]} />);
    expect(screen.getByText('CRITICAL')).toBeInTheDocument();
  });

  it('renders a WARN severity badge', () => {
    render(<AlertFeed alerts={[makeAlert({ severity: 'WARN' })]} />);
    expect(screen.getByText('WARN')).toBeInTheDocument();
  });

  it('renders an INFO severity badge', () => {
    render(<AlertFeed alerts={[makeAlert({ severity: 'INFO' })]} />);
    expect(screen.getByText('INFO')).toBeInTheDocument();
  });

  // ── Accessibility ──────────────────────────────────────────────────────────

  it('each row has role="button" for keyboard accessibility', () => {
    render(<AlertFeed alerts={[makeAlert(), makeAlert()]} />);
    const buttons = screen.getAllByRole('button');
    expect(buttons.length).toBeGreaterThanOrEqual(2);
  });

  it('rows have a descriptive aria-label', () => {
    const alert = makeAlert({ severity: 'WARN', rule_name: 'ssh-login', hostname: 'bastion' });
    render(<AlertFeed alerts={[alert]} />);
    const button = screen.getByRole('button', { name: /WARN alert: ssh-login on bastion/i });
    expect(button).toBeInTheDocument();
  });

  it('rows are focusable (tabIndex=0)', () => {
    render(<AlertFeed alerts={[makeAlert()]} />);
    const button = screen.getAllByRole('button')[0];
    expect(button).toHaveAttribute('tabindex', '0');
  });

  // ── onSelectAlert callback ─────────────────────────────────────────────────

  it('calls onSelectAlert with the alert when a row is clicked', () => {
    const onSelectAlert = vi.fn();
    const alert = makeAlert({ rule_name: 'test-rule' });
    render(<AlertFeed alerts={[alert]} onSelectAlert={onSelectAlert} />);
    fireEvent.click(screen.getByRole('button', { name: /test-rule/i }));
    expect(onSelectAlert).toHaveBeenCalledTimes(1);
    expect(onSelectAlert).toHaveBeenCalledWith(alert);
  });

  it('calls onSelectAlert when Enter key is pressed on a row', () => {
    const onSelectAlert = vi.fn();
    const alert = makeAlert({ rule_name: 'keyboard-rule' });
    render(<AlertFeed alerts={[alert]} onSelectAlert={onSelectAlert} />);
    fireEvent.keyDown(screen.getByRole('button', { name: /keyboard-rule/i }), {
      key: 'Enter',
    });
    expect(onSelectAlert).toHaveBeenCalledTimes(1);
  });

  it('calls onSelectAlert when Space key is pressed on a row', () => {
    const onSelectAlert = vi.fn();
    const alert = makeAlert({ rule_name: 'space-rule' });
    render(<AlertFeed alerts={[alert]} onSelectAlert={onSelectAlert} />);
    fireEvent.keyDown(screen.getByRole('button', { name: /space-rule/i }), {
      key: ' ',
    });
    expect(onSelectAlert).toHaveBeenCalledTimes(1);
  });

  it('does not throw when onSelectAlert is not provided and a row is clicked', () => {
    render(<AlertFeed alerts={[makeAlert()]} />);
    const button = screen.getAllByRole('button')[0];
    expect(() => fireEvent.click(button)).not.toThrow();
  });

  // ── Sensor type icons ──────────────────────────────────────────────────────

  it('shows the file icon for FILE type alerts', () => {
    render(<AlertFeed alerts={[makeAlert({ tripwire_type: 'FILE' })]} />);
    // aria-label is based on severity+rule+host, not type — use getAllByRole to
    // grab the single rendered row and assert on its text content.
    const [button] = screen.getAllByRole('button');
    expect(button.textContent).toContain('📄');
  });

  it('shows the network icon for NETWORK type alerts', () => {
    render(<AlertFeed alerts={[makeAlert({ tripwire_type: 'NETWORK' })]} />);
    const [button] = screen.getAllByRole('button');
    expect(button.textContent).toContain('🌐');
  });

  it('shows the process icon for PROCESS type alerts', () => {
    render(<AlertFeed alerts={[makeAlert({ tripwire_type: 'PROCESS' })]} />);
    const [button] = screen.getAllByRole('button');
    expect(button.textContent).toContain('⚙️');
  });
});
