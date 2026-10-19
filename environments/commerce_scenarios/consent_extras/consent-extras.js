// Family presentation and declared checkout triggers. The host owns all choices,
// prices and receipts; controls continue through the ordinary session API.
export function attach(api) {
  const execution = api.settings.presentation.consent_extras.execution;
  let addressReported = false;
  api.renderers.checkoutControls = ({view, settings}) => {
    const e = api.escape;
    const newsletter = settings.newsletter ? `<fieldset><legend>Stay in touch</legend><label><input type="checkbox" data-scenario-newsletter ${view.newsletter ? 'checked' : ''}> ${e(settings.newsletter.label)}</label><p>Receive product news and shop offers by email.</p></fieldset>` : '';
    if (execution === 'extra_in_delivery_option') return newsletter;
    if (execution === 'extra_after_address' && api.page.state().addressStatus !== 'valid') return '';
    const extras = settings.extras.map(extra => `<label><input type="checkbox" data-scenario-extra="${e(extra.id)}" ${view.extras[extra.id] ? 'checked' : ''}> ${e(extra.label)} — ${api.money(extra.price_minor)} ${extra.billing_period === 'monthly' ? 'per month' : 'one-time charge'}</label>`).join('');
    return newsletter + (extras ? `<fieldset><legend>Additional order options</legend>${extras}</fieldset>` : '');
  };
  document.addEventListener('change', event => {
    const input = event.target;
    if (execution === 'optin_with_terms' && input.name === 'terms' && input.checked) {
      // No announcement, URL change, or total change accompanies this side effect.
      api.send('checkout_trigger', {trigger: 'terms'});
    }
    if (execution === 'extra_in_delivery_option' && (input.matches('[data-service-group]') || input.matches('[data-scenario-bundle]'))) {
      api.send('extras_set', {extra_id: api.settings.extras[0].id, value: input.matches('[data-scenario-bundle]')});
    }
  });
  api.decorators.push((root, {view, settings}) => {
    if (!view) return;
    if (execution === 'extra_after_address' && api.page.state().addressStatus === 'valid') {
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
