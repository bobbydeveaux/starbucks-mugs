/**
 * app.js — Starbucks Mugs catalog
 *
 * Fetches mug data from mugs.json, renders a grid of cards,
 * and manages a detail modal with open/close behaviour.
 */

/** @type {{ id: number, name: string, price_usd: number, image: string, description: string } | null} */
let currentMug = null;

const grid = document.getElementById('grid');
const modal = document.getElementById('modal');
const modalBackdrop = modal.querySelector('.modal-backdrop');
const modalClose = modal.querySelector('.modal-close');
const modalImage = document.getElementById('modal-image');
const modalName = document.getElementById('modal-name');
const modalPrice = document.getElementById('modal-price');
const modalDescription = document.getElementById('modal-description');

/**
 * Fetches mug data from mugs.json.
 * Supports both the versioned envelope { version, mugs[] } and the legacy bare array.
 * @returns {Promise<{ version: string, mugs: Array }>}
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
 * Renders a mug card element.
 * @param {{ id: number, name: string, price_usd: number, image: string, description: string }} mug
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
 * @param {Array} mugs
 */
function renderCards(mugs) {
  grid.innerHTML = '';
  mugs.forEach((mug) => {
    grid.appendChild(createCard(mug));
  });
}

/**
 * Opens the modal and populates it with the given mug's details.
 * @param {{ id: number, name: string, price_usd: number, image: string, description: string }} mug
 */
function openModal(mug) {
  currentMug = mug;

  modalImage.src = mug.image;
  modalImage.alt = mug.name;
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

/* Bootstrap */
loadMugs()
  .then(({ mugs }) => renderCards(mugs))
  .catch((err) => {
    console.error(err);
    grid.innerHTML = '<p class="grid-error">Failed to load mugs. Please try again later.</p>';
  });
