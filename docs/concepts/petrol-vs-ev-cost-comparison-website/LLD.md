The LLD has been written to `docs/concepts/petrol-vs-ev-cost-comparison-website/LLD.md`.

Key decisions reflected in the document:

- **File structure** follows the `what-s-the-temp/` sub-app pattern from the existing repo, placing the new feature in `petrol-vs-ev/`.
- **API handlers** live in `api/` at the repo root, matching Vercel's conventions and the existing `vercel.json`.
- **Existing components reused**: `useCarCatalog`, `SearchBar`, `SearchBox`, `ComparisonPanel` — extended via props rather than forked.
- **DB migrations** numbered `005`/`006` to continue the existing `db/migrations/` sequence.
- **CostEngine** is a pure TS module with full function signatures and ≥90% test coverage target.
- **URL state** uses short param keys to keep shareable URLs compact.
- **Rollback** is clean — both new migrations have down scripts, and new routes can be removed without affecting any existing pages.