# Sprint Review: petrol-vs-ev-cost-comparison-website-sprint-1

**Date:** 2026-03-13
**Sprint Duration:** 2026-03-13T12:10:41Z → 2026-03-13T12:28:14Z (18 minutes)
**Namespace:** coo-petrol-vs-ev-cost-comparison-website
**Phase:** Completed

---

## 1. Executive Summary

Sprint 1 of the Petrol vs EV Cost Comparison Website delivered all three planned backend tasks on time and without retries, achieving an 88% overall sprint completion score. The sprint established the foundational data layer (PostgreSQL migrations for `vehicles` and `pricing_defaults` tables) and the core client-side calculation engine (`CostEngine` TypeScript module with 100% test coverage). Two code review cycles were completed within the sprint window, with one review initially flagging a missing implementation before the engineer delivered the full solution. All six tasks — three engineering and three review — are now merged or approved.

---

## 2. Achievements

### Database Schema Foundation (Issue #391 → PR #402)
- Migration `005_vehicles.up.sql` creates a fully typed `vehicles` table supporting petrol, diesel, EV, hybrid, and PHEV records with separate efficiency columns (`mpg_combined`, `mpg_city`, `mpg_motorway`, `efficiency_mpkwh`, `battery_kwh`, `wltp_range_mi`, `co2_gkm`).
- Migration `006_pricing_defaults.up.sql` creates a `pricing_defaults` config table covering nine distinct charging/fuel tariffs (standard home, Economy 7, Octopus Go, OVO Drive Anytime, public slow/rapid/ultra-rapid) seeded with representative UK March 2026 pricing.
- Both migrations include clean `DOWN` rollback scripts and a composite index on `(make, model, year, fuel_type)`.

### CostEngine Implementation (Issue #392 → PR #399)
- Six pure, stateless TypeScript functions with explicit typed parameter interfaces:
  - `iceCostPerMile` — exact `4.546` L/gal constant
  - `evCostPerMile` — pence/mile from electricity tariff
  - `annualCost` — fuel spend from cost-per-mile × mileage
  - `iceCo2PerMile` — WLTP g/km → g/mile via `× 1.60934`
  - `evCo2PerMile` — UK grid average `233 g/kWh`
  - `breakevenYears` — returns `Infinity` when savings ≤ 0
- Zero/negative input guards prevent division-by-zero errors throughout.

### CostEngine Test Suite (Issue #393 → PR #400)
- 42 Vitest unit tests across all six functions.
- **100% coverage** on all four Istanbul metrics (statements 24/24, branches 14/14, functions 6/6, lines 24/24) — well above the ≥90% requirement.
- Coverage threshold enforced as a hard CI gate in `vite.config.ts`.

---

## 3. Challenges

**Review cycle on PR #400** — The code-reviewer correctly identified that PR #400 was submitted as a draft with no code changes: the `src/petrol-vs-ev/` directory, `costEngine.test.ts`, and its dependency `costEngine.ts` were all absent at first review. This was a task sequencing issue — the test task (#393) was opened before the implementation (#392) was committed. The fix was rapid and resolved within the sprint with no retry recorded.

**Conflict resolution required** — Three files (`costEngine.ts`, `costEngine.test.ts`, `.review-feedback.txt`) required AI-assisted merge conflict resolution. In all cases, `origin/main` was chosen as it contained the more complete implementation (TypeScript param interfaces, input validation, and the missing `iceCo2PerMile` function). This suggests the working branch diverged significantly before merge.

**Sprint completion at 88%** — All tasks are complete but the score is 88%, likely reflecting the review cycle overhead and conflict resolution. The 14-minute duration for Issue #392 (vs. a 6-minute average) is the primary outlier.

---

## 4. Worker Performance

| Worker | Tasks | Retries | Review Cycles | Notes |
|---|---|---|---|---|
| backend-engineer | 3 | 0 | 2 | DB schema delivered cleanly in 9m; CostEngine took 14m but produced high-quality, well-typed code; tests hit 100% coverage in 6m |
| code-reviewer | 3 | 0 | 0 | Avg ~1m40s per review; correctly blocked PR #400 for missing implementation; fast turnaround on #399 and #402 |

Both workers handled equal task counts. The backend-engineer accounted for ~85% of total task time; the code-reviewer ran largely in parallel. Future sprints with more tasks may benefit from a second engineer to reduce queue depth.

---

## 5. Recommendations

1. **Enforce dependency gates at PR creation** — Block PR submission for tasks with declared `Dependencies` until the upstream PR is merged, to prevent the PR #400 sequencing issue from recurring.

2. **Rebase branches on `main` at task start** — Three conflict resolutions in a single sprint suggests branches diverged early. Short-lived branches rebased on `main` before work begins will reduce conflict surface area.

3. **Update task spec to list six functions** — `tasks.yaml` acceptance criteria reference "five calculation functions" but six were correctly delivered. Update the spec to avoid reviewer ambiguity in future sprints.

4. **Sprint 2 API-before-tests ordering** — Ensure `feat-vehicle-api-1` and `feat-pricing-api-1` are merged before the QA engineer starts `feat-vehicle-api-2`, mirroring the lesson from Issue #393.

5. **Consider a second backend engineer for Sprint 2** — Sprint 2 has five tasks vs three in Sprint 1, with four assigned to the backend-engineer role. Adding a second engineer would parallelize delivery and reduce the critical path.

---

## 6. Metrics Summary

| Metric | Value |
|---|---|
| Sprint Duration | 18 minutes |
| Total Tasks | 6 (3 engineering, 3 review) |
| Completed | 6 |
| Failed / Blocked | 0 / 0 |
| Sprint Completion Score | 88% |
| First-Time-Right Rate | 100% |
| Total Retries | 0 |
| Total Review Cycles | 2 |
| Merge Conflicts Resolved | 3 files (AI-assisted) |
| Average Task Duration | 6m 0s |
| Longest Task | Issue #392 — CostEngine Implementation (14m) |
| Shortest Task | PR #400 Review (1m) |

### Test Coverage — `costEngine.ts`

| Metric | Result |
|---|---|
| Statements | 100% (24/24) |
| Branches | 100% (14/14) |
| Functions | 100% (6/6) |
| Lines | 100% (24/24) |

---

The full review document has been saved to `sprint-review.md` in the repository root.