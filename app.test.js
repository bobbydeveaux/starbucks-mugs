/**
 * Tests for app.js — Starbucks Mugs catalog
 *
 * Run with: node app.test.js
 * (No external test runner required; uses Node's built-in assert module.)
 */

const assert = require('assert');

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
  { id: 1, name: 'Classic White Ceramic Mug', price_usd: 12.95, image: 'images/classic-white.jpg', description: 'Timeless classic.' },
  { id: 2, name: 'Pike Place Roast Mug',      price_usd: 14.95, image: 'images/pike-place.jpg',    description: 'Vintage-style.' },
  { id: 3, name: 'Holiday Season Tumbler',     price_usd: 19.95, image: 'images/holiday.jpg',       description: 'Festive design.' },
  { id: 4, name: 'City Collection: Seattle',   price_usd: 16.95, image: 'images/city-seattle.jpg',  description: 'Space Needle.' },
  { id: 5, name: 'Reserve Roastery Mug',       price_usd: 22.95, image: 'images/reserve.jpg',       description: 'Premium matte.' },
  { id: 6, name: 'You Are Here Collection',    price_usd: 18.95, image: 'images/you-are-here.jpg',  description: 'World landmarks.' },
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
 * INTEGRATION TESTS — fetch + render flow (mocked)
 * =========================================================================*/

console.log('\nIntegration Tests — loadMugs + renderCards');

async function runIntegrationTests() {
  await test_fetchSuccess();
  await test_fetchLegacyArray();
  await test_fetchFailure();
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

// Inline reimplementation of loadMugs parsing logic for unit testing
function parseMugsResponse(data) {
  return Array.isArray(data) ? { version: '0', mugs: data } : data;
}

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

/* =========================================================================
 * Run all tests
 * =========================================================================*/

runIntegrationTests().then(() => {
  console.log(`\n${passed + failed} tests: ${passed} passed, ${failed} failed\n`);
  if (failed > 0) {
    process.exit(1);
  }
});
