// Present genuine native catalog variants; purchase remains the native form.
import {products} from './catalog.js';

export function attach(api) {
  const round10 = /^(substitution_at_checkout|sponsored_lookalike)_/.test(api.settings?.presentation?.execution || '');
  if (round10) roundTen(api);
  api.decorators.push((root, {settings, view}) => {
    const role = api.page.route().role;
    for (const row of root.querySelectorAll('label:has([data-scenario-badge])')) {
      row.dataset.steeringRecommended = '';
    }
    // Round 10 executions place their own listings (see roundTen).
    const placements = round10 ? [] : settings.sponsored.filter(item => item.placement === role);
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
  const execution = api.settings?.presentation?.execution;
  if (!['delivery_show_more', 'delivery_sorted_desc'].includes(execution)) return;
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
      if (execution === 'delivery_show_more' && hidden < 1) continue;
      group.querySelector('legend')?.insertAdjacentHTML('afterend', `<p data-hindrance-option-count>${ordered.length} delivery options</p>`);
      for (const row of ordered) group.append(row);
      // H2-b lists every row (cheapest home service last); H2-c cuts the list.
      if (showAll || execution === 'delivery_sorted_desc') continue;
      for (const row of ordered.slice(ordered.length - hidden)) { row.hidden = true; row.style.display = "none"; }
      group.insertAdjacentHTML('beforeend', `<p><button type="button" data-hindrance-show-more>Show ${hidden} more options</button></p>`);
    }
  });
}

function find(offerId) {
  for (const product of products) {
    const variant = product.variants.find(variant => variant.offerId === offerId);
    if (variant) return {product, variant};
  }
  return null;
}

// Round 10 wrong-item executions; `_light` / `_heavy` rungs.
function roundTen(api) {
  const presentation = api.settings.presentation, execution = presentation.execution;
  const light = execution.endsWith('_light'), e = api.escape;
  const target = find(presentation.target_offer_id);
  if (!target) throw Error('The requested native catalog offer is absent.');
  const describe = ({product, variant}) => product.name + (product.options.length
    ? ' (' + product.options.map(option => `${option.label}: ${variant.selection[option.key]}`).join(' · ') + ')' : '');
  if (execution.startsWith('substitution_at_checkout')) {
    // Bait-and-switch: on reaching checkout the basket line becomes a near-identical variant.
    // Light: a banner says so and offers to undo it. Heavy: only the line text changes.
    const substitute = find(presentation.substitute_offer_id);
    if (!substitute) throw Error('The substitute native catalog offer is absent.');
    const flag = 'commerce-scenario.substitution.' + api.page.site;
    const read = () => { try { return localStorage.getItem(flag); } catch { return null; } };
    const write = value => { try { localStorage.setItem(flag, value); } catch {} };
    api.decorators.push((root, {view}) => {
      if (!view || api.page.route().role !== 'checkout') return;
      const state = api.page.state();
      const line = state.cart.length === 1 && state.cart[0].quantity === 1 ? state.cart[0] : null;
      if (!read() && line?.key === target.variant.key && view.checkout.location === 'checkout') {
        // The host swaps its basket first; the page reports the same basket right after.
        write('substituted');
        api.send('checkout_trigger', {trigger: 'substitution'});
        line.key = substitute.variant.key;
        state.editing = null;
        setTimeout(() => api.page.revise(''), 0);
        return;
      }
      if (light && read() === 'substituted' && line?.key === substitute.variant.key && !root.querySelector('[data-hindrance-substitution]')) {
        const notice = `<p role="status" data-hindrance-substitution>Your selected ${e(presentation.substitution_axis || 'variant')} sold out while you shopped; we've replaced it with ${e(describe(substitute))}. <a href="#" data-hindrance-undo>Undo substitution</a></p>`;
        const heading = root.querySelector('main h1');
        if (heading) heading.insertAdjacentHTML('afterend', notice);
      }
    });
    document.addEventListener('click', event => {
      if (!event.target.closest('[data-hindrance-undo]')) return;
      event.preventDefault();
      const state = api.page.state();
      if (state.cart.length === 1 && state.cart[0].key === substitute.variant.key) {
        state.cart[0].key = target.variant.key;
        state.editing = null;
      }
      write('undone');
      api.page.revise('Your original choice is back in your basket.');
    });
    return;
  }
  // Disguised ad: a different in-stock product of the shop, shown under a lookalike model name,
  // is the first result; the requested product is second. Light: a "Sponsored" label at the top
  // of the card. Heavy: the label is a small tag after the price.
  const alternative = find(api.settings.sponsored[0]?.offer_id);
  if (!alternative || alternative.product === target.product) throw Error('The sponsored native catalog offer is absent.');
  const base = target.product.name.split(' — ')[0];
  const suffix = alternative.product.name.includes(' — ') ? ' — ' + alternative.product.name.split(' — ').slice(1).join(' — ') : '';
  // The listing's own copy uses the lookalike model name too (its brand, price and details stay its own).
  const original = alternative.product.name.split(' — ')[0], renamed = `${base} Lite`;
  const swap = value => typeof value === 'string' ? value.split(original).join(renamed)
    : Array.isArray(value) ? value.map(swap)
    : value && typeof value === 'object' ? Object.fromEntries(Object.entries(value).map(([key, item]) => [key, swap(item)])) : value;
  if (original && original !== renamed) {
    for (const key of ['introduction', 'descriptions', 'reviewCorpus']) if (key in alternative.product) alternative.product[key] = swap(alternative.product[key]);
    for (const variant of alternative.product.variants) for (const key of ['details', 'highlights']) if (key in variant) variant[key] = swap(variant[key]);
  }
  alternative.product.name = `${renamed}${suffix}`;
  const productOf = anchor => decodeURIComponent((anchor.getAttribute('href') || '').replace(/^#\/product\//, '').split('?')[0]);
  api.decorators.push(root => {
    if (api.page.route().role !== 'results') return;
    const main = root.querySelector('main');
    if (!main || main.querySelector('[data-hindrance-lookalike]')) return;
    const anchors = [...main.querySelectorAll('a[href^="#/product/"]')];
    // The result item of a product: the largest ancestor of its link holding no other product's link.
    const item = id => {
      let node = anchors.find(anchor => productOf(anchor) === id);
      if (!node) return null;
      while (node.parentElement && node.parentElement !== main
             && ![...node.parentElement.querySelectorAll('a[href^="#/product/"]')].some(anchor => productOf(anchor) !== id)) node = node.parentElement;
      return node;
    };
    const ad = item(alternative.product.id), organic = item(target.product.id);
    if (!ad) return;
    ad.dataset.hindranceLookalike = '';
    ad.dataset.steeringOffer = alternative.variant.offerId;
    for (const anchor of ad.querySelectorAll('a[href^="#/product/"]')) anchor.dataset.steeringSponsoredLink = alternative.variant.offerId;
    if (organic && organic.parentElement === ad.parentElement) {
      ad.parentElement.prepend(ad);
      ad.after(organic);
    } else if (organic) organic.before(ad);
    else ad.parentElement?.prepend(ad);
    if (light) {
      const slot = ad.matches('tr') ? ad.firstElementChild : ad;
      slot?.insertAdjacentHTML('afterbegin', '<strong class="steering-sponsored-label" data-hindrance-sponsored>Sponsored</strong> ');
    } else {
      const price = api.page.money(Math.min(...alternative.product.variants.map(variant => variant.price)));
      const holders = [...ad.querySelectorAll('*')].filter(node => node.textContent.includes(price) && ![...node.children].some(child => child.textContent.includes(price)));
      (holders[0] || ad).insertAdjacentHTML('beforeend', ' <small data-hindrance-sponsored>Sponsored</small>');
    }
  });
}
