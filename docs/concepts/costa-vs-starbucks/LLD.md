The LLD has been written to `docs/concepts/costa-vs-starbucks/LLD.md`. Here's a summary of what was covered:

**Key design decisions captured:**

- **File structure** — 14 source files under `src/` plus `public/data/` JSON and `public/images/`; minimal, no over-engineering
- **Component designs** — Props interfaces and render logic for all 6 components from the HLD (`DrinkCard`, `DrinkCatalog`, `ComparisonPanel`, `NutritionBar`, `FilterBar`, `SearchBox`)
- **Types** — Full TypeScript schema in `src/types.ts` matching the HLD data model exactly
- **State** — All 6 state values in a single table; confirms `useState` in `App.tsx` with no external store
- **Function signatures** — `useDrinks`, `filterDrinks`, all 4 `App` handlers, and `getNutritionRows`
- **Error handling** — 5 failure scenarios covered (fetch fail, malformed JSON, image 404, empty search, duplicate brand selection guard)
- **Test plan** — 7 unit tests (Vitest), 4 integration tests, 5 E2E tests (Playwright + Lighthouse CI)
- **Migration** — 8-step greenfield setup sequence
- **Performance** — Bundle target <150 kB gzipped, lazy images, `.webp`, CDN cache headers