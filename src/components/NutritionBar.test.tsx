import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { NutritionBar } from './NutritionBar'

describe('NutritionBar', () => {
  it('renders the nutrient label', () => {
    render(
      <NutritionBar label="Calories" starbucksValue={160} costaValue={144} unit="kcal" />
    )
    expect(screen.getByText('Calories')).toBeInTheDocument()
  })

  it('renders both Starbucks and Costa brand labels', () => {
    render(
      <NutritionBar label="Sugar" starbucksValue={14} costaValue={12} unit="g" />
    )
    expect(screen.getByText('Starbucks')).toBeInTheDocument()
    expect(screen.getByText('Costa')).toBeInTheDocument()
  })

  it('renders starbucks and costa values with unit', () => {
    render(
      <NutritionBar label="Calories" starbucksValue={160} costaValue={144} unit="kcal" />
    )
    expect(screen.getByText(/160 kcal/)).toBeInTheDocument()
    expect(screen.getByText(/144 kcal/)).toBeInTheDocument()
  })

  it('renders two meter elements for the bars', () => {
    render(
      <NutritionBar label="Fat" starbucksValue={6} costaValue={8} unit="g" />
    )
    const meters = screen.getAllByRole('meter')
    expect(meters).toHaveLength(2)
  })

  it('renders a data-testid="nutrition-bar" wrapper', () => {
    render(
      <NutritionBar label="Caffeine" starbucksValue={130} costaValue={185} unit="mg" />
    )
    expect(screen.getByTestId('nutrition-bar')).toBeInTheDocument()
  })

  it('highlights the lower starbucks value when lowerIsBetter (default)', () => {
    render(
      <NutritionBar label="Calories" starbucksValue={100} costaValue={200} unit="kcal" />
    )
    // The starbucks value text should have the winner (bold) class
    const starbucksValueEl = screen.getByText(/100 kcal/)
    expect(starbucksValueEl.className).toContain('font-bold')
  })

  it('highlights the lower costa value when lowerIsBetter (default)', () => {
    render(
      <NutritionBar label="Sugar" starbucksValue={20} costaValue={10} unit="g" />
    )
    const costaValueEl = screen.getByText(/10 g/)
    expect(costaValueEl.className).toContain('font-bold')
  })

  it('highlights the higher starbucks value when lowerIsBetter=false (protein)', () => {
    render(
      <NutritionBar label="Protein" starbucksValue={9} costaValue={8} unit="g" lowerIsBetter={false} />
    )
    const starbucksValueEl = screen.getByText(/9 g/)
    expect(starbucksValueEl.className).toContain('font-bold')
  })

  it('neither value is bolded on a tie', () => {
    render(
      <NutritionBar label="Fat" starbucksValue={5} costaValue={5} unit="g" />
    )
    // Both value spans should NOT contain the winner bold class
    const valueEls = screen.getAllByText(/5 g/)
    valueEls.forEach((el) => {
      expect(el.className).not.toContain('font-bold')
    })
  })

  it('sets starbucks bar width to 100% when starbucks has the higher value', () => {
    const { container } = render(
      <NutritionBar label="Calories" starbucksValue={200} costaValue={100} unit="kcal" />
    )
    const bars = container.querySelectorAll('[style]')
    // First styled bar is starbucks (rendered first) — should be 100%
    const sbuxBar = bars[0] as HTMLElement
    expect(sbuxBar.style.width).toBe('100%')
  })

  it('sets bar width proportionally when values differ', () => {
    const { container } = render(
      <NutritionBar label="Calories" starbucksValue={200} costaValue={100} unit="kcal" />
    )
    const bars = container.querySelectorAll('[style]')
    // Second styled bar is costa — should be 50%
    const costaBar = bars[1] as HTMLElement
    expect(costaBar.style.width).toBe('50%')
  })

  it('sets both bars to 0% when both values are 0', () => {
    const { container } = render(
      <NutritionBar label="Caffeine" starbucksValue={0} costaValue={0} unit="mg" />
    )
    const bars = container.querySelectorAll('[style]')
    ;(Array.from(bars) as HTMLElement[]).forEach((bar) => {
      expect(bar.style.width).toBe('0%')
    })
  })
})
