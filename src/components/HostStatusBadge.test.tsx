import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { HostStatusBadge } from './HostStatusBadge';
import type { HostStatus } from '../types';

describe('HostStatusBadge', () => {
  it('renders "Online" for ONLINE status', () => {
    render(<HostStatusBadge status="ONLINE" />);
    expect(screen.getByText('Online')).toBeInTheDocument();
  });

  it('renders "Offline" for OFFLINE status', () => {
    render(<HostStatusBadge status="OFFLINE" />);
    expect(screen.getByText('Offline')).toBeInTheDocument();
  });

  it('renders "Degraded" for DEGRADED status', () => {
    render(<HostStatusBadge status="DEGRADED" />);
    expect(screen.getByText('Degraded')).toBeInTheDocument();
  });

  it('has role="status" for accessibility', () => {
    render(<HostStatusBadge status="ONLINE" />);
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it.each<[HostStatus, string]>([
    ['ONLINE', 'Host status: Online'],
    ['OFFLINE', 'Host status: Offline'],
    ['DEGRADED', 'Host status: Degraded'],
  ])('has accessible aria-label for %s', (status, expectedLabel) => {
    render(<HostStatusBadge status={status} />);
    expect(screen.getByRole('status', { name: expectedLabel })).toBeInTheDocument();
  });

  it('applies green styling for ONLINE', () => {
    const { container } = render(<HostStatusBadge status="ONLINE" />);
    const badge = container.firstChild as HTMLElement;
    expect(badge.className).toContain('green');
  });

  it('applies red styling for OFFLINE', () => {
    const { container } = render(<HostStatusBadge status="OFFLINE" />);
    const badge = container.firstChild as HTMLElement;
    expect(badge.className).toContain('red');
  });

  it('applies yellow styling for DEGRADED', () => {
    const { container } = render(<HostStatusBadge status="DEGRADED" />);
    const badge = container.firstChild as HTMLElement;
    expect(badge.className).toContain('yellow');
  });
});
