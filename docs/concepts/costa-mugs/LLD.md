The LLD has been written to `docs/concepts/costa-mugs/LLD.md`. Key decisions:

- **Implementation**: mirrors the existing Starbucks mugs `app.js` pattern exactly — same function structure (`loadMugs`, `createCard`, `renderCards`, `openModal`, `closeModal`), with `filterMugs` and `applyFilters` added for search/filter support.
- **Data**: `data/mugs.json` uses the versioned envelope `{version, mugs[]}` with fields `id, name, series, region, material, price_usd, image_url, description`.
- **Filter**: text search (name/series/region, case-insensitive) + series dropdown, AND-combined, pure function for testability.
- **Error handling**: fetch failure renders an error message in `#grid`; image 404s fall back to `images/placeholder.svg`.
- **Tests**: unit tests on `filterMugs`, integration tests on load/filter pipeline, manual E2E checklist.