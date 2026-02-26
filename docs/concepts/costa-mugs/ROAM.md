The ROAM analysis has been written to `docs/concepts/costa-mugs/ROAM.md`. Here is a summary of what was filled in:

**Risks (7 identified):**
- **High**: Missing mug image assets (only `.gitkeep` in `images/`); no Costa mug catalog data exists yet
- **Medium**: Dependency on Starbucks `app.js` reference correctness; `fetch()` failure when opened via `file://`; `data/` directory not yet created; image URL rot if external URLs are used
- **Low**: Data staleness with no update workflow

**Obstacles (4):**
- `data/mugs.json` does not exist — hard blocker for end-to-end testing
- No mug images on disk — v1 image strategy undecided
- `data/` subdirectory not yet created in the repo
- Starbucks `app.js` signatures not validated against Costa LLD

**Assumptions (5):**
- Existing `app.js` matches LLD function signatures
- Placeholder SVG fallback is acceptable at v1 launch
- Costa mug data can be sourced publicly
- Site will be served via HTTP, not `file://`
- Target browsers support Fetch API and ES2020 natively

**Mitigations:** Concrete, per-risk action items — including making `costa-mugs-feat-catalog-data` a hard gate before UI work, implementing `img.onerror` as the first code change, creating the `data/` directory as the first commit, and adding a dev setup note to the README for the `file://` fetch issue.