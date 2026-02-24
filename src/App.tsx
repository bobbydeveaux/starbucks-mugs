import { useState } from 'react'
import type { Drink, ComparisonState } from './types'
import { DrinkCatalog } from './components/DrinkCatalog'

// Sample mock data for development (real data will come from useDrinks hook)
const MOCK_DRINKS: Drink[] = [
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
    id: 'sbux-latte',
    brand: 'starbucks',
    name: 'Caffè Latte',
    category: 'hot',
    size_ml: 354,
    image: '/images/sbux-latte.webp',
    nutrition: { calories_kcal: 190, sugar_g: 17, fat_g: 7, protein_g: 12, caffeine_mg: 150 },
  },
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
    id: 'costa-latte',
    brand: 'costa',
    name: 'Latte',
    category: 'hot',
    size_ml: 354,
    image: '/images/costa-latte.webp',
    nutrition: { calories_kcal: 170, sugar_g: 16, fat_g: 6, protein_g: 11, caffeine_mg: 185 },
  },
]

function App() {
  const [comparison, setComparison] = useState<ComparisonState>({
    starbucks: null,
    costa: null,
  })

  function handleSelect(drink: Drink) {
    setComparison((prev) => ({
      ...prev,
      [drink.brand]: prev[drink.brand]?.id === drink.id ? null : drink,
    }))
  }

  const selectedIds = {
    starbucks: comparison.starbucks?.id ?? null,
    costa: comparison.costa?.id ?? null,
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white shadow-sm">
        <div className="mx-auto max-w-7xl px-4 py-6">
          <h1 className="text-3xl font-bold text-gray-900">
            Costa <span className="text-gray-400">vs</span> Starbucks
          </h1>
          <p className="mt-1 text-gray-500">Compare drinks side by side</p>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-4 py-8">
        <DrinkCatalog
          drinks={MOCK_DRINKS}
          selectedIds={selectedIds}
          onSelect={handleSelect}
        />
      </main>
    </div>
  )
}

export default App
