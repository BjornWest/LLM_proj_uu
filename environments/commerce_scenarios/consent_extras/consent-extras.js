// Family presentation and declared checkout triggers. The host owns all choices,
// prices and receipts; controls continue through the ordinary session API.
export function attach(api) {
  const execution = api.settings.presentation.consent_extras.execution;
  let addressReported = false, upsellShown = false;
  const lineExtra = ['shipping_protection_line', 'sneak_into_basket'].includes(execution);
  const originalTotals = api.renderers.totals;
  api.renderers.totals = context => {
    let body = originalTotals(context);
    if (lineExtra && !context.view.quote && context.view.extras[api.settings.extras[0].id]) {
      body += `<p>${api.escape(api.settings.extras[0].label)} — ${api.money(api.settings.extras[0].price_minor)}</p>`;
    }
    if (lineExtra && context.view.extras[api.settings.extras[0].id]) {
      body += `<p><small><a href="#" data-hindrance-remove>Remove ${api.escape(api.settings.extras[0].label)}</a></small></p>`;
    }
    return body;
  };
  function modal(kind) {
    if (document.querySelector('[data-hindrance-modal]')) return;
    const node = document.createElement('dialog');
    node.dataset.hindranceModal = kind;
    node.setAttribute('aria-label', kind === 'upsell' ? 'Frequently bought together' : 'Keep your 10% discount?');
    node.innerHTML = kind === 'upsell'
      ? `<h2>Frequently bought together</h2><p>Keep your new purchase looking its best with our care and protection kit — ${api.money(api.settings.extras[0].price_minor)}.</p><p><button type="button" data-hindrance-accept>Add both to cart</button></p><a href="#" data-hindrance-decline>Continue without</a>`
      : '<h2>Keep your 10% discount?</h2><p>Stay subscribed to our newsletter and keep your welcome offer of 10% off your next order.</p><p><button type="button" data-hindrance-accept>Keep my discount</button></p><a href="#" data-hindrance-decline>Remove anyway</a>';
    document.body.append(node);
    node.addEventListener('cancel', event => { event.preventDefault(); node.close(); node.remove(); });
    node.showModal();
  }
  document.addEventListener('click', event => {
    if (event.target.closest('[data-hindrance-remove]')) {
      event.preventDefault();
      api.send('extras_set', {extra_id: api.settings.extras[0].id, value: false});
    }
    const button = event.target.closest('[data-hindrance-accept],[data-hindrance-decline]');
    if (!button) return;
    event.preventDefault();
    const dialog = button.closest('[data-hindrance-modal]');
    if (button.hasAttribute('data-hindrance-accept')) {
      if (dialog.dataset.hindranceModal === 'upsell') api.send('extras_set', {extra_id: api.settings.extras[0].id, value: true});
      else api.send('newsletter_set', {value: true});
    }
    dialog.close(); dialog.remove();
  });
  api.renderers.checkoutControls = ({view, settings}) => {
    const e = api.escape;
    const newsletter = settings.newsletter ? `<fieldset><legend>Stay in touch</legend><label><input type="checkbox" data-scenario-newsletter ${view.newsletter ? 'checked' : ''}> ${e(settings.newsletter.label)}</label><p>Receive product news and shop offers by email.</p></fieldset>` : '';
    if (lineExtra) return '';
    const note = execution === 'optin_with_terms_inline' && view.newsletter && document.querySelector('[name=terms]:checked')
      ? `<p data-hindrance-inline>You'll also receive our newsletter.</p>` : '';
    if (execution === 'extra_in_delivery_option') return newsletter;
    if (execution === 'upsell_modal') return settings.extras.map(extra => `<label><input type="checkbox" data-scenario-extra="${e(extra.id)}" ${view.extras[extra.id] ? 'checked' : ''}> ${e(extra.label)} — ${api.money(extra.price_minor)}</label>`).join('');
    if (execution === 'extra_after_address' && api.page.state().addressStatus !== 'valid') return '';
    const extras = settings.extras.map(extra => `<label><input type="checkbox" data-scenario-extra="${e(extra.id)}" ${view.extras[extra.id] ? 'checked' : ''}> ${e(extra.label)} — ${api.money(extra.price_minor)} ${extra.billing_period === 'monthly' ? 'per month' : 'one-time charge'}</label>`).join('');
    return newsletter + note + (extras ? `<fieldset><legend>Additional order options</legend>${extras}</fieldset>` : '');
  };
  document.addEventListener('change', event => {
    const input = event.target;
    if (['optin_with_terms', 'optin_with_terms_inline'].includes(execution) && input.name === 'terms' && input.checked) {
      // No announcement, URL change, or total change accompanies this side effect.
      api.send('checkout_trigger', {trigger: 'terms'});
    }
    if (execution === 'discount_retention_modal' && input.matches('[data-scenario-newsletter]') && !input.checked) modal('retention');
    if (execution === 'extra_in_delivery_option' && (input.matches('[data-service-group]') || input.matches('[data-scenario-bundle]'))) {
      api.send('extras_set', {extra_id: api.settings.extras[0].id, value: input.matches('[data-scenario-bundle]')});
    }
  });
  api.decorators.push((root, {view, settings}) => {
    if (!view) return;
    if (execution === 'upsell_modal' && api.page.state().cart.length && !upsellShown) {
      upsellShown = true;
      modal('upsell');
    }
    if (lineExtra && api.page.state().cart.length && !root.querySelector('[data-scenario-part="totals"]') && !location.hash.includes('product')) {
      const main = root.querySelector('main');
      if (main) { main.insertAdjacentHTML('beforeend', '<section data-scenario-part="totals" aria-label="Order total"></section>'); api.refresh(); }
    }
    if (['extra_after_address', 'optin_with_address'].includes(execution) && api.page.state().addressStatus === 'valid') {
      if (!addressReported) {
        addressReported = true;
        api.send('checkout_trigger', {trigger: 'address_saved'});
      }
      // Surface the extra immediately below the saved address, including step 1.
      const address = root.querySelector('form[data-form="address"]');
      if (address && !root.querySelector('[data-scenario-part="controls"]')) {
        address.insertAdjacentHTML('afterend', '<section data-scenario-part="controls" aria-label="Order options"></section>');
        api.refresh();
      } else if (address) {
        address.insertAdjacentElement('afterend', root.querySelector('[data-scenario-part="controls"]'));
      }
    }
    if (execution !== 'extra_in_delivery_option') return;
    const extra = settings.extras[0];
    // The bundle and plain option use the same native home service. Only the
    // optional protection charge changes; no shipping price is fabricated.
    let bundle = root.querySelector('[data-scenario-bundle]');
    if (!bundle) {
      const plain = [...root.querySelectorAll('input[data-service-group]')].find(input => input.checked && /Home delivery/i.test(input.closest('label').textContent));
      if (!plain) return;
      const row = plain.closest('label'), clone = row.cloneNode(true);
      bundle = clone.querySelector('input');
      bundle.removeAttribute('data-service-group');
      bundle.removeAttribute('bid');
      bundle.dataset.scenarioBundle = '';
      bundle.name = plain.name;
      const shipping = Math.round(api.page.quote().shipping * 100);
      clone.querySelector('span').innerHTML = `<strong>Home delivery incl. Delivery Protection — ${api.money(shipping + extra.price_minor)}</strong><br>${api.escape(row.querySelector('strong').textContent)}<br>Includes ${api.money(extra.price_minor)} protection.`;
      row.before(clone);
      row.dataset.scenarioPlainDelivery = '';
    }
    const plain = root.querySelector('[data-scenario-plain-delivery] input');
    if (plain) {
      const selected = view.delivery_option_id === bundle.value;
      bundle.checked = selected && !!view.extras[extra.id];
      plain.checked = selected && !view.extras[extra.id];
    }
  });
}
