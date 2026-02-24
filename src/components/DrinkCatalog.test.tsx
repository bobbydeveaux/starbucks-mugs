import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { DrinkCatalog } from './DrinkCatalog'
import type { Drink } from '../types'

const STARBUCKS_DRINKS: Drink[] = [
  {
    id: 'sbux-flat-white',
    brand: 'starbucks',
    name: 'Flat White',
    category: 'hot',
    size_ml: 354,
    image: '/images/sbux-flat-white.webp',
    nutrition: { calories_kcal: 160, sugar_g: 14, fat_g: 6, protein_g: 9, caffeine_mg: 130 },
  },
  {
    id: 'sbux-iced-latte',
    brand: 'starbucks',
    name: 'Iced Latte',
    category: 'iced',
    size_ml: 473,
    image: '/images/sbux-iced-latte.webp',
    nutrition: { calories_kcal: 130, sugar_g: 14, fat_g: 4, protein_g: 7, caffeine_mg: 150 },
  },
]

const COSTA_DRINKS: Drink[] = [
  {
    id: 'costa-flat-white',
    brand: 'costa',
    name: 'Flat White',
    category: 'hot',
    size_ml: 300,
    image: '/images/costa-flat-white.webp',
    nutrition: { calories_kcal: 144, sugar_g: 12, fat_g: 8, protein_g: 8, caffeine_mg: 185 },
  },
  {
    id: 'costa-frappe',
    brand: 'costa',
    name: 'Caramel Frostino',
    category: 'blended',
    size_ml: 454,
    image: '/images/costa-frappe.webp',
    nutrition: { calories_kcal: 450, sugar_g: 62, fat_g: 13, protein_g: 8, caffeine_mg: 60 },
  },
]

const ALL_DRINKS = [...STARBUCKS_DRINKS, ...COSTA_DRINKS]

const NO_SELECTION = { starbucks: null, costa: null }

describe('DrinkCatalog', () => {
  it('renders a section for Starbucks', () => {
    render(<DrinkCatalog drinks={ALL_DRINKS} selectedIds={NO_SELECTION} onSelect={vi.fn()} />)
    expect(screen.getByRole('region', { name: /starbucks/i })).toBeInTheDocument()
  })

  it('renders a section for Costa Coffee', () => {
    render(<DrinkCatalog drinks={ALL_DRINKS} selectedIds={NO_SELECTION} onSelect={vi.fn()} />)
    expect(screen.getByRole('region', { name: /costa/i })).toBeInTheDocument()
  })

  it('renders brand heading labels', () => {
    render(<DrinkCatalog drinks={ALL_DRINKS} selectedIds={NO_SELECTION} onSelect={vi.fn()} />)
    expect(screen.getByText('Starbucks')).toBeInTheDocument()
    expect(screen.getByText('Costa Coffee')).toBeInTheDocument()
  })

  it('renders the correct number of Starbucks drink cards', () => {
    render(<DrinkCatalog drinks={ALL_DRINKS} selectedIds={NO_SELECTION} onSelect={vi.fn()} />)
    const sbuxList = screen.getByRole('list', { name: /starbucks drinks/i })
    expect(sbuxList.querySelectorAll('li').length).toBe(STARBUCKS_DRINKS.length)
  })

  it('renders the correct number of Costa drink cards', () => {
    render(<DrinkCatalog drinks={ALL_DRINKS} selectedIds={NO_SELECTION} onSelect={vi.fn()} />)
    const costaList = screen.getByRole('list', { name: /costa coffee drinks/i })
    expect(costaList.querySelectorAll('li').length).toBe(COSTA_DRINKS.length)
  })

  it('shows empty state message for Starbucks when no drinks match', () => {
    render(
      <DrinkCatalog drinks={COSTA_DRINKS} selectedIds={NO_SELECTION} onSelect={vi.fn()} />
    )
    expect(screen.getByText(/no starbucks drinks match/i)).toBeInTheDocument()
  })

  it('shows empty state message for Costa when no drinks match', () => {
    render(
      <DrinkCatalog drinks={STARBUCKS_DRINKS} selectedIds={NO_SELECTION} onSelect={vi.fn()} />
    )
    expect(screen.getByText(/no costa drinks match/i)).toBeInTheDocument()
  })

  it('marks the selected Starbucks drink card as selected', () => {
    render(
      <DrinkCatalog
        drinks={ALL_DRINKS}
        selectedIds={{ starbucks: 'sbux-flat-white', costa: null }}
        onSelect={vi.fn()}
      />
    )
    // The selected card's button should show "✓ Selected"
    const selectedButtons = screen.getAllByRole('button', { name: /selected/i })
    expect(selectedButtons).toHaveLength(1)
  })

  it('marks the selected Costa drink card as selected', () => {
    render(
      <DrinkCatalog
        drinks={ALL_DRINKS}
        selectedIds={{ starbucks: null, costa: 'costa-flat-white' }}
        onSelect={vi.fn()}
      />
    )
    const selectedButtons = screen.getAllByRole('button', { name: /selected/i })
    expect(selectedButtons).toHaveLength(1)
  })

  it('calls onSelect when a drink card CTA is clicked', () => {
    const onSelect = vi.fn()
    render(<DrinkCatalog drinks={ALL_DRINKS} selectedIds={NO_SELECTION} onSelect={onSelect} />)
    const ctaButtons = screen.getAllByRole('button', { name: /select to compare/i })
    fireEvent.click(ctaButtons[0])
    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect).toHaveBeenCalledWith(STARBUCKS_DRINKS[0])
  })

  it('displays drink count for each brand section', () => {
    const SBUX_COUNT = 3
    const COSTA_COUNT = 2
    const sbuxDrinks: Drink[] = [
      ...STARBUCKS_DRINKS,
      {
        id: 'sbux-mocha',
        brand: 'starbucks',
        name: 'Mocha',
        category: 'hot',
        size_ml: 354,
        image: '/images/sbux-mocha.webp',
        nutrition: { calories_kcal: 290, sugar_g: 35, fat_g: 11, protein_g: 13, caffeine_mg: 175 },
      },
    ]
    render(
      <DrinkCatalog
        drinks={[...sbuxDrinks, ...COSTA_DRINKS]}
        selectedIds={NO_SELECTION}
        onSelect={vi.fn()}
      />
    )
    expect(screen.getByText(`(${SBUX_COUNT} drinks)`)).toBeInTheDocument()
    expect(screen.getByText(`(${COSTA_COUNT} drinks)`)).toBeInTheDocument()
  })

  it('renders both selected drink cards when both brands have selections', () => {
    render(
      <DrinkCatalog
        drinks={ALL_DRINKS}
        selectedIds={{ starbucks: 'sbux-flat-white', costa: 'costa-flat-white' }}
        onSelect={vi.fn()}
      />
    )
    const selectedButtons = screen.getAllByRole('button', { name: /selected/i })
    expect(selectedButtons).toHaveLength(2)
  })
})
