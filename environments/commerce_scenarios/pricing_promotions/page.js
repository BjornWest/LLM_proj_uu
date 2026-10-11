// Claims are public advertised terms. Payable amounts always come from the host.
import {data} from './world-data.js';

export function attach(api) {
  const pricing = api.presentation.pricing;
  if (!pricing) return;
  const {escape:e, money} = api;
  const variantLabel = id => {
    for (const product of data.products) {
      const variant = product.variants.find(v => v.offerId === id);
      if (variant) return `${product.name} — ${Object.values(variant.selection).join(', ')}`;
    }
    throw Error('Promotion names an unpublished eligible variant');
  };
  const terms = () => pricing.promotions.map(p => `<section><h3>${e(p.code)} — save ${money(p.saving_minor)}</h3><ul>${p.conditions.map(c => `<li>${e(c)}</li>`).join('')}</ul>${p.offer_ids.length ? `<p>Eligible variants: ${p.offer_ids.map(id => e(variantLabel(id))).join('; ')}</p>` : ''}</section>`).join('');
  api.decorators.push(root => {
    // Runtime binds product-native IDs to public page IDs; consult the actual variant.
    const form = root.querySelector('form[data-form="add"]');
    const current = form && api.page.byVariant(form.dataset.key);
    if (current?.product.canonicalProductId === pricing.product_id && !root.querySelector('[data-pricing-terms]')) {
      const claim = pricing.advertised_claim;
      const article = document.createElement('section');
      article.dataset.pricingTerms = '';
      article.setAttribute('aria-label', 'Offers and promotion terms');
      article.innerHTML = `<h2>Offers</h2><p>${claim.kind === 'from_price' ? 'Prices from' : 'Advertised price'} ${money(claim.price_minor)}</p><details><summary>Offer terms</summary><p>Current variant price is shown with the selected options. Delivery and any applicable charges are calculated for the basket.</p><p>Account membership: ${pricing.membership_active ? 'active' : 'inactive'}.</p><p>Prices and promotions checked as of ${e(pricing.quote_as_of)}.</p>${terms()}</details>`;
      form.closest('[data-product-part="buying"]').before(article);
    }
    // Native quote rows contain native pre-discount tariffs. The overlay owns
    // shipping after discount qualification and every complete-basket total.
    const view = api.view();
    if (!view?.overlay_options) return;
    for (const input of root.querySelectorAll('input[data-service-group]')) {
      const row = input.closest('label');
      const option = view.overlay_options.find(o => o.native_option_id === input.value);
      if (!row) continue;
      let target = row.querySelector('[data-pricing-delivery]');
      if (!target) {
        const span = row.querySelector('span');
        if (!span) continue;
        // Keep company, type, location and arrival, replace the two native
        // monetary lines only. Fail closed if the pinned renderer shape changes.
        const html = span.innerHTML;
        const match = html.match(/<br>Delivery for these items:[\s\S]*$/);
        if (!match) throw Error('Pricing delivery row monetary seam changed');
        span.innerHTML = html.slice(0, match.index);
        target = document.createElement('span');
        target.dataset.pricingDelivery = '';
        span.append(target);
      }
      target.innerHTML = option ? `<br>Delivery for these items: ${money(option.shipping_minor)}<br>Basket total with this choice: ${money(option.total_minor)}`
        : '<br>This delivery type is outside this offer. Choose home delivery to see its applicable total.';
    }
  });
}
