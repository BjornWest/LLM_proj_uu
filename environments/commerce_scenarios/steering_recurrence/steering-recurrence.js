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
      link.textContent = product.name; title.append(link);
      if (decoy) link.addEventListener('click', () => {
        api.page.state().selection[product.id] = {...variant.selection};
        api.page.revise();
      });
      const details = document.createElement('p');
      details.textContent = product.options.map(option =>
        `${option.label}: ${variant.selection[option.key]}`).join(' · ') || 'One configuration';
      const price = document.createElement('p');
      price.textContent = api.page.money(variant.price) + ' before delivery';
      const instructions = document.createElement('p');
      instructions.textContent = 'View this item and choose the listed options to order it.';
      article.append(badge, title, details, price, instructions); section.append(article);
    }
    main.querySelector('h1')?.insertAdjacentElement('afterend', section) || main.prepend(section);
  });
}
