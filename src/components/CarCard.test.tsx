import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { CarCard } from './CarCard'
import type { CarModel } from '../types'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const mockFerrari: CarModel = {
  id: 'ferrari-testarossa-1984',
  brand: 'ferrari',
  model: 'Testarossa',
  year: 1984,
  decade: 1980,
  image: '/images/ferrari/testarossa.jpg',
  price: 87000,
  specs: {
    hp: 390,
    torqueLbFt: 362,
    zeroToSixtyMs: 5.2,
    topSpeedMph: 181,
    engineConfig: 'Flat-12, 4.9L',
  },
  eraRivals: ['lamborghini-countach-lp500s-1982'],
}

const mockLambo: CarModel = {
  id: 'lamborghini-countach-lp500s-1982',
  brand: 'lamborghini',
  model: 'Countach LP500S',
  year: 1982,
  decade: 1980,
  image: '/images/lamborghini/countach-lp500s.jpg',
  specs: {
    hp: 375,
    torqueLbFt: 268,
    zeroToSixtyMs: 4.9,
    topSpeedMph: 183,
    engineConfig: 'V12, 4.8L',
  },
  eraRivals: ['ferrari-testarossa-1984'],
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('CarCard', () => {
  it('renders the car model name', () => {
    render(<CarCard car={mockFerrari} isSelected={false} onSelect={vi.fn()} />)
    expect(screen.getByText('Testarossa')).toBeInTheDocument()
  })

  it('renders the car year', () => {
    render(<CarCard car={mockFerrari} isSelected={false} onSelect={vi.fn()} />)
    expect(screen.getByText('1984')).toBeInTheDocument()
  })

  it('renders a decade badge', () => {
    render(<CarCard car={mockFerrari} isSelected={false} onSelect={vi.fn()} />)
    expect(screen.getByText('1980s')).toBeInTheDocument()
  })

  it('renders all six stats: HP, torque, 0-60, top speed, engine config, and image', () => {
    render(<CarCard car={mockFerrari} isSelected={false} onSelect={vi.fn()} />)
    expect(screen.getByText(/390/)).toBeInTheDocument()
    expect(screen.getByText(/362 lb-ft/)).toBeInTheDocument()
    expect(screen.getByText(/5.2s/)).toBeInTheDocument()
    expect(screen.getByText(/181 mph/)).toBeInTheDocument()
    expect(screen.getByText(/Flat-12, 4\.9L/)).toBeInTheDocument()
    const img = screen.getByRole('img')
    expect(img).toBeInTheDocument()
  })

  it('renders car image with lazy loading', () => {
    render(<CarCard car={mockFerrari} isSelected={false} onSelect={vi.fn()} />)
    const img = screen.getByRole('img', { name: /Testarossa 1984/i })
    expect(img).toHaveAttribute('src', '/images/ferrari/testarossa.jpg')
    expect(img).toHaveAttribute('loading', 'lazy')
  })

  it('renders "Select to Compare" CTA button when not selected', () => {
    render(<CarCard car={mockFerrari} isSelected={false} onSelect={vi.fn()} />)
    const btn = screen.getByRole('button', { name: /select to compare/i })
    expect(btn).toBeInTheDocument()
  })

  it('renders "✓ Selected" CTA when selected', () => {
    render(<CarCard car={mockFerrari} isSelected={true} onSelect={vi.fn()} />)
    const btn = screen.getByRole('button')
    expect(btn).toHaveTextContent('✓ Selected')
  })

  it('calls onSelect with the car when CTA is clicked', () => {
    const onSelect = vi.fn()
    render(<CarCard car={mockFerrari} isSelected={false} onSelect={onSelect} />)
    fireEvent.click(screen.getByRole('button'))
    expect(onSelect).toHaveBeenCalledTimes(1)
    expect(onSelect).toHaveBeenCalledWith(mockFerrari)
  })

  it('sets aria-pressed=true on the button when selected', () => {
    render(<CarCard car={mockFerrari} isSelected={true} onSelect={vi.fn()} />)
    const btn = screen.getByRole('button')
    expect(btn).toHaveAttribute('aria-pressed', 'true')
  })

  it('sets aria-pressed=false on the button when not selected', () => {
    render(<CarCard car={mockFerrari} isSelected={false} onSelect={vi.fn()} />)
    const btn = screen.getByRole('button')
    expect(btn).toHaveAttribute('aria-pressed', 'false')
  })

  it('sets data-selected=true on article when selected', () => {
    const { container } = render(
      <CarCard car={mockFerrari} isSelected={true} onSelect={vi.fn()} />
    )
    const article = container.querySelector('article')
    expect(article).toHaveAttribute('data-selected', 'true')
  })

  it('sets data-selected=false on article when not selected', () => {
    const { container } = render(
      <CarCard car={mockFerrari} isSelected={false} onSelect={vi.fn()} />
    )
    const article = container.querySelector('article')
    expect(article).toHaveAttribute('data-selected', 'false')
  })

  it('applies ferrari-red border class for Ferrari cars', () => {
    const { container } = render(
      <CarCard car={mockFerrari} isSelected={false} onSelect={vi.fn()} />
    )
    const article = container.querySelector('article')
    expect(article?.className).toContain('border-ferrari-red')
  })

  it('applies lambo-yellow border class for Lamborghini cars', () => {
    const { container } = render(
      <CarCard car={mockLambo} isSelected={false} onSelect={vi.fn()} />
    )
    const article = container.querySelector('article')
    expect(article?.className).toContain('border-lambo-yellow')
  })

  it('applies selected ring class when isSelected is true (Ferrari)', () => {
    const { container } = render(
      <CarCard car={mockFerrari} isSelected={true} onSelect={vi.fn()} />
    )
    const article = container.querySelector('article')
    expect(article?.className).toContain('ring-ferrari-red')
  })

  it('applies selected ring class when isSelected is true (Lamborghini)', () => {
    const { container } = render(
      <CarCard car={mockLambo} isSelected={true} onSelect={vi.fn()} />
    )
    const article = container.querySelector('article')
    expect(article?.className).toContain('ring-lambo-yellow')
  })
})
