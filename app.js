/**
 * Fetches mug data from mugs.json.
 * @returns {Promise<Array>} Array of mug records
 */
async function loadMugs() {
  const response = await fetch('mugs.json');
  if (!response.ok) {
    throw new Error(`Failed to load mugs: ${response.status}`);
  }
  return response.json();
}

/**
 * Creates a card DOM element for a single mug.
 * @param {Object} mug - Mug record with id, name, price, description, imageUrl
 * @returns {HTMLElement} Card element
 */
function createCard(mug) {
  const card = document.createElement('article');
  card.className = 'card';
  card.setAttribute('role', 'button');
  card.setAttribute('tabindex', '0');
  card.setAttribute('aria-label', `${mug.name} - $${mug.price.toFixed(2)}`);

  card.innerHTML = `
    <img class="card-image" src="${mug.imageUrl}" alt="${mug.name}">
    <div class="card-body">
      <h2 class="card-name">${mug.name}</h2>
      <p class="card-price">$${mug.price.toFixed(2)}</p>
    </div>
  `;

  card.addEventListener('click', () => showDetail(mug));
  card.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      showDetail(mug);
    }
  });

  return card;
}

/**
 * Renders all mug cards into the given container element.
 * @param {Array} mugs - Array of mug records
 * @param {HTMLElement} container - Target container element
 */
function renderGrid(mugs, container) {
  container.innerHTML = '';
  const fragment = document.createDocumentFragment();
  mugs.forEach(mug => fragment.appendChild(createCard(mug)));
  container.appendChild(fragment);
}

/**
 * Opens the detail modal with full mug information.
 * @param {Object} mug - Mug record to display
 */
function showDetail(mug) {
  const modal = document.getElementById('modal');
  document.getElementById('modal-image').src = mug.imageUrl;
  document.getElementById('modal-image').alt = mug.name;
  document.getElementById('modal-name').textContent = mug.name;
  document.getElementById('modal-price').textContent = `$${mug.price.toFixed(2)}`;
  document.getElementById('modal-description').textContent = mug.description;

  modal.classList.remove('hidden');
  document.getElementById('modal-close').focus();
}

/**
 * Closes the detail modal.
 */
function closeDetail() {
  document.getElementById('modal').classList.add('hidden');
}

document.addEventListener('DOMContentLoaded', async () => {
  const container = document.getElementById('grid');

  try {
    const mugs = await loadMugs();
    renderGrid(mugs, container);
  } catch (err) {
    container.textContent = 'Unable to load mugs.';
  }

  document.getElementById('modal-close').addEventListener('click', closeDetail);
  document.getElementById('modal-overlay').addEventListener('click', closeDetail);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeDetail();
  });
});

export { loadMugs, createCard, renderGrid };
