import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { DrinkCard } from './DrinkCard'
import type { Drink } from '../types'

const mockStarbucksDrink: Drink = {
  id: 'sbux-flat-white',
  brand: 'starbucks',
  name: 'Flat White',
  category: 'hot',
  size_ml: 354,
  image: '/images/sbux-flat-white.webp',
  nutrition: {
    calories_kcal: 160,
    sugar_g: 14,
    fat_g: 6,
    protein_g: 9,
    caffeine_mg: 130,
  },
}

const mockCostaDrink: Drink = {
  id: 'costa-flat-white',
  brand: 'costa',
  name: 'Flat White',
  category: 'hot',
  size_ml: 300,
  image: '/images/costa-flat-white.webp',
  nutrition: {
    calories_kcal: 144,
    sugar_g: 12,
    fat_g: 8,
    protein_g: 8,
    caffeine_mg: 185,
  },
}

describe('DrinkCard', () => {
  it('renders the drink name', () => {
    render(<DrinkCard drink={mockStarbucksDrink} isSelected={false} onSelect={vi.fn()} />)
    expect(screen.getByText('Flat White')).toBeInTheDocument()
  })

  it('renders a category badge', () => {
    render(<DrinkCard drink={mockStarbucksDrink} isSelected={false} onSelect={vi.fn()} />)
    expect(screen.getByText('Hot')).toBeInTheDocument()
  })

  it('renders "Select to Compare" CTA button when not selected', () => {
    render(<DrinkCard drink={mockStarbucksDrink} isSelected={false} onSelect={vi.fn()} />)
    const btn = screen.getByRole('button', { name: /select to compare/i })
    expect(btn).toBeInTheDocument()
  })

  it('renders "✓ Selected" CTA when selected', () => {
    render(<DrinkCard drink={mockStarbucksDrink} isSelected={true} onSelect={vi.fn()} />)
    const btn = screen.getByRole('button')
    expect(btn).toHaveTextContent('✓ Selected')
  })

  it('calls onSelect with the drink when CTA is clicked', () => {
    const onSelect = vi.fn()
    render(<DrinkCard drink={mockStarbucksDrink} isSelected={false} onSelect={onSelect} />)
    fireEvent.click(screen.getByRole('button'))
    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect).toHaveBeenCalledWith(mockStarbucksDrink)
  })

  it('sets aria-pressed=true on the button when selected', () => {
    render(<DrinkCard drink={mockStarbucksDrink} isSelected={true} onSelect={vi.fn()} />)
    const btn = screen.getByRole('button')
    expect(btn).toHaveAttribute('aria-pressed', 'true')
  })

  it('sets aria-pressed=false on the button when not selected', () => {
    render(<DrinkCard drink={mockStarbucksDrink} isSelected={false} onSelect={vi.fn()} />)
    const btn = screen.getByRole('button')
    expect(btn).toHaveAttribute('aria-pressed', 'false')
  })

  it('shows calorie and size info', () => {
    render(<DrinkCard drink={mockStarbucksDrink} isSelected={false} onSelect={vi.fn()} />)
    expect(screen.getByText(/160 kcal/)).toBeInTheDocument()
    expect(screen.getByText(/354 ml/)).toBeInTheDocument()
  })

  it('renders an article element with the drink image', () => {
    render(<DrinkCard drink={mockStarbucksDrink} isSelected={false} onSelect={vi.fn()} />)
    const img = screen.getByRole('img', { name: 'Flat White' })
    expect(img).toBeInTheDocument()
    expect(img).toHaveAttribute('src', '/images/sbux-flat-white.webp')
    expect(img).toHaveAttribute('loading', 'lazy')
  })

  it('applies brand-specific starbucks border class', () => {
    const { container } = render(
      <DrinkCard drink={mockStarbucksDrink} isSelected={false} onSelect={vi.fn()} />
    )
    const article = container.querySelector('article')
    expect(article?.className).toContain('border-starbucks')
  })

  it('applies brand-specific costa border class for Costa drinks', () => {
    const { container } = render(
      <DrinkCard drink={mockCostaDrink} isSelected={false} onSelect={vi.fn()} />
    )
    const article = container.querySelector('article')
    expect(article?.className).toContain('border-costa')
  })

  it('applies selected ring class when isSelected is true', () => {
    const { container } = render(
      <DrinkCard drink={mockStarbucksDrink} isSelected={true} onSelect={vi.fn()} />
    )
    const article = container.querySelector('article')
    expect(article?.className).toContain('ring-starbucks')
  })

  it('sets aria-selected=true on article when selected', () => {
    const { container } = render(
      <DrinkCard drink={mockStarbucksDrink} isSelected={true} onSelect={vi.fn()} />
    )
    const article = container.querySelector('article')
    expect(article).toHaveAttribute('data-selected', 'true')
  })
})
