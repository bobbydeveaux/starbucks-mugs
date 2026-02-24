import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import { NutritionBar } from './NutritionBar';

describe('NutritionBar', () => {
  it('renders without crashing', () => {
    render(<NutritionBar costaValue={100} starbucksValue={130} />);
    // Component renders a wrapper div with role="img"
    expect(screen.getByRole('img')).toBeInTheDocument();
  });

  it('includes both brand values in the accessible label', () => {
    render(<NutritionBar costaValue={95} starbucksValue={130} unit="kcal" />);
    const img = screen.getByRole('img');
    expect(img).toHaveAttribute('aria-label', 'Costa 95kcal vs Starbucks 130kcal');
  });

  it('renders with zero values without throwing', () => {
    render(<NutritionBar costaValue={0} starbucksValue={0} unit="g" />);
    expect(screen.getByRole('img')).toBeInTheDocument();
  });

  it('renders when one value is zero and the other is positive', () => {
    render(<NutritionBar costaValue={0} starbucksValue={50} unit="mg" />);
    expect(screen.getByRole('img')).toBeInTheDocument();
    const img = screen.getByRole('img');
    expect(img).toHaveAttribute('aria-label', 'Costa 0mg vs Starbucks 50mg');
  });

  it('renders when values are equal (no winner)', () => {
    render(<NutritionBar costaValue={75} starbucksValue={75} unit="g" />);
    expect(screen.getByRole('img')).toBeInTheDocument();
  });

  it('renders without a unit prop', () => {
    render(<NutritionBar costaValue={10} starbucksValue={20} />);
    const img = screen.getByRole('img');
    // unit defaults to '' so no unit suffix
    expect(img).toHaveAttribute('aria-label', 'Costa 10 vs Starbucks 20');
  });
});
