import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { CarCard } from './CarCard';
import type { CarModel } from '../types';

const mockFerrariCar: CarModel = {
  id: 'ferrari-testarossa-1984',
  brand: 'ferrari',
  model: 'Testarossa',
  year: 1984,
  decade: 1980,
  imageUrl: '/images/ferrari/testarossa.jpg',
  specs: {
    hp: 390,
    torqueLbFt: 362,
    zeroToSixtyMs: 5.8,
    topSpeedMph: 181,
    engineConfig: 'Flat-12, 4.9L',
  },
  eraRivals: ['lamborghini-countach-lp500-1982'],
};

const mockLamboCar: CarModel = {
  id: 'lamborghini-countach-lp500-1982',
  brand: 'lamborghini',
  model: 'Countach LP500',
  year: 1982,
  decade: 1980,
  imageUrl: '/images/lamborghini/countach-lp500.jpg',
  specs: {
    hp: 375,
    torqueLbFt: 268,
    zeroToSixtyMs: 5.6,
    topSpeedMph: 183,
    engineConfig: 'V12, 4.8L',
  },
  eraRivals: ['ferrari-testarossa-1984'],
};

describe('CarCard', () => {
  it('renders the car model name', () => {
    render(<CarCard car={mockFerrariCar} isSelected={false} onSelect={vi.fn()} />);
    expect(screen.getByText('Testarossa')).toBeInTheDocument();
  });

  it('renders the car year', () => {
    render(<CarCard car={mockFerrariCar} isSelected={false} onSelect={vi.fn()} />);
    expect(screen.getByText('1984')).toBeInTheDocument();
  });

  it('renders the engine config badge', () => {
    render(<CarCard car={mockFerrariCar} isSelected={false} onSelect={vi.fn()} />);
    expect(screen.getByText('Flat-12, 4.9L')).toBeInTheDocument();
  });

  it('renders "Select to Compare" CTA when not selected', () => {
    render(<CarCard car={mockFerrariCar} isSelected={false} onSelect={vi.fn()} />);
    expect(screen.getByRole('button', { name: /select to compare/i })).toBeInTheDocument();
  });

  it('renders "Selected ✓" CTA when selected', () => {
    render(<CarCard car={mockFerrariCar} isSelected={true} onSelect={vi.fn()} />);
    expect(screen.getByRole('button')).toHaveTextContent('Selected ✓');
  });

  it('calls onSelect with the car when CTA is clicked', () => {
    const onSelect = vi.fn();
    render(<CarCard car={mockFerrariCar} isSelected={false} onSelect={onSelect} />);
    fireEvent.click(screen.getByRole('button'));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith(mockFerrariCar);
  });

  it('sets aria-pressed=true on the button when selected', () => {
    render(<CarCard car={mockFerrariCar} isSelected={true} onSelect={vi.fn()} />);
    expect(screen.getByRole('button')).toHaveAttribute('aria-pressed', 'true');
  });

  it('sets aria-pressed=false on the button when not selected', () => {
    render(<CarCard car={mockFerrariCar} isSelected={false} onSelect={vi.fn()} />);
    expect(screen.getByRole('button')).toHaveAttribute('aria-pressed', 'false');
  });

  it('renders the car image with lazy loading', () => {
    render(<CarCard car={mockFerrariCar} isSelected={false} onSelect={vi.fn()} />);
    const img = screen.getByRole('img', { name: /testarossa/i });
    expect(img).toBeInTheDocument();
    expect(img).toHaveAttribute('src', '/images/ferrari/testarossa.jpg');
    expect(img).toHaveAttribute('loading', 'lazy');
  });

  it('renders the HP stat', () => {
    render(<CarCard car={mockFerrariCar} isSelected={false} onSelect={vi.fn()} />);
    expect(screen.getByText('390')).toBeInTheDocument();
  });

  it('renders the top speed stat', () => {
    render(<CarCard car={mockFerrariCar} isSelected={false} onSelect={vi.fn()} />);
    expect(screen.getByText(/181 mph/)).toBeInTheDocument();
  });

  it('renders the 0-60 stat', () => {
    render(<CarCard car={mockFerrariCar} isSelected={false} onSelect={vi.fn()} />);
    expect(screen.getByText(/5\.8s/)).toBeInTheDocument();
  });

  it('applies ferrari border class for ferrari cars', () => {
    const { container } = render(
      <CarCard car={mockFerrariCar} isSelected={false} onSelect={vi.fn()} />,
    );
    const article = container.querySelector('article');
    expect(article?.className).toContain('border-ferrari-red');
  });

  it('applies lambo border class for lamborghini cars', () => {
    const { container } = render(
      <CarCard car={mockLamboCar} isSelected={false} onSelect={vi.fn()} />,
    );
    const article = container.querySelector('article');
    expect(article?.className).toContain('border-lambo-yellow');
  });

  it('applies selected ring class when isSelected is true', () => {
    const { container } = render(
      <CarCard car={mockFerrariCar} isSelected={true} onSelect={vi.fn()} />,
    );
    const article = container.querySelector('article');
    expect(article?.className).toContain('ring-ferrari-red');
  });

  it('sets data-selected=true on article when selected', () => {
    const { container } = render(
      <CarCard car={mockFerrariCar} isSelected={true} onSelect={vi.fn()} />,
    );
    const article = container.querySelector('article');
    expect(article).toHaveAttribute('data-selected', 'true');
  });

  it('sets data-selected=false on article when not selected', () => {
    const { container } = render(
      <CarCard car={mockFerrariCar} isSelected={false} onSelect={vi.fn()} />,
    );
    const article = container.querySelector('article');
    expect(article).toHaveAttribute('data-selected', 'false');
  });
});
