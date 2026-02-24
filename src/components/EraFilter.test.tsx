import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { EraFilter } from './EraFilter';

const AVAILABLE_DECADES = [1960, 1970, 1980, 1990, 2000];

describe('EraFilter', () => {
  // -------------------------------------------------------------------------
  // Rendering
  // -------------------------------------------------------------------------

  it('renders "All Eras" button', () => {
    render(<EraFilter era={null} availableDecades={AVAILABLE_DECADES} onChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: /all eras/i })).toBeInTheDocument();
  });

  it('renders a button for each available decade', () => {
    render(<EraFilter era={null} availableDecades={AVAILABLE_DECADES} onChange={vi.fn()} />);
    for (const decade of AVAILABLE_DECADES) {
      expect(screen.getByRole('button', { name: `${decade}s` })).toBeInTheDocument();
    }
  });

  it('renders with an accessible group label', () => {
    render(<EraFilter era={null} availableDecades={AVAILABLE_DECADES} onChange={vi.fn()} />);
    expect(screen.getByRole('group', { name: /filter by era/i })).toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // Active state
  // -------------------------------------------------------------------------

  it('"All Eras" button is aria-pressed=true when era is null', () => {
    render(<EraFilter era={null} availableDecades={AVAILABLE_DECADES} onChange={vi.fn()} />);
    const allErasButton = screen.getByRole('button', { name: /all eras/i });
    expect(allErasButton).toHaveAttribute('aria-pressed', 'true');
  });

  it('"All Eras" button is aria-pressed=false when a decade is selected', () => {
    render(<EraFilter era={1980} availableDecades={AVAILABLE_DECADES} onChange={vi.fn()} />);
    const allErasButton = screen.getByRole('button', { name: /all eras/i });
    expect(allErasButton).toHaveAttribute('aria-pressed', 'false');
  });

  it('the selected decade button is aria-pressed=true', () => {
    render(<EraFilter era={1980} availableDecades={AVAILABLE_DECADES} onChange={vi.fn()} />);
    const decadeButton = screen.getByRole('button', { name: '1980s' });
    expect(decadeButton).toHaveAttribute('aria-pressed', 'true');
  });

  it('non-selected decade buttons are aria-pressed=false', () => {
    render(<EraFilter era={1980} availableDecades={AVAILABLE_DECADES} onChange={vi.fn()} />);
    const decadeButton = screen.getByRole('button', { name: '1970s' });
    expect(decadeButton).toHaveAttribute('aria-pressed', 'false');
  });

  // -------------------------------------------------------------------------
  // Interactions
  // -------------------------------------------------------------------------

  it('calls onChange with the decade when a decade button is clicked', () => {
    const onChange = vi.fn();
    render(<EraFilter era={null} availableDecades={AVAILABLE_DECADES} onChange={onChange} />);
    fireEvent.click(screen.getByRole('button', { name: '1980s' }));
    expect(onChange).toHaveBeenCalledWith(1980);
  });

  it('calls onChange with null when "All Eras" is clicked', () => {
    const onChange = vi.fn();
    render(<EraFilter era={1980} availableDecades={AVAILABLE_DECADES} onChange={onChange} />);
    fireEvent.click(screen.getByRole('button', { name: /all eras/i }));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it('calls onChange with null when the already-selected decade is clicked again (toggle off)', () => {
    const onChange = vi.fn();
    render(<EraFilter era={1980} availableDecades={AVAILABLE_DECADES} onChange={onChange} />);
    // Clicking the active decade should deselect it (pass null)
    fireEvent.click(screen.getByRole('button', { name: '1980s' }));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it('renders without errors when availableDecades is empty', () => {
    render(<EraFilter era={null} availableDecades={[]} onChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: /all eras/i })).toBeInTheDocument();
  });
});
