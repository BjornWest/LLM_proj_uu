const sek = ore => (ore / 100).toLocaleString('sv-SE', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
}) + ' kr';

let data;
let category = '';
let query = '';
const $ = selector => document.querySelector(selector);
const productUrl = id => `/products/${encodeURIComponent(id)}`;
const urlState = () => { const params = new URLSearchParams(location.search); return { query: (params.get('q') || '').trim(), category: (params.get('category') || '').trim() }; };

function requestedProductId() {
  const match = location.pathname.match(/^\/products\/([^/]+)$/);
  if (match) return decodeURIComponent(match[1]);
  return new URLSearchParams(location.search).get('product_id');
}

async function boot() {
  const response = await fetch('/api/config');
  if (!response.ok) throw new Error(`Katalogen svarade med ${response.status}`);
  data = await response.json();
  ({ query, category } = urlState());
  $('#q').value = query;
  renderCategories();
  const wanted = requestedProductId();
  if (wanted) renderProductPage(wanted);
  else renderProducts(!query && !category);
}

function renderCategories() {
  const categories = ['Alla', ...new Set(data.products.map(product => product.category))];
  $('#categories').innerHTML = categories.map(name => {
    const value = name === 'Alla' ? '' : name;
    return `<button data-cat="${value}" aria-pressed="${category === value}">${name}</button>`;
  }).join('');
  $('#categories').onclick = event => {
    if (event.target.dataset.cat === undefined) return;
    category = event.target.dataset.cat;
    query = '';
    window.history.pushState(null, '', category ? `/?category=${encodeURIComponent(category)}` : '/');
    renderCategories();
    renderProducts(false);
  };
}

function matches(product) {
  const text = [product.name, product.brand, product.model, product.variant,
    product.capacity, product.category].join(' ').toLowerCase();
  const tokens = query.toLocaleLowerCase('sv').split(/\s+/).filter(Boolean);
  return (!category || product.category === category) && tokens.every(token => text.includes(token));
}

function setListingVisibility(visible) {
  $('#hero').hidden = !visible;
  $('#categories').hidden = !visible;
  $('#products').hidden = !visible;
  $('#promos').hidden = !visible;
  $('#detail').hidden = visible;
}

function productCard(product) {
  const offers = data.offers.filter(offer => offer.product_id === product.id);
  if (!offers.length) return '';
  const minimum = Math.min(...offers.map(offer => offer.quote_ore + offer.shipping_ore));
  const href = productUrl(product.id);
  return `<article class="card"><a class="product-image-link" href="${href}" aria-label="Visa ${product.name}, ${product.variant}, ${product.capacity}"><img src="/assets/product.svg" alt="Illustration av ${product.name}"></a><p class="muted">${product.category} · ${product.brand}</p><h2><a class="product-title-link" href="${href}">${product.name}</a></h2><p><strong>${product.variant}</strong><br>${product.capacity}</p><p>Jämförpris från <strong>${sek(minimum)}</strong> inkl. frakt</p><a class="product-action" href="${href}">Jämför ${offers.length} butiker</a></article>`;
}

function renderHomepage() {
  const ids = data.homepage?.product_ids || [];
  const pinned = ids.map(id => data.products.find(product => product.id === id)).filter(Boolean);
  $('#hero').innerHTML = '<p class="eyebrow">Prislyktan / Handplockat just nu</p><h1>Teknik som gör vardagen lite enklare</h1><p>Upptäck nya favoriter, jämför hela priset och välj butik med lugn i magen.</p>';
  $('#status').textContent = '';
  const groups = [['Små uppgraderingar', pinned.slice(0, 3)], ['För skrivbord, vila och rörelse', pinned.slice(3)]].filter(([, products]) => products.length);
  $('#promos').innerHTML = groups.map(([title, products]) => `<section class="promo-shelf"><div class="shelf-heading"><div><p class="eyebrow">Utvalt sortiment</p><h2>${title}</h2></div><span>${products.length} tips</span></div><div class="products">${products.map(productCard).join('')}</div></section>`).join('');
  $('#products').innerHTML = '';
}

function renderProducts(homepage = false) {
  document.title = 'Prislyktan — jämför aktuella teknikpriser';
  setListingVisibility(true);
  if (homepage) return renderHomepage();
  $('#promos').innerHTML = '';
  const rows = data.products.filter(matches);
  $('#status').textContent = `${rows.length} produkter visas`;
  $('#products').innerHTML = rows.map(productCard).join('') || '<p>Inga produkter matchar sökningen.</p>';
}

function renderProductPage(id) {
  const product = data.products.find(row => row.id === id);
  setListingVisibility(false);
  $('#status').textContent = '';
  if (!product) {
    document.title = 'Produkten hittades inte — Prislyktan';
    $('#detail').innerHTML = `<div class="panel not-found"><p class="eyebrow">404</p>
      <h1>Produkten hittades inte</h1><p>Kontrollera länken eller gå tillbaka till katalogen.</p>
      <a class="back" href="/">← Alla produkter</a></div>`;
    return;
  }
  const offers = data.offers.filter(offer => offer.product_id === id);
  document.title = `${product.name} ${product.variant} ${product.capacity} — Prislyktan`;
  $('#detail').innerHTML = `<a class="back" href="/">← Alla produkter</a>
    <div class="panel"><p class="muted">${product.category} · ${product.brand}</p>
      <h1>${product.name}</h1>
      <p><strong>Modell:</strong> ${product.model} · <strong>Variant:</strong> ${product.variant} ·
        <strong>Kapacitet:</strong> ${product.capacity}</p><p>${product.description}</p></div>
    <div class="tabs" role="tablist">
      <button role="tab" aria-selected="true" data-tab="offers">Erbjudanden (${offers.length})</button>
      <button role="tab" aria-selected="false" data-tab="specs">Specifikationer</button>
      <button role="tab" aria-selected="false" data-tab="history">Prishistorik</button>
    </div><section id="tabbody"></section>`;
  $('#detail').querySelector('.tabs').onclick = event => {
    if (!event.target.dataset.tab) return;
    document.querySelectorAll('[role=tab]').forEach(tab =>
      tab.setAttribute('aria-selected', String(tab === event.target)));
    renderTab(product, offers, event.target.dataset.tab);
  };
  renderTab(product, offers, 'offers');
}

function renderTab(product, offers, name) {
  if (name === 'specs') {
    $('#tabbody').innerHTML = `<table class="specs"><caption>Specifikationer för ${product.name}</caption>
      ${Object.entries(product.specs).map(([key, value]) => `<tr><th>${key}</th><td>${value}</td></tr>`).join('')}</table>`;
    return;
  }
  if (name === 'history') {
    $('#tabbody').innerHTML = '<div class="panel"><h2>Prishistorik</h2><p>Senaste 30 dagarna: stabil prisnivå. Historiken är vägledande; butikens aktuella pris gäller.</p></div>';
    return;
  }
  $('#tabbody').innerHTML = `<div class="panel"><label><input id="includeShipping" type="checkbox" checked>
    Visa totalpris inklusive frakt</label></div><div class="offers">${offers.map(offer => `<article class="offer">
      <div><h2>${offer.retailer_name}</h2><p>Betyg ${offer.retailer_rating} ·
        ${offer.stock === 'in_stock' ? 'I lager' : 'Få i lager'} · ${offer.delivery}</p>
        ${offer.quote_note ? `<p class="stale">${offer.quote_note}</p>` : ''}</div>
      <div><span class="price" data-base="${offer.quote_ore}" data-ship="${offer.shipping_ore}">
        ${sek(offer.quote_ore + offer.shipping_ore)}</span>
        <p class="shipping">Pris ${sek(offer.quote_ore)} + frakt ${sek(offer.shipping_ore)}</p></div>
      <div>${offer.variant}<br>${offer.capacity}</div>
      <a class="offer-link" href="${offer.retailer_url}">Till ${offer.retailer_name}</a></article>`).join('')}</div>`;
  $('#includeShipping').onchange = event => document.querySelectorAll('.price').forEach(price => {
    price.textContent = sek(Number(price.dataset.base) + (event.target.checked ? Number(price.dataset.ship) : 0));
  });
}

$('#search').onsubmit = event => {
  event.preventDefault();
  query = $('#q').value.trim();
  category = '';
  window.history.pushState(null, '', query ? `/?q=${encodeURIComponent(query)}` : '/');
  renderCategories();
  renderProducts(!query);
};

window.addEventListener('popstate', () => {
  ({ query, category } = urlState());
  $('#q').value = query;
  renderCategories();
  const wanted = requestedProductId();
  if (wanted) renderProductPage(wanted);
  else renderProducts(!query && !category);
});

boot().catch(error => {
  $('#status').textContent = 'Katalogen kunde inte laddas: ' + error.message;
});
