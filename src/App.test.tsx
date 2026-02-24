import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import App from './App';
import type { Drink } from './types';

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const makeDrink = (overrides: Partial<Drink> = {}): Drink => ({
  id: 'sbux-latte',
  brand: 'starbucks',
  name: 'Caffè Latte',
  category: 'hot',
  size_ml: 354,
  nutrition: {
    calories_kcal: 190,
    sugar_g: 17,
    fat_g: 7,
    protein_g: 12,
    caffeine_mg: 150,
  },
  ...overrides,
});

const SBUX_LATTE = makeDrink();
const SBUX_FLAT_WHITE = makeDrink({ id: 'sbux-flat-white', name: 'Flat White' });
const COSTA_LATTE = makeDrink({
  id: 'costa-latte',
  brand: 'costa',
  name: 'Caffè Latte (Costa)',
});

/** Minimal valid JSON envelope */
function makeEnvelope(drinks: Drink[]) {
  return {
    schema_version: '1.0',
    brand: drinks[0]?.brand ?? 'starbucks',
    updated: '2026-02-24',
    drinks,
  };
}

// ---------------------------------------------------------------------------
// Mock fetch — default: starbucks and costa each return one drink
// ---------------------------------------------------------------------------

function mockFetch(
  starbucksDrinks: Drink[] = [SBUX_LATTE],
  costaDrinks: Drink[] = [COSTA_LATTE],
) {
  global.fetch = vi.fn((url: unknown) => {
    const urlStr = String(url);
    const data = urlStr.includes('starbucks')
      ? makeEnvelope(starbucksDrinks)
      : makeEnvelope(costaDrinks);
    return Promise.resolve({
      ok: true,
      json: () => Promise.resolve(data),
    } as Response);
  });
}

beforeEach(() => {
  mockFetch();
});

// ---------------------------------------------------------------------------
// Helper to wait for the catalog to finish loading
// ---------------------------------------------------------------------------

async function renderAndWait() {
  render(<App />);
  // Wait until the loading indicator disappears
  await waitFor(() => expect(screen.queryByText(/loading drinks/i)).not.toBeInTheDocument());
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('App — handleSelect', () => {
  it('renders the drink catalog after loading', async () => {
    await renderAndWait();
    expect(screen.getByText('Caffè Latte')).toBeInTheDocument();
    expect(screen.getByText('Caffè Latte (Costa)')).toBeInTheDocument();
  });

  it('selecting a drink shows it in the selection summary', async () => {
    await renderAndWait();
    const user = userEvent.setup();

    const selectBtn = screen.getAllByRole('button', { name: /select to compare/i })[0];
    await user.click(selectBtn);

    // The "Current selection" section must be present and contain the selected name
    const summary = screen.getByRole('region', { name: /current selection/i });
    expect(within(summary).getByText('Caffè Latte')).toBeInTheDocument();
  });

  it('selected DrinkCard shows "Selected ✓" on its button', async () => {
    await renderAndWait();
    const user = userEvent.setup();

    const buttons = screen.getAllByRole('button', { name: /select to compare/i });
    await user.click(buttons[0]);

    expect(screen.getByRole('button', { name: /selected/i })).toBeInTheDocument();
  });

  it('selecting a second drink from the same brand replaces the first selection', async () => {
    mockFetch([SBUX_LATTE, SBUX_FLAT_WHITE], [COSTA_LATTE]);
    await renderAndWait();
    const user = userEvent.setup();

    // Select first Starbucks drink
    const [firstSbuxBtn] = screen.getAllByRole('button', { name: /select to compare/i });
    await user.click(firstSbuxBtn);

    // "Selected ✓" should appear for the first drink
    expect(screen.getAllByRole('button', { name: /selected/i })).toHaveLength(1);

    // Now click the second Starbucks drink's "Select to Compare" — it has been
    // re-labelled by the first selection so we need to find by text of the card
    const flatWhiteCard = screen.getByText('Flat White').closest('article');
    const flatWhiteBtn = flatWhiteCard!.querySelector('button')!;
    await user.click(flatWhiteBtn);

    // First button should now say "Select to Compare" again, second says "Selected ✓"
    const selectedButtons = screen.getAllByRole('button', { name: /selected/i });
    expect(selectedButtons).toHaveLength(1);

    // The Flat White card's button should now be the selected one
    expect(flatWhiteBtn).toHaveTextContent(/selected/i);
  });

  it('selecting one drink from each brand shows both in the summary', async () => {
    await renderAndWait();
    const user = userEvent.setup();

    const buttons = screen.getAllByRole('button', { name: /select to compare/i });
    // First button = Starbucks drink, last button = Costa drink
    await user.click(buttons[0]);
    await user.click(buttons[buttons.length - 1]);

    // Verify names appear in the "Current selection" summary panel specifically
    const summary = screen.getByRole('region', { name: /current selection/i });
    expect(within(summary).getByText('Caffè Latte')).toBeInTheDocument();
    expect(within(summary).getByText('Caffè Latte (Costa)')).toBeInTheDocument();
  });

  it('clear button resets both selections', async () => {
    await renderAndWait();
    const user = userEvent.setup();

    const buttons = screen.getAllByRole('button', { name: /select to compare/i });
    await user.click(buttons[0]);
    await user.click(buttons[buttons.length - 1]);

    const clearBtn = screen.getByRole('button', { name: /clear/i });
    await user.click(clearBtn);

    // No "Selected ✓" buttons should remain
    expect(screen.queryByRole('button', { name: /selected/i })).not.toBeInTheDocument();
    // Selection summary section should be gone
    expect(screen.queryByText(/your selection/i)).not.toBeInTheDocument();
  });

  it('shows an error message when fetch fails', async () => {
    global.fetch = vi.fn(() => Promise.reject(new Error('Network error')));
    render(<App />);
    await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
    expect(screen.getByRole('alert')).toHaveTextContent(/network error/i);
  });

  it('DrinkCatalog receives correct selectedIds from App state', async () => {
    await renderAndWait();
    const user = userEvent.setup();

    // Before selection: no card should show data-selected=true
    const articles = screen.getAllByRole('article');
    articles.forEach(article => {
      expect(article).toHaveAttribute('data-selected', 'false');
    });

    // Select first drink
    const [firstBtn] = screen.getAllByRole('button', { name: /select to compare/i });
    await user.click(firstBtn);

    // Exactly one card should be data-selected=true
    const selectedArticles = screen
      .getAllByRole('article')
      .filter(a => a.getAttribute('data-selected') === 'true');
    expect(selectedArticles).toHaveLength(1);
  });
});

describe('App — filter / search', () => {
  it('filters by search query', async () => {
    mockFetch([SBUX_LATTE, SBUX_FLAT_WHITE], [COSTA_LATTE]);
    await renderAndWait();
    const user = userEvent.setup();

    const searchInput = screen.getByPlaceholderText(/search drinks/i);
    await user.type(searchInput, 'flat');

    // Only "Flat White" should be visible
    expect(screen.getByText('Flat White')).toBeInTheDocument();
    expect(screen.queryByText('Caffè Latte')).not.toBeInTheDocument();
  });
});
