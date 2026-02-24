import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { ComparisonPanel } from './ComparisonPanel';
import type { Drink } from '../types';

const starbucksDrink: Drink = {
  id: 'sbux-flat-white',
  brand: 'starbucks',
  name: 'Flat White',
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

const costaDrink: Drink = {
  id: 'costa-flat-white',
  brand: 'costa',
  name: 'Flat White',
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

describe('ComparisonPanel', () => {
  describe('no selection', () => {
    it('renders nothing when both drinks are null', () => {
      const { container } = render(
        <ComparisonPanel starbucksDrink={null} costaDrink={null} onClear={vi.fn()} />
      );
      expect(container.firstChild).toBeNull();
    });
  });

  describe('partial selection — only Starbucks selected', () => {
    it('renders the panel section', () => {
      render(
        <ComparisonPanel starbucksDrink={starbucksDrink} costaDrink={null} onClear={vi.fn()} />
      );
      expect(screen.getByRole('region', { name: /comparison panel/i })).toBeInTheDocument();
    });

    it('shows the Starbucks drink name', () => {
      render(
        <ComparisonPanel starbucksDrink={starbucksDrink} costaDrink={null} onClear={vi.fn()} />
      );
      expect(screen.getByText('Flat White')).toBeInTheDocument();
    });

    it('prompts to select a Costa drink', () => {
      render(
        <ComparisonPanel starbucksDrink={starbucksDrink} costaDrink={null} onClear={vi.fn()} />
      );
      expect(screen.getByText(/select a costa drink/i)).toBeInTheDocument();
    });

    it('does not render the nutrition table', () => {
      render(
        <ComparisonPanel starbucksDrink={starbucksDrink} costaDrink={null} onClear={vi.fn()} />
      );
      expect(screen.queryByRole('table')).not.toBeInTheDocument();
    });
  });

  describe('partial selection — only Costa selected', () => {
    it('prompts to select a Starbucks drink', () => {
      render(
        <ComparisonPanel starbucksDrink={null} costaDrink={costaDrink} onClear={vi.fn()} />
      );
      expect(screen.getByText(/select a starbucks drink/i)).toBeInTheDocument();
    });

    it('shows the Costa drink name', () => {
      render(
        <ComparisonPanel starbucksDrink={null} costaDrink={costaDrink} onClear={vi.fn()} />
      );
      expect(screen.getByText('Flat White')).toBeInTheDocument();
    });
  });

  describe('full comparison — both drinks selected', () => {
    it('renders the heading', () => {
      render(
        <ComparisonPanel
          starbucksDrink={starbucksDrink}
          costaDrink={costaDrink}
          onClear={vi.fn()}
        />
      );
      expect(screen.getByText('Side-by-Side Comparison')).toBeInTheDocument();
    });

    it('renders the nutrition comparison table', () => {
      render(
        <ComparisonPanel
          starbucksDrink={starbucksDrink}
          costaDrink={costaDrink}
          onClear={vi.fn()}
        />
      );
      expect(screen.getByRole('table', { name: /nutrition comparison/i })).toBeInTheDocument();
    });

    it('renders a row for each nutritional field (5 rows)', () => {
      render(
        <ComparisonPanel
          starbucksDrink={starbucksDrink}
          costaDrink={costaDrink}
          onClear={vi.fn()}
        />
      );
      expect(screen.getByText('Calories')).toBeInTheDocument();
      expect(screen.getByText('Sugar')).toBeInTheDocument();
      expect(screen.getByText('Fat')).toBeInTheDocument();
      expect(screen.getByText('Protein')).toBeInTheDocument();
      expect(screen.getByText('Caffeine')).toBeInTheDocument();
    });

    it('renders Starbucks nutritional values', () => {
      render(
        <ComparisonPanel
          starbucksDrink={starbucksDrink}
          costaDrink={costaDrink}
          onClear={vi.fn()}
        />
      );
      expect(screen.getByText('160')).toBeInTheDocument(); // calories
      expect(screen.getByText('130')).toBeInTheDocument(); // caffeine
    });

    it('renders Costa nutritional values', () => {
      render(
        <ComparisonPanel
          starbucksDrink={starbucksDrink}
          costaDrink={costaDrink}
          onClear={vi.fn()}
        />
      );
      expect(screen.getByText('144')).toBeInTheDocument(); // calories
      expect(screen.getByText('185')).toBeInTheDocument(); // caffeine
    });

    it('renders both drink names', () => {
      render(
        <ComparisonPanel
          starbucksDrink={starbucksDrink}
          costaDrink={costaDrink}
          onClear={vi.fn()}
        />
      );
      const flatWhites = screen.getAllByText('Flat White');
      expect(flatWhites).toHaveLength(2);
    });

    it('does not show the prompt text', () => {
      render(
        <ComparisonPanel
          starbucksDrink={starbucksDrink}
          costaDrink={costaDrink}
          onClear={vi.fn()}
        />
      );
      expect(screen.queryByText(/select a starbucks drink/i)).not.toBeInTheDocument();
      expect(screen.queryByText(/select a costa drink/i)).not.toBeInTheDocument();
    });
  });

  describe('Clear button', () => {
    it('renders the Clear button when at least one drink is selected', () => {
      render(
        <ComparisonPanel starbucksDrink={starbucksDrink} costaDrink={null} onClear={vi.fn()} />
      );
      expect(screen.getByRole('button', { name: /clear/i })).toBeInTheDocument();
    });

    it('calls onClear when the Clear button is clicked', () => {
      const onClear = vi.fn();
      render(
        <ComparisonPanel
          starbucksDrink={starbucksDrink}
          costaDrink={costaDrink}
          onClear={onClear}
        />
      );
      fireEvent.click(screen.getByRole('button', { name: /clear/i }));
      expect(onClear).toHaveBeenCalledTimes(1);
    });
  });
});
