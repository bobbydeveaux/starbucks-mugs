import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { CatalogFilters } from './CatalogFilters';

const DEFAULT_PROPS = {
  era: undefined as number | undefined,
  onEraChange: vi.fn(),
  searchValue: '',
  onSearchChange: vi.fn(),
};

describe('CatalogFilters', () => {
  it('renders the search bar', () => {
    render(<CatalogFilters {...DEFAULT_PROPS} />);
    expect(screen.getByRole('searchbox')).toBeInTheDocument();
  });

  it('renders the era filter', () => {
    render(<CatalogFilters {...DEFAULT_PROPS} />);
    expect(screen.getByRole('button', { name: /^all$/i })).toBeInTheDocument();
  });

  it('renders "Filter Cars" heading', () => {
    render(<CatalogFilters {...DEFAULT_PROPS} />);
    expect(screen.getByText(/filter cars/i)).toBeInTheDocument();
  });

  it('does not show "Clear all filters" when no filters are active', () => {
    render(<CatalogFilters {...DEFAULT_PROPS} />);
    expect(screen.queryByRole('button', { name: /clear all filters/i })).not.toBeInTheDocument();
  });

  it('shows "Clear all filters" when era is set', () => {
    render(<CatalogFilters {...DEFAULT_PROPS} era={1980} />);
    expect(screen.getByRole('button', { name: /clear all filters/i })).toBeInTheDocument();
  });

  it('shows "Clear all filters" when search value is non-empty', () => {
    render(<CatalogFilters {...DEFAULT_PROPS} searchValue="Diablo" />);
    expect(screen.getByRole('button', { name: /clear all filters/i })).toBeInTheDocument();
  });

  it('"Clear all filters" calls both onEraChange(undefined) and onSearchChange("")', () => {
    const onEraChange = vi.fn();
    const onSearchChange = vi.fn();
    render(
      <CatalogFilters
        era={1990}
        onEraChange={onEraChange}
        searchValue="Countach"
        onSearchChange={onSearchChange}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /clear all filters/i }));
    expect(onEraChange).toHaveBeenCalledWith(undefined);
    expect(onSearchChange).toHaveBeenCalledWith('');
  });

  it('passes era value and onChange to EraFilter', () => {
    const onEraChange = vi.fn();
    render(
      <CatalogFilters {...DEFAULT_PROPS} era={1970} onEraChange={onEraChange} />,
    );
    // 1970s button should be pressed
    expect(screen.getByRole('button', { name: /1970s/i })).toHaveAttribute('aria-pressed', 'true');
  });

  it('passes searchValue and onChange to SearchBar', () => {
    render(<CatalogFilters {...DEFAULT_PROPS} searchValue="Enzo" />);
    expect(screen.getByRole('searchbox')).toHaveValue('Enzo');
  });
});
