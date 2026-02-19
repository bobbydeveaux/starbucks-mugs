/**
 * @typedef {{ id: number, name: string, price: number, description: string, imageUrl: string }} Mug
 */

/**
 * Fetches mug data from mugs.json.
 * @returns {Promise<Mug[]>}
 */
async function loadMugs() {
  const response = await fetch('mugs.json');
  if (!response.ok) {
    throw new Error(`Failed to load mugs: ${response.status}`);
  }
  return response.json();
}

/**
 * Creates a card element for a single mug.
 * @param {Mug} mug
 * @returns {HTMLElement}
 */
function createCard(mug) {
  const card = document.createElement('article');
  card.className = 'mug-card';
  card.setAttribute('tabindex', '0');
  card.setAttribute('role', 'button');
  card.setAttribute('aria-label', `View details for ${mug.name}`);

  card.innerHTML = `
    <div class="card-image-wrapper">
      <img class="card-image" src="${mug.imageUrl}" alt="${mug.name}" loading="lazy" />
    </div>
    <div class="card-body">
      <h2 class="card-name">${mug.name}</h2>
      <p class="card-price">$${mug.price.toFixed(2)}</p>
    </div>
  `;

  card.addEventListener('click', () => openDetail(mug));
  card.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      openDetail(mug);
    }
  });

  return card;
}

/**
 * Renders all mug cards into the grid container.
 * @param {Mug[]} mugs
 * @param {HTMLElement} container
 */
function renderGrid(mugs, container) {
  container.innerHTML = '';
  const fragment = document.createDocumentFragment();
  mugs.forEach(mug => fragment.appendChild(createCard(mug)));
  container.appendChild(fragment);
}

/**
 * Opens the detail overlay for a mug.
 * @param {Mug} mug
 */
function openDetail(mug) {
  const overlay = document.getElementById('detail-overlay');
  document.getElementById('detail-image').src = mug.imageUrl;
  document.getElementById('detail-image').alt = mug.name;
  document.getElementById('detail-name').textContent = mug.name;
  document.getElementById('detail-price').textContent = `$${mug.price.toFixed(2)}`;
  document.getElementById('detail-description').textContent = mug.description;
  overlay.hidden = false;
  document.body.classList.add('overlay-open');
  document.getElementById('detail-close').focus();
}

/**
 * Closes the detail overlay.
 */
function closeDetail() {
  const overlay = document.getElementById('detail-overlay');
  overlay.hidden = true;
  document.body.classList.remove('overlay-open');
}

document.addEventListener('DOMContentLoaded', async () => {
  const grid = document.getElementById('grid');

  document.getElementById('detail-close').addEventListener('click', closeDetail);

  document.getElementById('detail-overlay').addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeDetail();
  });

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeDetail();
  });

  try {
    const mugs = await loadMugs();
    renderGrid(mugs, grid);
  } catch (err) {
    grid.innerHTML = '<p class="error-message">Unable to load mugs. Please try again later.</p>';
    console.error(err);
  }
});

export { loadMugs, createCard, renderGrid };
