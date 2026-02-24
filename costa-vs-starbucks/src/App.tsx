function App() {
  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <div className="flex items-center gap-4">
            <span className="text-2xl font-bold text-starbucks">Costa</span>
            <span className="text-gray-400 text-xl">vs</span>
            <span className="text-2xl font-bold text-costa">Starbucks</span>
          </div>
          <p className="mt-1 text-sm text-gray-500">
            Compare drinks side-by-side with full nutritional information
          </p>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <p className="text-gray-600">Coming soon — drink catalog and comparison panel.</p>
      </main>
    </div>
  )
}

export default App
