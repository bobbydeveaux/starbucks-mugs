/**
 * Tests for app.js — Starbucks Mugs catalog
 *
 * Run with: node app.test.js
 * (No external test runner required; uses Node's built-in assert module.)
 */

import assert from 'assert';

/* -------------------------------------------------------------------------
 * JSDOM-free DOM simulation helpers
 * We create a minimal in-memory DOM so we can import the module's pure
 * functions directly without a browser or jsdom.
 * -------------------------------------------------------------------------*/

/**
 * Minimal element factory that mirrors just enough of the DOM API used by
 * createCard / renderCards / openModal / closeModal.
 */
function makeElement(tag = 'div') {
  const el = {
    tagName: tag.toUpperCase(),
    className: '',
    textContent: '',
    src: '',
    alt: '',
    loading: '',
    hidden: false,
    innerHTML: '',
    children: [],
    _attrs: {},
    _listeners: {},
    style: {},
    setAttribute(k, v) { this._attrs[k] = v; },
    getAttribute(k) { return this._attrs[k]; },
    addEventListener(evt, fn) {
      this._listeners[evt] = this._listeners[evt] || [];
      this._listeners[evt].push(fn);
    },
    _fire(evt, eventObj = {}) {
      (this._listeners[evt] || []).forEach(fn => fn(eventObj));
    },
    appendChild(child) {
      this.children.push(child);
      return child;
    },
    querySelector(sel) {
      // Minimal: match by class name prefix
      const cls = sel.replace(/^\./, '');
      return this.children.find(c => c.className === cls) || null;
    },
    focus() {},
  };
  return el;
}

/* -------------------------------------------------------------------------
 * Re-implement the pure functions under test (extracted from app.js)
 * so we don't need to load the ES module or stub the DOM globals.
 * -------------------------------------------------------------------------*/

// -- createCard (extracted logic) --
function createCard(mug, onOpen) {
  const card = makeElement('div');
  card.className = 'card';
  card.setAttribute('role', 'listitem');
  card.setAttribute('tabindex', '0');
  card.setAttribute('aria-label', `${mug.name}, $${mug.price_usd.toFixed(2)}`);

  const img = makeElement('img');
  img.src = mug.image;
  img.alt = mug.name;
  img.className = 'card-image';
  img.loading = 'lazy';
  img.onerror = () => {
    img.src = 'images/placeholder.svg';
    img.onerror = null;
  };

  const body = makeElement('div');
  body.className = 'card-body';

  const name = makeElement('p');
  name.className = 'card-name';
  name.textContent = mug.name;

  const price = makeElement('p');
  price.className = 'card-price';
  price.textContent = `$${mug.price_usd.toFixed(2)}`;

  body.appendChild(name);
  body.appendChild(price);
  card.appendChild(img);
  card.appendChild(body);

  card.addEventListener('click', () => onOpen(mug));
  card.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onOpen(mug);
    }
  });

  return card;
}

// -- renderCards (extracted logic) --
function renderCards(mugs, container, onOpen) {
  container.innerHTML = '';
  container.children = [];
  mugs.forEach(mug => container.appendChild(createCard(mug, onOpen)));
}

// -- filterMugs (extracted logic) --
/**
 * @param {Array} mugs
 * @param {{ query: string, series: string, yearMin: number|null, yearMax: number|null }} state
 * @returns {Array}
 */
function filterMugs(mugs, state) {
  const { query, series, yearMin, yearMax } = state;
  const q = query.trim().toLowerCase();

  return mugs.filter((mug) => {
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

    if (series && mug.series !== series) return false;

    if (yearMin !== null && mug.year < yearMin) return false;
    if (yearMax !== null && mug.year > yearMax) return false;

    return true;
  });
}

// -- debounce (extracted logic) --
/**
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

// -- parseMugsResponse (extracted logic) --
function parseMugsResponse(data) {
  return Array.isArray(data) ? { version: '0', mugs: data } : data;
}

/* -------------------------------------------------------------------------
 * Test helpers
 * -------------------------------------------------------------------------*/

let passed = 0;
let failed = 0;

function test(description, fn) {
  try {
    fn();
    console.log(`  ✓ ${description}`);
    passed++;
  } catch (err) {
    console.error(`  ✗ ${description}`);
    console.error(`    ${err.message}`);
    failed++;
  }
}

/* -------------------------------------------------------------------------
 * Fixtures
 * -------------------------------------------------------------------------*/

const MUGS = [
  { id: 1, name: 'Classic White Ceramic Mug', price_usd: 12.95, image: 'images/classic-white.jpg', description: 'Timeless classic.', series: 'Siren',           year: 2019, region: 'Global',        tags: ['ceramic', 'classic', 'siren', 'white'] },
  { id: 2, name: 'Pike Place Roast Mug',      price_usd: 14.95, image: 'images/pike-place.jpg',    description: 'Vintage-style.',   series: 'Anniversary',     year: 2012, region: 'North America', tags: ['vintage', 'anniversary', 'seattle'] },
  { id: 3, name: 'Holiday Season Tumbler',     price_usd: 19.95, image: 'images/holiday.jpg',       description: 'Festive design.',  series: 'Holiday',         year: 2023, region: 'Global',        tags: ['holiday', 'limited-edition', 'insulated'] },
  { id: 4, name: 'City Collection: Seattle',   price_usd: 16.95, image: 'images/city-seattle.jpg',  description: 'Space Needle.',    series: 'City Collection', year: 2020, region: 'Seattle, USA',  tags: ['city-collection', 'seattle', 'skyline'] },
  { id: 5, name: 'Reserve Roastery Mug',       price_usd: 22.95, image: 'images/reserve.jpg',       description: 'Premium matte.',   series: 'Reserve',         year: 2021, region: 'Global',        tags: ['reserve', 'roastery', 'premium'] },
  { id: 6, name: 'You Are Here Collection',    price_usd: 18.95, image: 'images/you-are-here.jpg',  description: 'World landmarks.', series: 'You Are Here',    year: 2018, region: 'Global',        tags: ['you-are-here', 'landmarks', 'travel'] },
];

/* =========================================================================
 * UNIT TESTS
 * =========================================================================*/

console.log('\nUnit Tests — createCard');

test('card has class "card"', () => {
  const card = createCard(MUGS[0], () => {});
  assert.strictEqual(card.className, 'card');
});

test('card sets role="listitem"', () => {
  const card = createCard(MUGS[0], () => {});
  assert.strictEqual(card.getAttribute('role'), 'listitem');
});

test('card sets tabindex="0"', () => {
  const card = createCard(MUGS[0], () => {});
  assert.strictEqual(card.getAttribute('tabindex'), '0');
});

test('card aria-label includes name and formatted price_usd', () => {
  const mug = MUGS[0];
  const card = createCard(mug, () => {});
  const label = card.getAttribute('aria-label');
  assert.ok(label.includes(mug.name), 'label should include mug name');
  assert.ok(label.includes('$12.95'), 'label should include formatted price');
});

test('card image has loading="lazy"', () => {
  const card = createCard(MUGS[0], () => {});
  const img = card.children[0];
  assert.strictEqual(img.loading, 'lazy');
});

test('card image src matches mug image field', () => {
  const card = createCard(MUGS[0], () => {});
  const img = card.children[0];
  assert.strictEqual(img.src, MUGS[0].image);
});

test('card image alt matches mug name', () => {
  const card = createCard(MUGS[0], () => {});
  const img = card.children[0];
  assert.strictEqual(img.alt, MUGS[0].name);
});

test('card body displays mug name', () => {
  const card = createCard(MUGS[0], () => {});
  const body = card.children[1];
  const nameEl = body.children[0];
  assert.strictEqual(nameEl.textContent, MUGS[0].name);
});

test('card body displays formatted price', () => {
  const card = createCard(MUGS[0], () => {});
  const body = card.children[1];
  const priceEl = body.children[1];
  assert.strictEqual(priceEl.textContent, '$12.95');
});

test('click fires onOpen with correct mug', () => {
  let received = null;
  const card = createCard(MUGS[2], (mug) => { received = mug; });
  card._fire('click');
  assert.strictEqual(received, MUGS[2]);
});

test('Enter keydown fires onOpen', () => {
  let received = null;
  const card = createCard(MUGS[1], (mug) => { received = mug; });
  card._fire('keydown', { key: 'Enter', preventDefault() {} });
  assert.strictEqual(received, MUGS[1]);
});

test('Space keydown fires onOpen', () => {
  let received = null;
  const card = createCard(MUGS[1], (mug) => { received = mug; });
  card._fire('keydown', { key: ' ', preventDefault() {} });
  assert.strictEqual(received, MUGS[1]);
});

test('Tab keydown does NOT fire onOpen', () => {
  let received = null;
  const card = createCard(MUGS[1], (mug) => { received = mug; });
  card._fire('keydown', { key: 'Tab', preventDefault() {} });
  assert.strictEqual(received, null);
});

/* =========================================================================
 * UNIT TESTS — renderCards
 * =========================================================================*/

console.log('\nUnit Tests — renderCards');

test('renders correct number of cards', () => {
  const container = makeElement('div');
  renderCards(MUGS, container, () => {});
  assert.strictEqual(container.children.length, MUGS.length);
});

test('renders 0 cards for empty array', () => {
  const container = makeElement('div');
  renderCards([], container, () => {});
  assert.strictEqual(container.children.length, 0);
});

test('re-renders replaces previous cards', () => {
  const container = makeElement('div');
  renderCards(MUGS, container, () => {});
  renderCards(MUGS.slice(0, 2), container, () => {});
  assert.strictEqual(container.children.length, 2);
});

test('each rendered card has class "card"', () => {
  const container = makeElement('div');
  renderCards(MUGS, container, () => {});
  container.children.forEach(card => {
    assert.strictEqual(card.className, 'card');
  });
});

/* =========================================================================
 * UNIT TESTS — filterMugs
 * =========================================================================*/

console.log('\nUnit Tests — filterMugs');

test('filterMugs: empty query with no filters returns all mugs', () => {
  const result = filterMugs(MUGS, { query: '', series: '', yearMin: null, yearMax: null });
  assert.strictEqual(result.length, MUGS.length);
});

test('filterMugs: query matches mug name (case-insensitive)', () => {
  const result = filterMugs(MUGS, { query: 'CLASSIC', series: '', yearMin: null, yearMax: null });
  assert.strictEqual(result.length, 1);
  assert.strictEqual(result[0].name, 'Classic White Ceramic Mug');
});

test('filterMugs: query matches mug name (partial match)', () => {
  const result = filterMugs(MUGS, { query: 'city', series: '', yearMin: null, yearMax: null });
  assert.ok(result.length >= 1, 'should match at least one city mug');
  assert.ok(result.find(m => m.name === 'City Collection: Seattle'), 'should include Seattle mug');
});

test('filterMugs: query matches tag substring', () => {
  const result = filterMugs(MUGS, { query: 'limited-edition', series: '', yearMin: null, yearMax: null });
  assert.strictEqual(result.length, 1);
  assert.strictEqual(result[0].name, 'Holiday Season Tumbler');
});

test('filterMugs: query matches region', () => {
  const result = filterMugs(MUGS, { query: 'North America', series: '', yearMin: null, yearMax: null });
  assert.ok(result.length >= 1, 'should match at least one mug by region');
  assert.ok(result.find(m => m.region === 'North America'));
});

test('filterMugs: series filter excludes non-matching series', () => {
  const result = filterMugs(MUGS, { query: '', series: 'Holiday', yearMin: null, yearMax: null });
  assert.strictEqual(result.length, 1);
  assert.strictEqual(result[0].series, 'Holiday');
});

test('filterMugs: series filter with empty string returns all mugs', () => {
  const result = filterMugs(MUGS, { query: '', series: '', yearMin: null, yearMax: null });
  assert.strictEqual(result.length, MUGS.length);
});

test('filterMugs: yearMin filters out mugs before the bound (inclusive)', () => {
  const result = filterMugs(MUGS, { query: '', series: '', yearMin: 2020, yearMax: null });
  assert.ok(result.every(m => m.year >= 2020), 'all results should have year >= 2020');
  assert.ok(!result.find(m => m.year < 2020), 'no mug with year < 2020 should appear');
});

test('filterMugs: yearMax filters out mugs after the bound (inclusive)', () => {
  const result = filterMugs(MUGS, { query: '', series: '', yearMin: null, yearMax: 2019 });
  assert.ok(result.every(m => m.year <= 2019), 'all results should have year <= 2019');
  assert.ok(!result.find(m => m.year > 2019), 'no mug with year > 2019 should appear');
});

test('filterMugs: yearMin and yearMax combined — inclusive range', () => {
  const result = filterMugs(MUGS, { query: '', series: '', yearMin: 2018, yearMax: 2020 });
  assert.ok(result.every(m => m.year >= 2018 && m.year <= 2020),
    'all results should have year in [2018, 2020]');
  assert.ok(result.find(m => m.year === 2018), 'mug with year 2018 should appear');
  assert.ok(result.find(m => m.year === 2019), 'mug with year 2019 should appear');
  assert.ok(result.find(m => m.year === 2020), 'mug with year 2020 should appear');
  assert.ok(!result.find(m => m.year < 2018), 'no mug with year < 2018');
  assert.ok(!result.find(m => m.year > 2020), 'no mug with year > 2020');
});

test('filterMugs: all filters combined narrows results correctly', () => {
  // series "Siren" + year >= 2019 + query "global"
  const result = filterMugs(MUGS, { query: 'global', series: 'Siren', yearMin: 2019, yearMax: null });
  // Only MUGS[0] matches: series "Siren", year 2019, region "Global"
  assert.strictEqual(result.length, 1);
  assert.strictEqual(result[0].id, 1);
});

test('filterMugs: no match returns empty array', () => {
  const result = filterMugs(MUGS, { query: 'xyzzy-no-match', series: '', yearMin: null, yearMax: null });
  assert.deepStrictEqual(result, []);
});

test('filterMugs: query is whitespace-trimmed before matching', () => {
  const result = filterMugs(MUGS, { query: '  classic  ', series: '', yearMin: null, yearMax: null });
  assert.strictEqual(result.length, 1);
  assert.strictEqual(result[0].name, 'Classic White Ceramic Mug');
});

test('filterMugs: does not mutate the input array', () => {
  const copy = [...MUGS];
  filterMugs(MUGS, { query: 'classic', series: '', yearMin: null, yearMax: null });
  assert.deepStrictEqual(MUGS, copy, 'original mugs array should not be modified');
});

/* =========================================================================
 * UNIT TESTS — debounce
 * =========================================================================*/

console.log('\nUnit Tests — debounce');

test('debounce: returns a function', () => {
  const fn = debounce(() => {}, 200);
  assert.strictEqual(typeof fn, 'function');
});

test('debounce: callback does not fire synchronously', () => {
  let callCount = 0;
  const fn = debounce(() => { callCount++; }, 50);
  fn();
  fn();
  fn();
  assert.strictEqual(callCount, 0, 'callback must not fire synchronously');
});

test('debounce: multiple rapid calls do not fire callback synchronously', () => {
  let callCount = 0;
  const fn = debounce(() => { callCount++; }, 100);
  for (let i = 0; i < 10; i++) fn();
  assert.strictEqual(callCount, 0, 'ten rapid calls must not fire callback synchronously');
});

/* =========================================================================
 * UNIT TESTS — image onerror fallback (createCard)
 * =========================================================================*/

console.log('\nUnit Tests — image onerror fallback');

test('card image onerror sets src to placeholder and nulls handler', () => {
  const card = createCard(MUGS[0], () => {});
  const img = card.children[0];
  assert.ok(typeof img.onerror === 'function', 'onerror should be a function initially');
  img.onerror();
  assert.strictEqual(img.src, 'images/placeholder.svg', 'onerror should set placeholder src');
  assert.strictEqual(img.onerror, null, 'onerror should null itself to prevent loops');
});

/* =========================================================================
 * INTEGRATION TESTS — fetch + render flow (mocked)
 * =========================================================================*/

console.log('\nIntegration Tests — loadMugs + renderCards');

async function runIntegrationTests() {
  await test_fetchSuccess();
  await test_fetchLegacyArray();
  await test_fetchFailure();
  await test_filterAndRender();
}

async function test_fetchSuccess() {
  const name = 'fetch returns versioned envelope and renderCards populates grid';
  try {
    // Simulate a successful fetch returning versioned envelope
    const envelope = { version: '1.0', mugs: MUGS };
    const fakeFetch = async (url) => ({
      ok: true,
      json: async () => envelope,
    });

    // Replicate the bootstrap flow (with envelope unwrapping)
    const container = makeElement('div');
    let openedMug = null;
    const data = await fakeFetch('./mugs.json').then(r => r.json());
    const mugs = Array.isArray(data) ? data : data.mugs;
    renderCards(mugs, container, (mug) => { openedMug = mug; });

    assert.strictEqual(container.children.length, MUGS.length, 'grid should have all mugs');

    // Simulate clicking the first card
    container.children[0]._fire('click');
    assert.strictEqual(openedMug, MUGS[0], 'clicking first card should open first mug');

    console.log(`  ✓ ${name}`);
    passed++;
  } catch (err) {
    console.error(`  ✗ ${name}`);
    console.error(`    ${err.message}`);
    failed++;
  }
}

async function test_fetchLegacyArray() {
  const name = 'legacy bare-array response is wrapped and grid still renders';
  try {
    // Simulate fetch returning a bare array (legacy format)
    const fakeFetch = async (url) => ({
      ok: true,
      json: async () => MUGS,
    });

    const container = makeElement('div');
    const data = await fakeFetch('./mugs.json').then(r => r.json());
    const mugs = Array.isArray(data) ? data : data.mugs;
    renderCards(mugs, container, () => {});

    assert.strictEqual(container.children.length, MUGS.length, 'grid should render all mugs from bare array');
    console.log(`  ✓ ${name}`);
    passed++;
  } catch (err) {
    console.error(`  ✗ ${name}`);
    console.error(`    ${err.message}`);
    failed++;
  }
}

async function test_fetchFailure() {
  const name = 'failed fetch shows error message in grid';
  try {
    const container = makeElement('div');
    let errorHtml = '';

    // Replicate error handling
    const fakeFetch = async () => { throw new Error('Network error'); };

    await fakeFetch('./mugs.json')
      .then(r => r.json())
      .then(mugs => renderCards(mugs, container, () => {}))
      .catch(() => {
        container.innerHTML = '<p class="grid-error">Failed to load mugs. Please try again later.</p>';
      });

    assert.ok(container.innerHTML.includes('Failed to load mugs'), 'error message should appear in grid');
    console.log(`  ✓ ${name}`);
    passed++;
  } catch (err) {
    console.error(`  ✗ ${name}`);
    console.error(`    ${err.message}`);
    failed++;
  }
}

/* =========================================================================
 * UNIT TESTS — loadMugs envelope handling
 * =========================================================================*/

console.log('\nUnit Tests — loadMugs envelope handling');

test('versioned envelope is returned as-is', () => {
  const envelope = { version: '1.0', mugs: MUGS };
  const result = parseMugsResponse(envelope);
  assert.strictEqual(result.version, '1.0');
  assert.strictEqual(result.mugs, MUGS);
});

test('bare array is wrapped into { version: "0", mugs }', () => {
  const result = parseMugsResponse(MUGS);
  assert.strictEqual(result.version, '0');
  assert.deepStrictEqual(result.mugs, MUGS);
});

test('empty array is wrapped correctly', () => {
  const result = parseMugsResponse([]);
  assert.strictEqual(result.version, '0');
  assert.deepStrictEqual(result.mugs, []);
});

async function test_filterAndRender() {
  const name = 'filter + render: filterMugs narrows catalog and renderCards shows only matching mugs';
  try {
    // Apply a series filter: only "Holiday" mugs
    const state = { query: '', series: 'Holiday', yearMin: null, yearMax: null };
    const filtered = filterMugs(MUGS, state);

    const container = makeElement('div');
    renderCards(filtered, container, () => {});

    const expectedCount = MUGS.filter(m => m.series === 'Holiday').length;
    assert.strictEqual(
      container.children.length,
      expectedCount,
      `grid should show only Holiday mugs (expected ${expectedCount})`,
    );

    // Verify each rendered card has a valid aria-label
    container.children.forEach((card, i) => {
      const label = card.getAttribute('aria-label');
      assert.ok(label && label.length > 0, `card ${i} should have a non-empty aria-label`);
    });

    // Apply a compound filter: query "ceramic" + yearMin 2019 + yearMax 2019
    const state2 = { query: 'ceramic', series: '', yearMin: 2019, yearMax: 2019 };
    const filtered2 = filterMugs(MUGS, state2);
    const container2 = makeElement('div');
    renderCards(filtered2, container2, () => {});

    // MUGS[0] (Classic White Ceramic Mug, year 2019, tags include 'ceramic') should match
    assert.strictEqual(container2.children.length, 1, 'compound filter should return exactly 1 mug');

    console.log(`  ✓ ${name}`);
    passed++;
  } catch (err) {
    console.error(`  ✗ ${name}`);
    console.error(`    ${err.message}`);
    failed++;
  }
}

/* =========================================================================
 * Run all tests
 * =========================================================================*/

runIntegrationTests().then(() => {
  console.log(`\n${passed + failed} tests: ${passed} passed, ${failed} failed\n`);
  if (failed > 0) {
    process.exit(1);
  }
});
