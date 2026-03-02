function App() {
  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white shadow-sm">
        <div className="max-w-4xl mx-auto px-4 py-6">
          <h1 className="text-3xl font-bold text-gray-900">What's the Temp?</h1>
          <p className="mt-1 text-gray-500">
            Find countries to visit in your ideal temperature range
          </p>
        </div>
      </header>
      <main className="max-w-4xl mx-auto px-4 py-8">
        <p className="text-gray-600">Loading…</p>
      </main>
    </div>
  )
}

export default App
