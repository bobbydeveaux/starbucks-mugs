import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { FilterBar } from './FilterBar';
import { CATEGORY_LABELS } from '../utils/filterDrinks';

describe('FilterBar', () => {
  it('renders a button for each category including All', () => {
    render(<FilterBar category="all" onCategoryChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: /^all$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^hot$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^iced$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^blended$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^tea$/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /^other$/i })).toBeInTheDocument();
  });

  it('renders all six category buttons', () => {
    render(<FilterBar category="all" onCategoryChange={vi.fn()} />);
    const buttons = screen.getAllByRole('button');
    expect(buttons).toHaveLength(6);
  });

  it('renders buttons with correct labels', () => {
    render(<FilterBar category="all" onCategoryChange={vi.fn()} />);
    for (const label of Object.values(CATEGORY_LABELS)) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument();
    }
  });

  it('marks the active category button as pressed', () => {
    render(<FilterBar category="hot" onCategoryChange={vi.fn()} />);
    const hotButton = screen.getByRole('button', { name: 'Hot' });
    expect(hotButton).toHaveAttribute('aria-pressed', 'true');
  });

  it('marks all other buttons as not pressed', () => {
    render(<FilterBar category="hot" onCategoryChange={vi.fn()} />);
    const notPressedButtons = screen
      .getAllByRole('button')
      .filter((btn) => btn.getAttribute('aria-pressed') === 'false');
    expect(notPressedButtons).toHaveLength(5);
  });

  it('marks the "All" button as active when category is "all"', () => {
    render(<FilterBar category="all" onCategoryChange={vi.fn()} />);
    const allButton = screen.getByRole('button', { name: 'All' });
    expect(allButton).toHaveAttribute('aria-pressed', 'true');
  });

  it('calls onCategoryChange with the clicked category', () => {
    const onCategoryChange = vi.fn();
    render(<FilterBar category="all" onCategoryChange={onCategoryChange} />);
    fireEvent.click(screen.getByRole('button', { name: 'Iced' }));
    expect(onCategoryChange).toHaveBeenCalledOnce();
    expect(onCategoryChange).toHaveBeenCalledWith('iced');
  });

  it('calls onCategoryChange with "all" when the All button is clicked', () => {
    const onCategoryChange = vi.fn();
    render(<FilterBar category="hot" onCategoryChange={onCategoryChange} />);
    fireEvent.click(screen.getByRole('button', { name: 'All' }));
    expect(onCategoryChange).toHaveBeenCalledWith('all');
  });

  it('has a group role with accessible label', () => {
    render(<FilterBar category="all" onCategoryChange={vi.fn()} />);
    expect(screen.getByRole('group', { name: /filter by category/i })).toBeInTheDocument();
  });

  it('marks blended button as pressed when category is "blended"', () => {
    render(<FilterBar category="blended" onCategoryChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: /^blended$/i })).toHaveAttribute(
      'aria-pressed',
      'true'
    );
    expect(screen.getByRole('button', { name: /^all$/i })).toHaveAttribute(
      'aria-pressed',
      'false'
    );
  });
});
