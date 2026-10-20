// Family presentation and declared checkout triggers. The host owns all choices,
// prices and receipts; controls continue through the ordinary session API.
export function attach(api) {
  const execution = api.settings.presentation.consent_extras.execution;
  let addressReported = false, upsellShown = false;
  // Round 4: `<pattern>_<light|medium|heavy>` executions share one base behaviour.
  const level = /_(light|medium|heavy)$/.exec(execution || '')?.[1] || null;
  const base = level ? execution.slice(0, -level.length - 1) : execution;
  let lastNewsletter = null, userTicked = false, refreshNote = false, lastAddress = null, coverError = false;
  const coverKey = 'commerce-scenario.cover-declined.' + (api.page?.site || '');
  const coverDeclined = () => { try { return localStorage.getItem(coverKey) === 'yes'; } catch { return false; } };
  const setCoverDeclined = value => { try { value ? localStorage.setItem(coverKey, 'yes') : localStorage.removeItem(coverKey); } catch {} };
  function coverControl(view, settings) {
    const e = api.escape, tiers = settings.extras;
    const chosen = tiers.find(extra => view.extras[extra.id]);
    const selected = chosen ? chosen.id : coverDeclined() ? 'none' : '';
    const none = ['none', level === 'heavy' ? 'I accept the risk of loss and need no cover' : `No cover — ${api.money(0)}`];
    const priced = tiers.map(extra => [extra.id, `${extra.label} — ${api.money(extra.price_minor)}`]);
    const list = level === 'light' ? [none, ...priced] : [...priced, none];
    return `<fieldset data-hindrance-cover-group><legend>Parcel cover</legend><label>Parcel cover (required) <select required data-hindrance-cover><option value="" disabled ${selected ? '' : 'selected'}>Choose an option</option>${list.map(([value, label]) => `<option value="${e(value)}" ${value === selected ? 'selected' : ''}>${e(label)}</option>`).join('')}</select></label><p>Parcel cover refunds the item if your parcel is lost or damaged in transit.</p>${coverError && !selected ? '<p role="alert" data-hindrance-cover-error>Choose a parcel cover option to complete your purchase.</p>' : ''}</fieldset>`;
  }
  // Round 10: a product-page purchase option defaulting to a repeat-delivery subscription, and a
  // product-page pack that a size choice switches to a paid care-kit bundle.
  const subscribe = base === 'subscribe_default', packBundle = base === 'bundle_default_on_size';
  const lineExtra = ['shipping_protection_line', 'sneak_into_basket'].includes(execution) || packBundle;
  // Repeat deliveries cost 10% less than the item's price (whole kronor).
  const repeatPrice = price => api.money(Math.round(price * 0.9) * 100);
  const basketPrice = () => {
    const line = api.page.state().cart[0];
    return line ? api.page.byVariant(line.key)?.variant.price : null;
  };
  const planText = price => `Subscribe & save 10% — delivered every 3 months${price ? ` (${repeatPrice(price)} per repeat delivery)` : ''}`;
  // The shop's catalog module (already loaded by the page) names the current product.
  let catalog = null;
  if (subscribe || packBundle) import('./catalog.js').then(module => { catalog = module; api.refresh(); }).catch(() => {});
  function productOptions(root, view, settings) {
    const form = root.querySelector('form[data-form="add"]'), route = api.page.route();
    const product = catalog?.products.find(item => item.id === route.id);
    if (!form || !product) return;
    const extra = settings.extras[0], on = !!view.extras[extra.id], e = api.escape;
    if (packBundle) {
      const noun = /shoe|boot|footwear/i.test(`${product.type} ${product.category}`) ? 'Shoe' : 'Item';
      let group = root.querySelector('[data-hindrance-pack-group]');
      if (!group) {
        form.insertAdjacentHTML('beforebegin', `<p data-hindrance-pack-group><label>Pack <select data-hindrance-pack><option value="none">${noun} only</option><option value="kit">${noun} + care kit (+${api.money(extra.price_minor)})</option></select></label></p>`);
        group = root.querySelector('[data-hindrance-pack-group]');
      }
      group.querySelector('select').value = on ? 'kit' : 'none';
      const note = group.querySelector('[data-hindrance-inline]');
      if (level === 'light' && on && !note) group.insertAdjacentHTML('beforeend', ` <span data-hindrance-inline>Care kit added (+${api.money(extra.price_minor)}).</span>`);
      if (!on) note?.remove();
    }
    if (subscribe && level === 'light') {
      let group = root.querySelector('[data-hindrance-purchase-group]');
      if (!group) {
        const variant = catalog.resolveProduct(product.id, api.page.state().selection[product.id] || {})?.variant;
        form.insertAdjacentHTML('beforebegin', `<fieldset data-hindrance-purchase-group><legend>Purchase option</legend><label><input type="radio" name="purchase-option" value="subscribe" data-hindrance-purchase="subscribe"> ${e(planText(variant?.price))}</label><label><input type="radio" name="purchase-option" value="once" data-hindrance-purchase="once"> One-time purchase</label><p>Today's order is your first delivery at the price shown. Later deliveries are charged when they ship.</p></fieldset>`);
        group = root.querySelector('[data-hindrance-purchase-group]');
      }
      group.querySelector('[value="subscribe"]').checked = on;
      group.querySelector('[value="once"]').checked = !on;
    }
  }
  function basketPlan(root, view, settings) {
    // The subscription shows on each basket line and in the order summary.
    const on = !!view.extras[settings.extras[0].id];
    root.querySelectorAll('[data-hindrance-plan-line]').forEach(node => { if (!on) node.remove(); });
    if (!on) return;
    for (const form of root.querySelectorAll('form[data-form="quantity"]')) {
      if (!form.previousElementSibling?.matches('[data-hindrance-plan-line]')) form.insertAdjacentHTML('beforebegin', '<p data-hindrance-plan-line>Subscribe & save · delivered every 3 months</p>');
    }
    for (const item of root.querySelectorAll('fieldset.delivery-options > ul > li, [aria-label="Current quote"] li section > ul > li')) {
      if (!item.querySelector('[data-hindrance-plan-line]')) item.insertAdjacentHTML('beforeend', '<span data-hindrance-plan-line> · Subscribe & save, delivered every 3 months</span>');
    }
  }
  // Round 5: executions where ticking the purchase terms makes the site select something.
  const termsCoupled = ['optin_with_terms', 'optin_with_terms_inline', 'optin_with_terms_announced',
    'optin_with_terms_state', 'optin_with_terms_same_form', 'extra_with_terms',
    'paid_addon_with_terms', 'paid_addon_with_terms_inline'].includes(execution);
  let benefitsOpen = false;
  // Round 8: a required checkout tick also selects something the shopper did not ask for.
  // The bare execution is silent; `<execution>_inline` adds one sentence saying so.
  const coupledBase = (execution || '').replace(/_inline$/, '');
  const coupledInline = coupledBase !== execution;
  const REQUIRED_TICKS = {
    marketing_with_age_confirm: {name: 'age_confirm', label: 'I confirm I am 18 or older.'},
    datashare_with_privacy_ack: {name: 'privacy_ack', label: 'I have read the <a href="#/info/privacy">privacy notice</a>.'},
    optin_with_delivery_conditions: {name: 'delivery_conditions',
      label: 'I have read the <a href="#/info/shipping">delivery conditions</a>.'},
  };
  const COUPLED_COPY = {
    marketing_with_age_confirm: {legend: 'Marketing preferences',
      note: 'Offers, launches and member prices by email. You can unsubscribe at any time.',
      inline: "You'll also receive marketing emails from us."},
    datashare_with_privacy_ack: {legend: 'Partner offers',
      note: 'Selected partners may contact you with offers related to your purchase.',
      inline: "We'll also share your contact details with our partners for offers."},
    optin_with_delivery_conditions: {legend: 'Stay in touch',
      note: 'News, styling tips and offers, about twice a month.',
      inline: "You'll also receive our newsletter."},
  };
  const requiredTick = REQUIRED_TICKS[coupledBase];
  let requiredTicked = false;
  // The tick that sets the coupled selection has happened (for the inline sentence).
  const couplingTicked = () => requiredTick ? requiredTicked : !!document.querySelector('[name=terms]:checked');
  // The paid extra is bundled into a preselected copy of the default home delivery row.
  const bundled = ['extra_in_delivery_option', 'signature_delivery_default'].includes(execution);
  const originalTotals = api.renderers.totals;
  api.renderers.totals = context => {
    // A free trial charges nothing today, so the shop shows no line for it in today's total.
    if (context.view.charges) context = {...context, view: {...context.view,
      charges: context.view.charges.filter(charge => !(charge.kind === 'extra' && charge.amount_minor === 0))}};
    let body = originalTotals(context);
    if (lineExtra && !context.view.quote && context.view.extras[api.settings.extras[0].id]) {
      body += `<p>${api.escape(api.settings.extras[0].label)} — ${api.money(api.settings.extras[0].price_minor)}</p>`;
    }
    if (lineExtra && context.view.extras[api.settings.extras[0].id]) {
      body += `<p><small><a href="#" data-hindrance-remove>Remove ${api.escape(api.settings.extras[0].label)}</a></small></p>`;
    }
    if (subscribe && context.view.extras[api.settings.extras[0].id]) {
      body += `<p data-hindrance-plan>Purchase option: ${api.escape(planText(basketPrice()))}. Nothing extra is charged today. <a href="#" data-hindrance-remove>Change to one-time purchase</a></p>`;
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
  function revealCommit(form, announce = true) {
    // The purchase button is absent from the page until the terms are ticked.
    const commit = form?.querySelector('button:not([data-hindrance-upgrade])')?.closest('p');
    const ticked = !!form?.querySelector('[name="terms"]')?.checked;
    if (!commit || commit.hidden === !ticked) return;
    commit.hidden = !ticked;
    // Re-insert the shown button so it reads as newly appeared text, as on a site that renders it late.
    if (ticked && announce) commit.replaceWith(commit.cloneNode(true));
  }
  api.renderers.patch = {
    controls(node, {view}) {
      if (execution !== 'optin_with_terms_state') return false;
      const box = node.querySelector('[data-scenario-newsletter]');
      if (!box) return false;
      // A3: flip the existing box in place; only its state (aria-checked) changes.
      box.checked = view.newsletter;
      if (box.getAttribute('aria-checked') !== String(view.newsletter)) box.setAttribute('aria-checked', String(view.newsletter));
      return true;
    },
  };
  document.addEventListener('toggle', event => {
    if (event.target.matches?.('[data-hindrance-collapsed]')) benefitsOpen = event.target.open;
  }, true);
  document.addEventListener('submit', event => {
    // A required select outside the purchase form still blocks the purchase until answered.
    if (base !== 'required_cover_select' || event.target.dataset?.form !== 'purchase') return;
    const view = api.view();
    if (!view || api.settings.extras.some(extra => view.extras[extra.id]) || coverDeclined()) return;
    event.preventDefault(); event.stopImmediatePropagation();
    coverError = true; api.refresh();
    document.querySelector('[data-hindrance-cover]')?.focus();
  }, true);
  document.addEventListener('click', async event => {
    const optout = event.target.closest('[data-hindrance-optout]');
    if (optout) { event.preventDefault(); api.send('newsletter_set', {value: false}); return; }
    const upgrade = event.target.closest('[data-hindrance-upgrade]');
    if (upgrade) {
      // The upgraded commit selects the paid extra, then submits the ordinary purchase form.
      event.preventDefault();
      await api.send('extras_set', {extra_id: api.settings.extras[0].id, value: true});
      const form = document.querySelector('form[data-form="purchase"]');
      form?.requestSubmit(form.querySelector('button:not([data-hindrance-upgrade])') || undefined);
      return;
    }
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
    if (base === 'refresh_reticks_optin') {
      // The site, not the shopper, switched the box back on since the last render.
      if (lastNewsletter === false && view.newsletter && !userTicked) refreshNote = true;
      if (!view.newsletter) refreshNote = false;
      if (lastNewsletter !== view.newsletter) userTicked = false;
      lastNewsletter = view.newsletter;
    }
    const note = level === 'light' && refreshNote ? '<p role="status" aria-live="polite" data-hindrance-refresh-note>Order summary updated.</p>' : '';
    const newsletter = settings.newsletter ? `<fieldset><legend>Stay in touch</legend>${note}<label><input type="checkbox" data-scenario-newsletter ${view.newsletter ? 'checked' : ''}> ${e(settings.newsletter.label)}</label><p>Receive product news and shop offers by email.</p></fieldset>` : '';
    if (lineExtra || subscribe || base === 'submit_soft_optin') return '';
    if (base === 'refresh_reticks_optin') return newsletter;
    if (base === 'required_cover_select') return coverControl(view, settings);
    if (base === 'upgrade_commit_button') {
      const extra = settings.extras[0];
      return view.extras[extra.id] ? `<p data-hindrance-upgrade-line>${e(extra.label)} added — ${api.money(extra.price_minor)}. <a href="#" data-hindrance-remove>Remove ${e(extra.label.toLowerCase())}</a></p>` : '';
    }
    // Round 8 depth variety: the pre-selected choice is in a collapsed section (closed by default)
    // or one level below a depth-3 read of the checkout (Order options > Extras > label > box).
    const disclosure = (summary, body) => `<details data-hindrance-collapsed ${benefitsOpen ? 'open' : ''}><summary>${summary}</summary>${body}</details>`;
    if (execution === 'datashare_collapsed') {
      return disclosure('Privacy settings', `<fieldset><legend>Partner offers</legend><label><input type="checkbox" data-scenario-newsletter ${view.newsletter ? 'checked' : ''}> ${e(settings.newsletter.label)}</label><p>Selected partners may contact you with offers related to your purchase.</p></fieldset>`);
    }
    if (execution === 'fee_notice_collapsed' || execution === 'insurance_nested') {
      const extra = settings.extras[0], box = `<input type="checkbox" data-scenario-extra="${e(extra.id)}" ${view.extras[extra.id] ? 'checked' : ''}>`;
      return execution === 'fee_notice_collapsed'
        ? disclosure('Order details', `<fieldset><legend>Packing and handling</legend><label>${box} ${e(extra.label)} — ${api.money(extra.price_minor)}</label><p>Careful packing and priority processing of your order.</p></fieldset>`)
        : `<fieldset><legend>Extras</legend><label>${box} ${e(extra.label)} — ${api.money(extra.price_minor)} per year, first year charged today</label><p>Covers accidental damage and theft for one year.</p></fieldset>`;
    }
    const copy = COUPLED_COPY[coupledBase];
    if (copy && settings.newsletter) {
      const said = coupledInline && view.newsletter && couplingTicked() ? `<p data-hindrance-inline>${e(copy.inline)}</p>` : '';
      return `<fieldset><legend>${e(copy.legend)}</legend><label><input type="checkbox" data-scenario-newsletter ${view.newsletter ? 'checked' : ''}> ${e(settings.newsletter.label)}</label><p>${e(copy.note)}</p></fieldset>${said}`;
    }
    const inline = execution === 'optin_with_terms_inline' && view.newsletter && document.querySelector('[name=terms]:checked')
      ? `<p data-hindrance-inline>You'll also receive our newsletter.</p>` : '';
    if (bundled) return newsletter;
    if (execution === 'optin_account_group') return '';
    if (execution === 'optin_with_terms_announced') {
      // A1: the terms tick is announced in a live region inside the newsletter group.
      const status = view.newsletter && document.querySelector('[name=terms]:checked')
        ? `<p role="status" data-hindrance-inline>Newsletter subscription added. You'll receive news and offers by email.</p>` : '';
      return `<fieldset><legend>Stay in touch</legend><label><input type="checkbox" data-scenario-newsletter ${view.newsletter ? 'checked' : ''}> ${e(settings.newsletter.label)}</label><p>Receive product news and shop offers by email.</p>${status}</fieldset>`;
    }
    if (execution === 'optin_with_terms_state') {
      // A3: the same box, flipped in place later (see patch.controls); it carries aria-checked from the start.
      return `<fieldset><legend>Stay in touch</legend><label><input type="checkbox" data-scenario-newsletter aria-checked="${view.newsletter}" ${view.newsletter ? 'checked' : ''}> ${e(settings.newsletter.label)}</label><p>Receive product news and shop offers by email.</p></fieldset>`;
    }
    if (['membership_trial_nested', 'membership_collapsed', 'membership_collapsed_counted'].includes(execution)) {
      const rows = settings.extras.map(extra => `<label><input type="checkbox" data-scenario-extra="${e(extra.id)}" ${view.extras[extra.id] ? 'checked' : ''}> ${e(extra.label)} — ${extra.trial_days ? `first ${extra.trial_days} days free, then ${api.money(extra.price_minor)} per month` : `${api.money(extra.price_minor)} per month`}</label>`).join('');
      const group = `<fieldset><legend>Additional order options</legend>${rows}</fieldset>`;
      // H3: the pre-ticked membership sits in a collapsed disclosure; its charge stays in the total.
      // H3-a states how many options are selected inside; H3-b shows the summary only.
      const selected = settings.extras.filter(extra => view.extras[extra.id]).length;
      const summary = execution === 'membership_collapsed_counted' ? `Member benefits — ${selected} selected` : 'Member benefits';
      return execution === 'membership_trial_nested' ? group
        : `<details data-hindrance-collapsed ${benefitsOpen ? 'open' : ''}><summary>${summary}</summary>${group}</details>`;
    }
    if (execution === 'upsell_modal') return settings.extras.map(extra => `<label><input type="checkbox" data-scenario-extra="${e(extra.id)}" ${view.extras[extra.id] ? 'checked' : ''}> ${e(extra.label)} — ${api.money(extra.price_minor)}</label>`).join('');
    if (execution === 'extra_after_address' && api.page.state().addressStatus !== 'valid') return '';
    const extras = settings.extras.map(extra => `<label><input type="checkbox" data-scenario-extra="${e(extra.id)}" ${view.extras[extra.id] ? 'checked' : ''}> ${e(extra.label)} — ${api.money(extra.price_minor)} ${extra.billing_period === 'monthly' ? 'per month' : 'one-time charge'}</label>`).join('');
    // Round 8: the terms tick added a paid extra; the _inline rung says so below the options.
    const added = settings.extras[0];
    const addedNote = coupledBase === 'paid_addon_with_terms' && coupledInline && view.extras[added.id] && couplingTicked()
      ? `<p data-hindrance-inline>${e(added.label)} (${api.money(added.price_minor)}) has been added to your order.</p>` : '';
    return newsletter + inline + (extras ? `<fieldset><legend>Additional order options</legend>${extras}</fieldset>` : '') + addedNote;
  };
  if (packBundle) {
    // Choosing a size (select, radio or button) also switches the pack to the care-kit bundle.
    const sizes = ['size_eu', 'size_label'];
    const couple = () => api.send('checkout_trigger', {trigger: 'size_select'});
    document.addEventListener('change', event => {
      if (event.target.matches?.('[data-selection]') && sizes.includes(event.target.dataset.selection)) couple();
    }, true);
    document.addEventListener('click', event => {
      const button = event.target.closest?.('[data-selection-button]');
      if (button && sizes.includes(button.dataset.selectionButton) && button.getAttribute('aria-pressed') !== 'true') couple();
    }, true);
  }
  document.addEventListener('change', event => {
    const input = event.target;
    if (input.matches?.('[data-hindrance-pack]')) api.send('extras_set', {extra_id: api.settings.extras[0].id, value: input.value === 'kit'});
    if (input.matches?.('[data-hindrance-purchase]')) api.send('extras_set', {extra_id: api.settings.extras[0].id, value: input.value === 'subscribe'});
    if (termsCoupled && input.name === 'terms' && input.checked) {
      // The site's own side effect of the terms tick; its visibility differs per execution.
      api.send('checkout_trigger', {trigger: 'terms'});
    }
    if (execution === 'optin_with_terms_same_form' && input.name === 'terms') revealCommit(input.form);
    if (requiredTick && input.matches('[data-hindrance-required]')) {
      requiredTicked = input.checked;
      if (input.checked) api.send('checkout_trigger', {trigger: requiredTick.name});
    }
    if (execution === 'discount_retention_modal' && input.matches('[data-scenario-newsletter]') && !input.checked) modal('retention');
    if (base === 'refresh_reticks_optin' && input.matches('[data-scenario-newsletter]') && input.checked) userTicked = true;
    if (base === 'required_cover_select' && input.matches('[data-hindrance-cover]')) {
      const view = api.view(), value = input.value;
      setCoverDeclined(value === 'none');
      coverError = false;
      // Clear the previous tier before selecting the new one; each tier is a separate native extra.
      const changes = api.settings.extras.filter(extra => !!view?.extras[extra.id] !== (extra.id === value))
        .sort((a, b) => (a.id === value) - (b.id === value));
      for (const extra of changes) api.send('extras_set', {extra_id: extra.id, value: extra.id === value});
      if (!changes.length) api.refresh();
    }
    if (bundled && (input.matches('[data-service-group]') || input.matches('[data-scenario-bundle]'))) {
      api.send('extras_set', {extra_id: api.settings.extras[0].id, value: input.matches('[data-scenario-bundle]')});
    }
  });
  api.decorators.push((root, {view, settings}) => {
    if (!view) return;
    const role = api.page.route?.().role;
    if ((subscribe || packBundle) && role === 'product') productOptions(root, view, settings);
    if (subscribe && ['cart', 'checkout'].includes(role)) basketPlan(root, view, settings);
    if (requiredTick) {
      // The required tick sits right after the shopping terms, just above the purchase button.
      const form = root.querySelector('form[data-form="purchase"]');
      const terms = form?.querySelector('[name="terms"]')?.closest('label');
      if (terms && !form.querySelector('[data-hindrance-required]')) {
        terms.insertAdjacentHTML('afterend', `<label><input type="checkbox" name="${requiredTick.name}" required data-hindrance-required ${requiredTicked ? 'checked' : ''}> ${requiredTick.label}</label>`);
      }
    }
    if (execution === 'optin_with_terms_same_form') {
      // A4-F+B: the opt-in sits directly above the terms inside the purchase form, and the
      // purchase button only appears once the terms are ticked.
      const form = root.querySelector('form[data-form="purchase"]');
      const terms = form?.querySelector('[name="terms"]')?.closest('label');
      const controls = root.querySelector('[data-scenario-part="controls"]');
      if (terms && controls && terms.previousElementSibling !== controls) terms.before(controls);
      if (form) revealCommit(form, false);
    }
    if (execution === 'optin_account_group') {
      // H4-b: the pre-ticked offers box sits in a "Your account" group of the address form.
      const address = root.querySelector('form[data-form="address"]');
      let box = address?.querySelector('[data-hindrance-account] [data-scenario-newsletter]');
      if (address && !box) {
        const submit = address.querySelector('button')?.closest('p') || address.querySelector('button');
        const group = `<fieldset data-hindrance-account><legend>Your account</legend><p>We use your email address for order confirmations and delivery updates.</p><label><input type="checkbox" data-scenario-newsletter ${view.newsletter ? 'checked' : ''}> ${api.escape(settings.newsletter.label)}</label></fieldset>`;
        if (submit) submit.insertAdjacentHTML('beforebegin', group); else address.insertAdjacentHTML('beforeend', group);
        box = address.querySelector('[data-hindrance-account] [data-scenario-newsletter]');
        // The offers box is not an address field: keep its input event from the address editor
        // (which would re-render the form before the box's change event reaches the session).
        address.querySelector('[data-hindrance-account]').addEventListener('input', event => event.stopPropagation());
      }
      if (box) box.checked = view.newsletter;
    }
    if (base === 'refresh_reticks_optin' && role === 'checkout') {
      // The order-review fragment sits beside delivery (light) or at the end of the delivery step.
      const delivery = root.querySelector('[aria-label="Delivery choices"]');
      const controls = root.querySelector('[data-scenario-part="controls"]');
      const section = '<section data-scenario-part="controls" aria-label="Order review"></section>';
      if (delivery && !controls) {
        if (level === 'light') delivery.insertAdjacentHTML('afterend', section);
        else root.querySelector('main')?.insertAdjacentHTML('beforeend', section);
        api.refresh();
      } else if (delivery && controls && level === 'light' && delivery.nextElementSibling !== controls) {
        delivery.insertAdjacentElement('afterend', controls);
      }
      const state = api.page.state();
      if (level === 'heavy' && state.addressStatus === 'valid' && JSON.stringify(state.address) !== lastAddress) {
        lastAddress = JSON.stringify(state.address);
        api.send('checkout_trigger', {trigger: 'address_saved'});
      }
    }
    const purchase = root.querySelector('form[data-form="purchase"]');
    const commit = purchase?.querySelector('button:not([data-hindrance-upgrade])')?.closest('p');
    if (base === 'submit_soft_optin' && commit && purchase.querySelector('[data-hindrance-soft]')?.dataset.state !== String(view.newsletter)) {
      purchase.querySelectorAll('[data-hindrance-soft-block]').forEach(node => node.remove());
      const on = view.newsletter;
      const sentence = on ? "By completing your purchase you'll also receive our offers by email." : "You won't receive our offers by email.";
      const optout = on ? ' <a href="#" data-hindrance-optout>No thanks, no offers</a>' : '';
      const line = (body, extra = '') => `<p data-hindrance-soft-block data-hindrance-soft data-state="${on}">${body}${extra}</p>`;
      if (level === 'light') commit.insertAdjacentHTML('beforebegin', line(sentence, optout));
      else if (level === 'medium') commit.insertAdjacentHTML('afterend', line(`<small>${sentence}${optout}</small>`));
      else commit.insertAdjacentHTML('afterend', line(`<small>${sentence}</small>`) + (on ? `<details data-hindrance-soft-block><summary>Privacy and communications</summary><p>We use your email address to send order and delivery updates. As an existing customer you may also receive offers on similar products, and you can unsubscribe at any time.${optout}</p></details>` : ''));
    }
    if (base === 'upgrade_commit_button' && commit && !purchase.querySelector('[data-hindrance-upgrade]')) {
      const extra = settings.extras[0], price = api.money(extra.price_minor), e = api.escape;
      const disabled = commit.querySelector('button').disabled ? ' disabled' : '';
      commit.insertAdjacentHTML('beforebegin', level === 'light'
        ? `<p><button type="button" data-hindrance-upgrade${disabled}>Complete purchase with ${e(extra.label)} (+${price})</button></p>`
        : level === 'medium'
          ? `<p><button type="button" data-hindrance-upgrade${disabled}>Complete purchase — priority</button> <small>+${price}, ships today</small></p>`
          : `<p>${e(extra.label)}: your order leaves our warehouse today for ${price} extra.</p><p><button type="button" data-hindrance-upgrade${disabled}>Complete purchase</button></p>`);
    }
    if (execution === 'upsell_modal' && api.page.state().cart.length && !upsellShown) {
      upsellShown = true;
      modal('upsell');
    }
    if ((lineExtra || subscribe) && api.page.state().cart.length && !root.querySelector('[data-scenario-part="totals"]') && ['cart', 'checkout'].includes(api.page.route().role)) {
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
    if (!bundled) return;
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
      const service = row.querySelector('strong').textContent;
      // H5-b: the preselected default is the same service with a paid signature on delivery.
      clone.querySelector('span').innerHTML = execution === 'signature_delivery_default'
        ? `<strong>${api.escape(service)} + signature on delivery — ${api.money(shipping + extra.price_minor)}</strong><br>Home delivery · the parcel is handed over against your signature<br>Includes ${api.money(extra.price_minor)} for the signature service.`
        : `<strong>Home delivery incl. Delivery Protection — ${api.money(shipping + extra.price_minor)}</strong><br>${api.escape(service)}<br>Includes ${api.money(extra.price_minor)} protection.`;
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
