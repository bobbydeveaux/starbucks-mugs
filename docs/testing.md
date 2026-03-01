# Testing Guide

This document describes the testing approach and conventions used in the Costa vs Starbucks and Ferrari vs Lamborghini projects.

---

## Testing Stack

- **Test Framework:** [Vitest](https://vitest.dev/) (fast, ESM-native test runner)
- **Component Testing:** [React Testing Library](https://testing-library.com/react)
- **DOM Environment:** [jsdom](https://github.com/jsdom/jsdom)
- **Mocking:** [Vitest's `vi` utilities](https://vitest.dev/api/vi.html)

### Configuration

**File:** `vite.config.ts`

```typescript
test: {
  environment: 'jsdom',
  globals: true,
  setupFiles: ['./src/setupTests.ts'],
  css: false,
  include: ['src/**/*.{test,spec}.{ts,tsx}'],
}
```

---

## Unit & Component Tests

All unit and component tests follow the pattern: `src/**/*.{test,spec}.{ts,tsx}`

### Structure

Tests are colocated with their source files:

```
src/
├── components/
│   ├── CarCard.tsx
│   ├── CarCard.test.tsx          ← test file colocated
│   ├── CatalogPage.tsx
│   └── CatalogPage.test.tsx
├── hooks/
│   ├── useCarCatalog.ts
│   └── useCarCatalog.test.ts
└── utils/
    ├── filterDrinks.ts
    └── filterDrinks.test.ts
```

### Running Tests

```bash
# Run all tests once
npm test

# Watch mode
npm test:watch

# UI dashboard
npm test:ui

# Run specific test file
npm test -- src/components/CarCard.test.tsx
```

---

## E2E Integration Tests

**Location:** `src/integration/`

E2E and integration tests use the same Vitest framework but may use different testing patterns (e.g., direct filesystem access, data loading).

### Image Loading E2E Tests

**File:** `src/integration/images.e2e.test.ts`

Verifies that all car images load correctly from the filesystem.

#### Acceptance Criteria

1. **All 58 Ferrari images load** via `/images/ferrari/*` (HTTP 200)
2. **All 42 Lamborghini images load** via `/images/lamborghini/*` (HTTP 200)
3. **Missing images return HTTP 404**
4. **E2E test suite passes without failures**

#### Test Organization

```typescript
describe('Image Loading E2E Tests', () => {
  describe('Ferrari Catalog Images', () => {
    it('should load exactly 58 Ferrari models', () => { ... })
    it('all Ferrari models should have valid imageUrl format', () => { ... })
    it('all 58 Ferrari images should be accessible (HTTP 200)', () => { ... })
    // ... more tests
  })

  describe('Lamborghini Catalog Images', () => {
    // ... similar tests for Lamborghini (42 models)
  })

  describe('Missing Image Handling', () => {
    it('non-existent Ferrari images should return HTTP 404', () => { ... })
    // ... more tests
  })

  describe('Overall Image Catalog Validation', () => {
    it('should verify the complete image catalog (58 + 42 = 100 total)', () => { ... })
    // ... more tests
  })
})
```

#### Image Files

Placeholder PNG images are stored in:

- `public/images/ferrari/` — 58 files (one per model)
- `public/images/lamborghini/` — 42 files (one per model)

Each file is a minimal 1×1 transparent PNG (70 bytes).

#### Running Image Tests

```bash
# Run only image E2E tests
npm test -- src/integration/images.e2e.test.ts

# Run with output
npm test -- src/integration/images.e2e.test.ts --reporter=verbose
```

#### Expected Output

```
✓ Image Loading E2E Tests (14 tests)
  ✓ All 58 Ferrari images loaded successfully (HTTP 200)
  ✓ All 42 Lamborghini images loaded successfully (HTTP 200)
  ✓ Complete image catalog verified: 100 total models (58 Ferrari + 42 Lamborghini)
```

---

## Test Data

### Static Catalog Data

Car data is stored as JSON:

- `public/data/ferrari.json` — 58 Ferrari models with specs, images, era rivals
- `public/data/lamborghini.json` — 42 Lamborghini models with specs, images, era rivals

Each model includes:
- `id` — slug identifier
- `model` — display name
- `year` — production year
- `decade` — decade bucket (1950, 1960, etc.)
- `imageUrl` — path to image (e.g., `/images/ferrari/testarossa.jpg`)
- `specs` — performance specs (HP, torque, 0–60, top speed, engine)
- `eraRivals` — contemporaneous models from the opposing brand

### Mocking Fetch Calls

Tests that fetch JSON data mock the Fetch API:

```typescript
import { vi } from 'vitest';

beforeEach(() => {
  global.fetch = vi.fn((url: string) => {
    if (url === '/data/ferrari.json') {
      return Promise.resolve({
        ok: true,
        json: () => Promise.resolve(ferrariMockData),
      });
    }
    // ... more mock responses
  });
});
```

---

## Naming Conventions

### Test Files

- `ComponentName.test.tsx` for component tests
- `hookName.test.ts` for hook tests
- `utilityName.test.ts` for utility function tests
- `feature.e2e.test.ts` for E2E / integration tests

### Test Names

Use clear, descriptive test names that read like requirements:

```typescript
✓ should render the car model name
✓ renders all six stats: HP, torque, 0–60, top speed, engine config, and image
✓ all 58 Ferrari images should be accessible (HTTP 200)
✗ should fail gracefully when images are missing
```

Avoid vague names like `"test rendering"` or `"works correctly"`.

### Test Helpers

Extract reusable test utilities into separate files:

- `src/test/fixtures/cars.ts` — mock car data
- `src/test/fixtures/drinks.ts` — mock drink data
- `src/test/helpers/render.tsx` — custom render function with providers

---

## Best Practices

### 1. Test User Behavior, Not Implementation

❌ **Don't:**
```typescript
it('sets isSelected state to true', () => {
  const { container } = render(<CarCard ... />);
  expect(component.state.isSelected).toBe(true);
});
```

✅ **Do:**
```typescript
it('renders "✓ Selected" CTA when selected', () => {
  render(<CarCard ... isSelected={true} />);
  expect(screen.getByRole('button')).toHaveTextContent('✓ Selected');
});
```

### 2. Use Semantic Queries

Prefer queries that match user-visible semantics:

```typescript
// Good — user sees a button with this text
screen.getByRole('button', { name: /select to compare/i })

// Good — user sees this heading
screen.getByRole('heading', { name: /ferrari catalog/i })

// Avoid — implementation detail
screen.getByTestId('car-card-container')
```

### 3. Avoid Act Warnings

Always wrap state updates in `act()`:

```typescript
import { act } from 'react-dom/test-utils';

it('filters cars when decade is selected', () => {
  const { getByRole } = render(<CatalogPage />);

  act(() => {
    fireEvent.click(getByRole('button', { name: /1980s/i }));
  });

  expect(screen.getByText('1980s cars')).toBeInTheDocument();
});
```

### 4. Test Accessibility

Use accessible selectors (`role`, `aria-*`) in tests:

```typescript
// Accessible
screen.getByRole('img', { name: /testarossa 1984/i })
screen.getByRole('button', { pressed: true })

// Less accessible
screen.getByTestId('car-image')
screen.getByClassName('car-card--selected')
```

### 5. Keep Tests Small and Focused

One logical behavior per test:

```typescript
// ✓ Focused
it('renders car brand in heading', () => {
  render(<CarCard car={mockFerrari} ... />);
  expect(screen.getByText('Ferrari')).toBeInTheDocument();
});

// ✗ Too broad
it('renders correctly', () => {
  render(<CarCard car={mockFerrari} ... />);
  expect(...).toBeDefined(); // many assertions
});
```

---

## Debugging Tests

### 1. View Rendered HTML

```typescript
import { screen, render } from '@testing-library/react';

it('renders the car card', () => {
  const { debug } = render(<CarCard ... />);
  debug(); // prints the entire DOM to console
});
```

### 2. Print Accessible Roles

```typescript
import { screen } from '@testing-library/react';

it('example', () => {
  render(<CarCard ... />);
  screen.logTestingPlaygroundURL(); // outputs a test playground link
});
```

### 3. Run Tests in Watch Mode

```bash
npm test:watch
# Press 'p' to filter by filename
# Press 't' to filter by test name
# Press 'w' for more options
```

### 4. Run a Single Test

```bash
# Inline skip/only in the test
it.only('this test runs alone', () => { ... })

# Or run with pattern
npm test -- --grep "should render car model name"
```

---

## CI/CD Integration

Tests run automatically in GitHub Actions on:

- **Push to `main`**
- **Pull request**
- **Pre-commit** (via husky hooks, if configured)

See `.github/workflows/` for CI configuration.

---

## Coverage

Generate coverage report:

```bash
npm test -- --coverage
```

Coverage is checked in CI and reported to PR comments.

---

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "Cannot find module" in tests | Check `setupFiles` in `vite.config.ts` for missing imports |
| "Act warning" in console | Wrap state updates in `act()` (see Best Practices above) |
| Tests timeout | Check for unresolved promises; use `{ timeout: 5000 }` in `beforeEach` |
| Fetch not mocked | Add `vi.stubGlobal('fetch', ...)` in test or `beforeEach` |
| jsdom doesn't support feature | Check jsdom compatibility; use `skipIf` conditionally |
