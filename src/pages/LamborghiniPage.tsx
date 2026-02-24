/** Stub page for the Lamborghini catalog — full implementation in feat-car-catalog sprint. */
export function LamborghiniPage() {
  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-lambo-yellow shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <h1 className="text-3xl font-bold text-gray-900">Lamborghini Catalog</h1>
          <p className="mt-1 text-yellow-800">
            Every production Lamborghini from 1963 to the present day.
          </p>
        </div>
      </header>
      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <p className="text-gray-500">
          Car catalog coming in Sprint 2 — feat-car-catalog.
        </p>
      </main>
    </div>
  );
}
