function App() {
  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header with brand colour tokens smoke test */}
      <header className="flex items-center justify-between px-6 py-4 shadow-sm bg-white">
        <div className="flex items-center gap-3">
          <span className="inline-block w-4 h-4 rounded-full bg-starbucks" aria-hidden="true" />
          <span className="font-semibold text-starbucks">Starbucks</span>
        </div>
        <h1 className="text-xl font-bold text-gray-800">Costa vs Starbucks</h1>
        <div className="flex items-center gap-3">
          <span className="font-semibold text-costa">Costa</span>
          <span className="inline-block w-4 h-4 rounded-full bg-costa" aria-hidden="true" />
        </div>
      </header>

      {/* Brand colour showcase */}
      <main className="max-w-4xl mx-auto px-6 py-12">
        <p className="text-center text-gray-500 mb-8">
          Drink comparison coming soon — project setup in progress.
        </p>
        <div className="grid grid-cols-2 gap-6">
          <div className="rounded-xl p-6 bg-starbucks text-white text-center shadow-md">
            <p className="text-sm uppercase tracking-widest opacity-75 mb-2">Brand colour</p>
            <p className="text-2xl font-bold">Starbucks</p>
            <p className="text-sm opacity-75 mt-1">#00704A</p>
          </div>
          <div className="rounded-xl p-6 bg-costa text-white text-center shadow-md">
            <p className="text-sm uppercase tracking-widest opacity-75 mb-2">Brand colour</p>
            <p className="text-2xl font-bold">Costa</p>
            <p className="text-sm opacity-75 mt-1">#6B1E1E</p>
          </div>
        </div>
      </main>
    </div>
  )
}

export default App
