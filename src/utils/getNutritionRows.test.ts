import { describe, it, expect } from 'vitest'
import { getNutritionRows } from './getNutritionRows'
import type { Drink } from '../types'

const costaDrink: Drink = {
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

const starbucksDrink: Drink = {
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

describe('getNutritionRows', () => {
  it('returns exactly 5 rows — one per nutritional field', () => {
    const rows = getNutritionRows(costaDrink, starbucksDrink)
    expect(rows).toHaveLength(5)
  })

  it('returns rows with the correct labels in order', () => {
    const rows = getNutritionRows(costaDrink, starbucksDrink)
    const labels = rows.map((r) => r.label)
    expect(labels).toEqual(['Calories', 'Sugar', 'Fat', 'Protein', 'Caffeine'])
  })

  it('maps costa drink nutrition values correctly', () => {
    const rows = getNutritionRows(costaDrink, starbucksDrink)
    expect(rows[0].costaValue).toBe(144)  // calories_kcal
    expect(rows[1].costaValue).toBe(12)   // sugar_g
    expect(rows[2].costaValue).toBe(8)    // fat_g
    expect(rows[3].costaValue).toBe(8)    // protein_g
    expect(rows[4].costaValue).toBe(185)  // caffeine_mg
  })

  it('maps starbucks drink nutrition values correctly', () => {
    const rows = getNutritionRows(costaDrink, starbucksDrink)
    expect(rows[0].starbucksValue).toBe(160) // calories_kcal
    expect(rows[1].starbucksValue).toBe(14)  // sugar_g
    expect(rows[2].starbucksValue).toBe(6)   // fat_g
    expect(rows[3].starbucksValue).toBe(9)   // protein_g
    expect(rows[4].starbucksValue).toBe(130) // caffeine_mg
  })

  it('includes the correct unit for each row', () => {
    const rows = getNutritionRows(costaDrink, starbucksDrink)
    expect(rows[0].unit).toBe('kcal')
    expect(rows[1].unit).toBe('g')
    expect(rows[2].unit).toBe('g')
    expect(rows[3].unit).toBe('g')
    expect(rows[4].unit).toBe('mg')
  })

  it('each row has label, costaValue, starbucksValue, and unit fields', () => {
    const rows = getNutritionRows(costaDrink, starbucksDrink)
    for (const row of rows) {
      expect(row).toHaveProperty('label')
      expect(row).toHaveProperty('costaValue')
      expect(row).toHaveProperty('starbucksValue')
      expect(row).toHaveProperty('unit')
      expect(typeof row.label).toBe('string')
      expect(typeof row.costaValue).toBe('number')
      expect(typeof row.starbucksValue).toBe('number')
      expect(typeof row.unit).toBe('string')
    }
  })
})
