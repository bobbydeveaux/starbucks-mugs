import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { FilterBar } from './FilterBar';

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

  it('renders 6 category buttons in total', () => {
    render(<FilterBar category="all" onCategoryChange={vi.fn()} />);
    const buttons = screen.getAllByRole('button');
    expect(buttons).toHaveLength(6);
  });

  it('marks the active category button with aria-pressed=true', () => {
    render(<FilterBar category="hot" onCategoryChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: /^hot$/i })).toHaveAttribute(
      'aria-pressed',
      'true'
    );
  });

  it('marks inactive category buttons with aria-pressed=false', () => {
    render(<FilterBar category="hot" onCategoryChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: /^all$/i })).toHaveAttribute(
      'aria-pressed',
      'false'
    );
    expect(screen.getByRole('button', { name: /^iced$/i })).toHaveAttribute(
      'aria-pressed',
      'false'
    );
  });

  it('calls onCategoryChange with the clicked category value', () => {
    const onCategoryChange = vi.fn();
    render(<FilterBar category="all" onCategoryChange={onCategoryChange} />);
    fireEvent.click(screen.getByRole('button', { name: /^hot$/i }));
    expect(onCategoryChange).toHaveBeenCalledTimes(1);
    expect(onCategoryChange).toHaveBeenCalledWith('hot');
  });

  it('calls onCategoryChange with "all" when the All button is clicked', () => {
    const onCategoryChange = vi.fn();
    render(<FilterBar category="hot" onCategoryChange={onCategoryChange} />);
    fireEvent.click(screen.getByRole('button', { name: /^all$/i }));
    expect(onCategoryChange).toHaveBeenCalledWith('all');
  });

  it('renders within a labelled group for accessibility', () => {
    render(<FilterBar category="all" onCategoryChange={vi.fn()} />);
    expect(
      screen.getByRole('group', { name: /filter by category/i })
    ).toBeInTheDocument();
  });

  it('marks All button as pressed when category is "all"', () => {
    render(<FilterBar category="all" onCategoryChange={vi.fn()} />);
    expect(screen.getByRole('button', { name: /^all$/i })).toHaveAttribute(
      'aria-pressed',
      'true'
    );
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
