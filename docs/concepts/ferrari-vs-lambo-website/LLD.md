264 lines — well within the 400-line limit. The LLD has been written to `docs/concepts/ferrari-vs-lambo-website/LLD.md`.

Key decisions reflected in the document:

- **Mirrors `useDrinks` pattern exactly** — `useCarCatalog` uses `fetch('/data/ferrari.json')` from `public/data/` (not Vite static imports) to stay consistent with the existing scaffold
- **Additive changes only** — `src/types.ts` gets car types appended; existing `Drink`/`Brand` types are untouched; Costa vs Starbucks UI stays at route `/`
- **`tailwind.config.ts` extension** — `ferrari-red: #DC143C` and `lambo-yellow: #FFC72C` added alongside existing `starbucks`/`costa` tokens
- **`react-router-dom@6`** is the only new dependency
- **`eraMatchSuggestion`** is a pure utility function with its own test file, keeping comparison logic isolated from hook state
- **Test plan** covers unit, integration (React Testing Library + fake timers for debounce), and E2E (Playwright) proportional to the project size