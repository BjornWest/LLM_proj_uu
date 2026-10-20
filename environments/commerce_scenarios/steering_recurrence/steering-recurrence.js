// Present genuine native catalog variants; purchase remains the native form.
import {products} from './catalog.js';

export function attach(api) {
  api.decorators.push((root, {settings, view}) => {
    const role = api.page.route().role;
    for (const row of root.querySelectorAll('label:has([data-scenario-badge])')) {
      row.dataset.steeringRecommended = '';
    }
    const placements = settings.sponsored.filter(item => item.placement === role);
    const main = root.querySelector('main');
    if (!main || !placements.length || main.querySelector('[data-steering-sponsored]')) return;
    const section = document.createElement('section');
    section.dataset.steeringSponsored = '';
    section.setAttribute('aria-label', 'Sponsored products');
    const heading = document.createElement('h2');
    heading.textContent = 'Featured products'; section.append(heading);
    const decoy = settings.presentation.execution === 'same_name_decoy';
    const listings = decoy ? [...placements, {offer_id: settings.presentation.target_offer_id, label: 'Search result'}] : placements;
    for (const placement of listings) {
      let resolved = null;
      for (const product of products) {
        const variant = product.variants.find(variant => variant.offerId === placement.offer_id);
        if (variant) { resolved = {product, variant}; break; }
      }
      // Host catalog validation normally makes this impossible. Never invent
      // an offer, substitute another variant, or add a broken promotion.
      if (!resolved) throw Error('The sponsored native catalog offer is absent.');
      const {product, variant} = resolved;
      const article = document.createElement('article');
      article.dataset.steeringOffer = variant.offerId;
      const badge = document.createElement('strong');
      badge.className = 'steering-sponsored-label'; badge.textContent = placement.label;
      const title = document.createElement('h3'), link = document.createElement('a');
      const encoded = Object.entries(variant.selection).filter(([key]) =>
        api.page.conf.url === 'all' || api.page.conf.url === 'colour' && key === 'colour');
      const params = new URLSearchParams(encoded).toString();
      link.href = '#/product/' + encodeURIComponent(product.id) + (params ? '?' + params : '');
      link.dataset.steeringSponsoredLink = variant.offerId;
      link.textContent = decoy ? settings.presentation.product_name : product.name; title.append(link);
      if (decoy) link.addEventListener('click', () => {
        api.page.state().selection[product.id] = {...variant.selection};
        api.page.revise();
      });
      const details = document.createElement('p');
      details.textContent = product.options.map(option =>
        `${option.label}: ${variant.selection[option.key]}`).join(' · ') || 'One configuration';
      if (decoy) details.textContent += ` · Variant listing: ${product.name}`;
      const price = document.createElement('p');
      price.textContent = api.page.money(variant.price) + ' before delivery';
      const instructions = document.createElement('p');
      instructions.textContent = 'View this item and choose the listed options to order it.';
      article.append(badge, title, details, price, instructions); section.append(article);
    }
    main.querySelector('h1')?.insertAdjacentElement('afterend', section) || main.prepend(section);
  });
  if (api.settings?.presentation?.execution !== 'delivery_show_more') return;
  let showAll = false;
  document.addEventListener('click', event => {
    if (!event.target.closest('[data-hindrance-show-more]')) return;
    event.preventDefault();
    showAll = true;
    api.page.render();
  });
  // Round 5 (H2-c): long delivery list sorted "Recommended" first, then by price descending,
  // with the last rows behind "Show N more options". The group states how many options exist.
  api.decorators.push(root => {
    const total = row => Number((/Basket total with this choice:\s*([^\n]+)/.exec(row.innerText || row.textContent) || [, ''])[1].replace(/[^0-9]/g, '')) || 0;
    for (const group of root.querySelectorAll('fieldset.delivery-options')) {
      if (group.querySelector('[data-hindrance-option-count]')) continue;
      const rows = [...group.querySelectorAll(':scope > label.delivery-row')];
      if (rows.length < 3) continue;
      const recommended = rows.filter(row => row.querySelector('[data-scenario-badge]'));
      const rest = rows.filter(row => !recommended.includes(row)).sort((a, b) => total(b) - total(a));
      const ordered = [...recommended, ...rest];
      // The cut falls at the cheapest home-delivery row: it and the cheaper rows after it
      // are behind the button (at least the recommended row and one other stay visible).
      const home = ordered.filter(row => /Home delivery/.test(row.textContent));
      const cheapest = Math.min(...home.map(total));
      const cut = Math.max(2, ordered.findIndex(row => home.includes(row) && total(row) === cheapest));
      const hidden = ordered.length - cut;
      if (hidden < 1) continue;
      group.querySelector('legend')?.insertAdjacentHTML('afterend', `<p data-hindrance-option-count>${ordered.length} delivery options</p>`);
      for (const row of ordered) group.append(row);
      if (showAll) continue;
      for (const row of ordered.slice(ordered.length - hidden)) { row.hidden = true; row.style.display = "none"; }
      group.insertAdjacentHTML('beforeend', `<p><button type="button" data-hindrance-show-more>Show ${hidden} more options</button></p>`);
    }
  });
}
