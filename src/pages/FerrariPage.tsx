/** Stub page for the Ferrari catalog — full implementation in feat-car-catalog sprint. */
export function FerrariPage() {
  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-ferrari-red shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
          <h1 className="text-3xl font-bold text-white">Ferrari Catalog</h1>
          <p className="mt-1 text-red-100">
            Every production Ferrari from 1947 to the present day.
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
