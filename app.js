/**
 * app.js — Starbucks Mugs catalog
 *
 * Fetches mug data from mugs.json, renders a grid of cards,
 * and manages a detail modal with open/close behaviour.
 * Includes a debounced filter/search engine wired to the filter bar.
 */

/**
 * @typedef {{
 *   id: number,
 *   name: string,
 *   series: string,
 *   year: number,
 *   region: string,
 *   edition?: string,
 *   material?: string,
 *   capacity_oz?: number,
 *   price_usd: number,
 *   image: string,
 *   description: string,
 *   tags: string[]
 * }} MugEntry
 *
 * @typedef {{ query: string, series: string, yearMin: number|null, yearMax: number|null }} FilterState
 */

/** @type {MugEntry | null} */
let currentMug = null;

/** @type {MugEntry[]} Full catalog; populated once after fetch */
let allMugs = [];

/** @type {FilterState} Current filter values; mutated by UI events */
let filterState = { query: '', series: '', yearMin: null, yearMax: null };

const grid = document.getElementById('grid');
const modal = document.getElementById('modal');
const modalBackdrop = modal.querySelector('.modal-backdrop');
const modalClose = modal.querySelector('.modal-close');
const modalImage = document.getElementById('modal-image');
const modalName = document.getElementById('modal-name');
const modalPrice = document.getElementById('modal-price');
const modalDescription = document.getElementById('modal-description');

const searchInput = document.getElementById('search');
const seriesSelect = document.getElementById('filter-series');
const yearMinInput = document.getElementById('year-min');
const yearMaxInput = document.getElementById('year-max');
const filterReset = document.getElementById('filter-reset');
const resultsCount = document.getElementById('results-count');

/**
 * Fetches mug data from mugs.json.
 * Supports both the versioned envelope { version, mugs[] } and the legacy bare array.
 * @returns {Promise<{ version: string, mugs: MugEntry[] }>}
 */
async function loadMugs() {
  const response = await fetch('./mugs.json');
  if (!response.ok) {
    throw new Error(`Failed to fetch mugs.json: ${response.status}`);
  }
  const data = await response.json();
  return Array.isArray(data) ? { version: '0', mugs: data } : data;
}

/**
 * Filters mugs using AND-combined conditions.
 * Pure function — no side effects.
 *
 * @param {MugEntry[]} mugs
 * @param {FilterState} state
 * @returns {MugEntry[]}
 */
function filterMugs(mugs, state) {
  const q = state.query.toLowerCase();
  return mugs.filter((mug) => {
    // Text search: case-insensitive substring match on name, series, region, tags
    if (q) {
      const searchable = [
        mug.name,
        mug.series,
        mug.region,
        (mug.tags || []).join(' '),
      ].join(' ').toLowerCase();
      if (!searchable.includes(q)) return false;
    }

    // Series: exact equality (empty string = no filter)
    if (state.series && mug.series !== state.series) return false;

    // Year range: inclusive bounds (null = unbounded)
    if (state.yearMin !== null && mug.year < state.yearMin) return false;
    if (state.yearMax !== null && mug.year > state.yearMax) return false;

    return true;
  });
}

/**
 * Returns a debounced version of fn that delays invocation by delay ms.
 * @param {Function} fn
 * @param {number} [delay=200]
 * @returns {Function}
 */
function debounce(fn, delay = 200) {
  let timer;
  return function (...args) {
    clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), delay);
  };
}

/**
 * Re-runs the filter against allMugs with the current filterState,
 * re-renders the grid, and updates the results count.
 */
function applyFilters() {
  const filtered = filterMugs(allMugs, filterState);
  renderCards(filtered);
  updateResultsCount(filtered.length, allMugs.length);
}

/**
 * Populates the series <select> from distinct series values in the catalog.
 * @param {MugEntry[]} mugs
 */
function populateSeriesFilter(mugs) {
  const seen = new Set();
  mugs.forEach((mug) => {
    if (mug.series && !seen.has(mug.series)) {
      seen.add(mug.series);
      const option = document.createElement('option');
      option.value = mug.series;
      option.textContent = mug.series;
      seriesSelect.appendChild(option);
    }
  });
}

/**
 * Updates the #results-count paragraph.
 * @param {number} shown
 * @param {number} total
 */
function updateResultsCount(shown, total) {
  resultsCount.textContent =
    shown === total ? `${total} mugs` : `${shown} of ${total} mugs`;
}

/**
 * Renders a mug card element.
 * @param {MugEntry} mug
 * @returns {HTMLElement}
 */
function createCard(mug) {
  const card = document.createElement('div');
  card.className = 'card';
  card.setAttribute('role', 'listitem');
  card.setAttribute('tabindex', '0');
  card.setAttribute('aria-label', `${mug.name}, $${mug.price_usd.toFixed(2)}`);

  const img = document.createElement('img');
  img.src = mug.image;
  img.alt = mug.name;
  img.className = 'card-image';
  img.loading = 'lazy';
  img.onerror = () => {
    img.src = 'images/placeholder.svg';
    img.onerror = null;
  };

  const body = document.createElement('div');
  body.className = 'card-body';

  const name = document.createElement('p');
  name.className = 'card-name';
  name.textContent = mug.name;

  const price = document.createElement('p');
  price.className = 'card-price';
  price.textContent = `$${mug.price_usd.toFixed(2)}`;

  body.appendChild(name);
  body.appendChild(price);
  card.appendChild(img);
  card.appendChild(body);

  card.addEventListener('click', () => openModal(mug));
  card.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      openModal(mug);
    }
  });

  return card;
}

/**
 * Renders all mug cards into the #grid container.
 * Shows an empty-state message when the array is empty.
 * @param {MugEntry[]} mugs
 */
function renderCards(mugs) {
  grid.innerHTML = '';
  if (mugs.length === 0) {
    const empty = document.createElement('p');
    empty.className = 'grid-empty';
    empty.textContent = 'No mugs match your filters.';
    grid.appendChild(empty);
    return;
  }
  mugs.forEach((mug) => {
    grid.appendChild(createCard(mug));
  });
}

/**
 * Opens the modal and populates it with the given mug's details.
 * @param {MugEntry} mug
 */
function openModal(mug) {
  currentMug = mug;

  modalImage.src = mug.image;
  modalImage.alt = mug.name;
  modalImage.onerror = () => {
    modalImage.src = 'images/placeholder.svg';
    modalImage.onerror = null;
  };
  modalName.textContent = mug.name;
  modalPrice.textContent = `$${mug.price_usd.toFixed(2)}`;
  modalDescription.textContent = mug.description;

  modal.hidden = false;
  document.body.style.overflow = 'hidden';
  modalClose.focus();
}

/**
 * Closes the modal and restores page scroll.
 */
function closeModal() {
  modal.hidden = true;
  document.body.style.overflow = '';
  currentMug = null;
}

/* Close on backdrop click */
modalBackdrop.addEventListener('click', closeModal);

/* Close on × button click */
modalClose.addEventListener('click', closeModal);

/* Close on ESC key */
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !modal.hidden) {
    closeModal();
  }
});

/* ── Filter bar event wiring ─────────────────────────────────────────────── */

/* Search input — debounced at 200 ms */
searchInput.addEventListener(
  'input',
  debounce(() => {
    filterState.query = searchInput.value.trim();
    applyFilters();
  }, 200)
);

/* Series select — immediate */
seriesSelect.addEventListener('change', () => {
  filterState.series = seriesSelect.value;
  applyFilters();
});

/* Year min — immediate */
yearMinInput.addEventListener('input', () => {
  const val = parseInt(yearMinInput.value, 10);
  filterState.yearMin = isNaN(val) ? null : val;
  applyFilters();
});

/* Year max — immediate */
yearMaxInput.addEventListener('input', () => {
  const val = parseInt(yearMaxInput.value, 10);
  filterState.yearMax = isNaN(val) ? null : val;
  applyFilters();
});

/* Reset — clears all filters and re-renders full catalog */
filterReset.addEventListener('click', () => {
  filterState = { query: '', series: '', yearMin: null, yearMax: null };
  searchInput.value = '';
  seriesSelect.value = '';
  yearMinInput.value = '';
  yearMaxInput.value = '';
  applyFilters();
});

/* ── Bootstrap ───────────────────────────────────────────────────────────── */
loadMugs()
  .then(({ mugs }) => {
    allMugs = mugs;
    populateSeriesFilter(mugs);
    applyFilters();
  })
  .catch((err) => {
    console.error(err);
    grid.innerHTML = '<p class="grid-error">Failed to load mugs. Please try again later.</p>';
  });
