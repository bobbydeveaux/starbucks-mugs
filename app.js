/**
 * app.js — Starbucks Mugs catalog
 *
 * Fetches mug data from mugs.json, renders a grid of cards,
 * and manages a detail modal with open/close behaviour.
 * Includes a debounced text search + series/year-range filter engine.
 */

/**
 * @typedef {{ id: number, name: string, series: string, year: number,
 *   region: string, edition?: string, material?: string, capacity_oz?: number,
 *   price_usd: number, description: string, image: string, tags: string[] }} MugEntry
 * @typedef {{ query: string, series: string, yearMin: number|null, yearMax: number|null }} FilterState
 */

/** @type {MugEntry|null} */
let currentMug = null;

/** @type {MugEntry[]} Full catalog — set once after fetch; never mutated. */
let allMugs = [];

/** @type {FilterState} Current filter state; mutated in-place by event handlers. */
let filterState = { query: '', series: '', yearMin: null, yearMax: null };

/* -------------------------------------------------------------------------
 * DOM element references
 * All queryed lazily so this module can be loaded on any page without
 * throwing when the mugs-specific elements are absent.
 * -------------------------------------------------------------------------*/

const grid = document.getElementById('grid');
const modal = document.getElementById('modal');
const modalBackdrop = modal ? modal.querySelector('.modal-backdrop') : null;
const modalClose = modal ? modal.querySelector('.modal-close') : null;
const modalImage = document.getElementById('modal-image');
const modalName = document.getElementById('modal-name');
const modalPrice = document.getElementById('modal-price');
const modalDescription = document.getElementById('modal-description');

/* Filter bar elements */
const searchInput = document.getElementById('search');
const seriesSelect = document.getElementById('filter-series');
const yearMinInput = document.getElementById('year-min');
const yearMaxInput = document.getElementById('year-max');
const resetButton = document.getElementById('filter-reset');
const resultsCount = document.getElementById('results-count');

/* =========================================================================
 * FILTER ENGINE
 * =========================================================================*/

/**
 * Filters an array of mugs using AND-combined criteria:
 *   - query: case-insensitive substring match on name, series, region, and tags
 *   - series: exact equality on mug.series (empty string = no filter)
 *   - yearMin / yearMax: inclusive bounds on mug.year (null = unbounded)
 *
 * This function is pure — it does not read or write any module state.
 *
 * @param {MugEntry[]} mugs
 * @param {FilterState} state
 * @returns {MugEntry[]}
 */
function filterMugs(mugs, state) {
  const { query, series, yearMin, yearMax } = state;
  const q = query.trim().toLowerCase();

  return mugs.filter((mug) => {
    // Text search — check name, series, region, and tags
    if (q) {
      const haystack = [
        mug.name,
        mug.series,
        mug.region,
        Array.isArray(mug.tags) ? mug.tags.join(' ') : '',
      ]
        .join(' ')
        .toLowerCase();
      if (!haystack.includes(q)) return false;
    }

    // Series filter — exact equality
    if (series && mug.series !== series) return false;

    // Year range — inclusive bounds
    if (yearMin !== null && mug.year < yearMin) return false;
    if (yearMax !== null && mug.year > yearMax) return false;

    return true;
  });
}

/**
 * Returns a debounced version of `fn` that delays invocation by `delay` ms.
 * Multiple rapid calls reset the timer; only the final call fires.
 *
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

/* =========================================================================
 * RENDER PIPELINE
 * =========================================================================*/

/**
 * Applies current filterState to allMugs, re-renders the grid,
 * and updates the results count.
 */
function applyFilters() {
  const filtered = filterMugs(allMugs, filterState);
  renderCards(filtered);
  updateResultsCount(filtered.length, allMugs.length);
}

/**
 * Populates the series <select> with deduplicated series values
 * sorted alphabetically, preserving the "All Series" default option.
 *
 * @param {MugEntry[]} mugs
 */
function populateSeriesFilter(mugs) {
  if (!seriesSelect) return;

  const series = [...new Set(mugs.map((m) => m.series))].sort();
  series.forEach((s) => {
    const option = document.createElement('option');
    option.value = s;
    option.textContent = s;
    seriesSelect.appendChild(option);
  });
}

/**
 * Updates the #results-count paragraph with a human-readable message.
 *
 * @param {number} shown  — number of mugs currently visible
 * @param {number} total  — total mugs in the catalog
 */
function updateResultsCount(shown, total) {
  if (!resultsCount) return;
  if (shown === total) {
    resultsCount.textContent = `Showing all ${total} mug${total !== 1 ? 's' : ''}`;
  } else {
    resultsCount.textContent = `${shown} of ${total} mug${total !== 1 ? 's' : ''} shown`;
  }
}

/* =========================================================================
 * DATA FETCH
 * =========================================================================*/

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

/* =========================================================================
 * CARD RENDERER
 * =========================================================================*/

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
 * @param {MugEntry[]} mugs
 */
function renderCards(mugs) {
  if (!grid) return;
  grid.innerHTML = '';
  if (mugs.length === 0) {
    grid.innerHTML = '<p class="grid-empty">No mugs match your filters. Try resetting the search.</p>';
    return;
  }
  mugs.forEach((mug) => {
    grid.appendChild(createCard(mug));
  });
}

/* =========================================================================
 * MODAL CONTROLLER
 * =========================================================================*/

/**
 * Opens the modal and populates it with the given mug's details.
 * @param {MugEntry} mug
 */
function openModal(mug) {
  if (!modal) return;
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
  if (modalClose) modalClose.focus();
}

/**
 * Closes the modal and restores page scroll.
 */
function closeModal() {
  if (!modal) return;
  modal.hidden = true;
  document.body.style.overflow = '';
  currentMug = null;
}

/* =========================================================================
 * EVENT WIRING
 * =========================================================================*/

/* Modal close events */
if (modalBackdrop) modalBackdrop.addEventListener('click', closeModal);
if (modalClose) modalClose.addEventListener('click', closeModal);

/* Close on ESC key */
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && modal && !modal.hidden) {
    closeModal();
  }
});

/* Search input — debounced at 200 ms */
if (searchInput) {
  searchInput.addEventListener(
    'input',
    debounce((e) => {
      filterState.query = e.target.value;
      applyFilters();
    }, 200),
  );
}

/* Series dropdown — immediate */
if (seriesSelect) {
  seriesSelect.addEventListener('change', (e) => {
    filterState.series = e.target.value;
    applyFilters();
  });
}

/* Year min input — immediate */
if (yearMinInput) {
  yearMinInput.addEventListener('input', (e) => {
    const val = parseInt(e.target.value, 10);
    filterState.yearMin = isNaN(val) ? null : val;
    applyFilters();
  });
}

/* Year max input — immediate */
if (yearMaxInput) {
  yearMaxInput.addEventListener('input', (e) => {
    const val = parseInt(e.target.value, 10);
    filterState.yearMax = isNaN(val) ? null : val;
    applyFilters();
  });
}

/* Reset button — clears all filter state and re-renders */
if (resetButton) {
  resetButton.addEventListener('click', () => {
    filterState = { query: '', series: '', yearMin: null, yearMax: null };
    if (searchInput) searchInput.value = '';
    if (seriesSelect) seriesSelect.value = '';
    if (yearMinInput) yearMinInput.value = '';
    if (yearMaxInput) yearMaxInput.value = '';
    applyFilters();
  });
}

/* =========================================================================
 * BOOTSTRAP
 * =========================================================================*/

loadMugs()
  .then(({ mugs }) => {
    allMugs = mugs;
    populateSeriesFilter(mugs);
    applyFilters();
  })
  .catch((err) => {
    console.error(err);
    if (grid) {
      grid.innerHTML = '<p class="grid-error">Failed to load mugs. Please try again later.</p>';
    }
  });
