import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ComparisonPanel } from './ComparisonPanel';
import type { Drink, ComparisonState } from '../types';

const costaDrink: Drink = {
  id: 'costa-flat-white',
  brand: 'costa',
  name: 'Costa Flat White',
  category: 'hot',
  size_ml: 300,
  nutrition: {
    calories_kcal: 144,
    sugar_g: 12,
    fat_g: 8,
    protein_g: 8,
    caffeine_mg: 185,
  },
};

const starbucksDrink: Drink = {
  id: 'sbux-flat-white',
  brand: 'starbucks',
  name: 'Starbucks Flat White',
  category: 'hot',
  size_ml: 354,
  nutrition: {
    calories_kcal: 160,
    sugar_g: 14,
    fat_g: 6,
    protein_g: 9,
    caffeine_mg: 130,
  },
};

const emptyComparison: ComparisonState = { starbucks: null, costa: null };
const fullComparison: ComparisonState = { starbucks: starbucksDrink, costa: costaDrink };
const starbucksOnly: ComparisonState = { starbucks: starbucksDrink, costa: null };
const costaOnly: ComparisonState = { starbucks: null, costa: costaDrink };

describe('ComparisonPanel', () => {
  it('renders nothing when no drinks are selected', () => {
    const { container } = render(
      <ComparisonPanel comparison={emptyComparison} onClear={vi.fn()} />
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders the panel when at least one drink is selected', () => {
    render(<ComparisonPanel comparison={starbucksOnly} onClear={vi.fn()} />);
    expect(screen.getByRole('region', { name: /comparison/i })).toBeInTheDocument();
  });

  it('shows a prompt when only one drink is selected', () => {
    render(<ComparisonPanel comparison={costaOnly} onClear={vi.fn()} />);
    expect(
      screen.getByText(/select one drink from each brand/i)
    ).toBeInTheDocument();
  });

  it('renders all 5 nutrition row labels when both drinks selected', () => {
    render(<ComparisonPanel comparison={fullComparison} onClear={vi.fn()} />);
    expect(screen.getByText('Calories')).toBeInTheDocument();
    expect(screen.getByText('Sugar')).toBeInTheDocument();
    expect(screen.getByText('Fat')).toBeInTheDocument();
    expect(screen.getByText('Protein')).toBeInTheDocument();
    expect(screen.getByText('Caffeine')).toBeInTheDocument();
  });

  it('renders drink names in the header columns', () => {
    render(<ComparisonPanel comparison={fullComparison} onClear={vi.fn()} />);
    expect(screen.getByText('Costa Flat White')).toBeInTheDocument();
    expect(screen.getByText('Starbucks Flat White')).toBeInTheDocument();
  });

  it('renders Costa calorie value', () => {
    render(<ComparisonPanel comparison={fullComparison} onClear={vi.fn()} />);
    expect(screen.getByLabelText(/costa: 144 kcal/i)).toBeInTheDocument();
  });

  it('renders Starbucks calorie value', () => {
    render(<ComparisonPanel comparison={fullComparison} onClear={vi.fn()} />);
    expect(screen.getByLabelText(/starbucks: 160 kcal/i)).toBeInTheDocument();
  });

  it('calls onClear when the Clear button is clicked', () => {
    const onClear = vi.fn();
    render(<ComparisonPanel comparison={fullComparison} onClear={onClear} />);
    fireEvent.click(screen.getByRole('button', { name: /clear/i }));
    expect(onClear).toHaveBeenCalledTimes(1);
  });

  it('renders an error/guard message when both drinks are the same brand', () => {
    // Construct an edge-case ComparisonState where both slots hold drinks from the
    // same brand (e.g. via props manipulation or unexpected state). The component
    // should defensively guard against this scenario.
    const sameBrandComparison: ComparisonState = {
      starbucks: starbucksDrink,
      costa: { ...starbucksDrink, id: 'sbux-mocha', name: 'Starbucks Mocha' },
    };
    render(<ComparisonPanel comparison={sameBrandComparison} onClear={vi.fn()} />);
    expect(screen.getByRole('alert')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent(/same brand/i);
  });
});
