// Page side of a commerce scenario. The host owns consent, newsletter, extras,
// promotion codes and every total; this script renders them from the host's
// reply and reports the page-held basket, delivery option and checkout location.
// Family pieces replace the generic renderers through attach(api).
import {data} from './world-data.js';

const settings = data.commerceScenario || null;
const purposes = [['analytics', 'Analytics'], ['personalisation', 'Personalisation'], ['marketing', 'Marketing']];
const inactive = {promotionField: false, ready: Promise.resolve(), sync() {}, chose() {},
  checkoutControls: () => '', totals: () => null, promotionForm: () => '',
  armOrder: async () => true, decorate() {}};

export function commerceScenario(page) {
  if (!settings) return inactive;
  const e = value => page.e(value), money = minor => page.money(minor / 100);
  const sessionKey = `commerce-scenario.session.${page.site}`;
  let session = localStorage.getItem(sessionKey);
  if (!session) { session = crypto.randomUUID(); localStorage.setItem(sessionKey, session); }
  let view = null, queue = Promise.resolve(), pending = 0, lastSync = null, problem = '';
  let pane = false, toggles = null, displayedTotal = null;

  const mark = () => { document.documentElement.dataset.commerceScenario = pending ? 'busy' : 'ready'; };

  // One request at a time, in page order, so the host sees one history.
  function send(op, fields = {}) {
    pending++; mark();
    const run = async () => {
      let reply = null;
      try {
        const response = await fetch('/api/session', {method: 'POST',
          headers: {'Content-Type': 'application/json'}, body: JSON.stringify({op, session, ...fields})});
        const value = await response.json();
        if (!response.ok) throw Error(value.error || 'The shop could not save this choice.');
        view = reply = value; problem = '';
      } catch (failure) { problem = failure.message; }
      pending--; mark();
      if (reply?.directives.reset_delivery) resetDelivery();
      refresh();
      return reply;
    };
    queue = queue.then(run, run);
    return queue;
  }

  async function settled() { while (pending) await queue; }

  function reported() {
    const state = page.state(), route = page.route(), lines = new Map();
    for (const line of state.cart) {
      const offer = page.byVariant(line.key)?.variant.offerId;
      if (offer) lines.set(offer, (lines.get(offer) || 0) + line.quantity);
    }
    const basket = [...lines].sort(([a], [b]) => a < b ? -1 : a > b ? 1 : 0)
      .map(([offer_id, quantity]) => ({offer_id, quantity}));
    const result = basket.length ? page.quote() : null;
    const option = result && !result.errors.length && result.optionId ? result.optionId : null;
    const chosen = !!state.basketSelection && state.scenarioChosen === JSON.stringify(state.basketSelection);
    const atCheckout = route.role === 'checkout' && basket.length > 0;
    const step = atCheckout && page.conf.modules.checkout === 'steps'
      ? Math.max(1, Math.min(3, Math.floor(Number(route.params.get('step'))) || 1)) : null;
    return {basket, delivery: {option_id: option, source: chosen ? 'shopper' : 'site'},
      location: atCheckout ? 'checkout' : 'outside', step};
  }

  function sync() {
    const value = reported(), text = JSON.stringify(value);
    if (text === lastSync) return;
    lastSync = text;
    send('sync', value);
  }

  function resetDelivery() {
    const state = page.state();
    state.basketSelection = null;
    delete state.scenarioChosen;
    // A family may declare a silent reset (no notice; only the changed choice and total show it).
    page.revise(settings.presentation.silent_reset ? '' : 'Delivery choices were reset. Check your delivery choice again.');
  }

  const renderers = {
    cookieFirstLevel({cookie}) {
      const labels = {accept_all: 'Accept all', reject_all: 'Reject all', settings: 'Cookie settings'};
      const buttons = cookie.first_level.map(action => `<button type="button" data-consent="${action}"${cookie.emphasis ? ` data-emphasis="${cookie.emphasis === action ? 'primary' : 'quiet'}"` : ''}>${labels[action]}</button>`).join('');
      return `<h2>Cookies</h2><p>We use cookies for analytics, personalisation and marketing. Choose what you allow.</p><p class="scenario-actions">${buttons}${cookie.dismissible ? '<button type="button" data-consent="dismiss">Close</button>' : ''}</p>`;
    },
    cookieSettingsPane({toggles}) {
      return `<h2>Cookie settings</h2><fieldset><legend>Optional cookies</legend>${purposes.map(([key, label]) => `<label><input type="checkbox" data-consent-purpose="${key}" ${toggles[key] ? 'checked' : ''}> ${label}</label>`).join('')}</fieldset><p class="scenario-actions"><button type="button" data-consent="save_settings">Save settings</button><button type="button" data-consent="reject_all">Reject all</button><button type="button" data-consent="accept_all">Accept all</button><button type="button" data-consent="back">Back</button></p>`;
    },
    checkoutControls({view}) {
      const rows = settings.extras.map(extra => `<label><input type="checkbox" data-scenario-extra="${e(extra.id)}" ${view.extras[extra.id] ? 'checked' : ''}> ${e(extra.label)} — ${money(extra.price_minor)}${extra.billing_period === 'monthly' ? ' per month' : ''}</label>`);
      if (settings.newsletter) rows.push(`<label><input type="checkbox" data-scenario-newsletter ${view.newsletter ? 'checked' : ''}> ${e(settings.newsletter.label)}</label>`);
      return rows.length ? `<h3>Order options</h3>${rows.join('')}` : '';
    },
    totals({view}) {
      if (!view.quote) return `<p role="status">${e(view.quote_reason || 'The total is being calculated.')}</p>`;
      const atCheckout = view.checkout.location === 'checkout';
      const hidden = new Set(settings.fees.filter(fee => fee.reveal === 'checkout' && !atCheckout).map(fee => fee.label));
      // Lines of the quote's own breakdown are part of the quote charge, never added to it.
      const breakdown = view.quote_lines.filter(line => !hidden.has(line.label))
        .map(line => `<dt>Including ${e(line.label)}</dt><dd>${money(line.amount_minor)}</dd>`).join('');
      const charges = view.charges.map(charge => `<dt>${e(charge.label)}</dt><dd>${money(charge.amount_minor)}</dd>${charge.kind === 'quote' ? breakdown : ''}`).join('');
      return `<dl>${charges}<dt>Total</dt><dd><strong>${money(view.grand_total_minor)}</strong></dd></dl>`;
    },
    promotionForm({view}) {
      const promotions = settings.promotions, feedback = view.promotion_feedback;
      const applied = view.promotion_codes.map(code => `<li>${e(code)} <button type="button" data-scenario-remove-code="${e(code)}">Remove ${e(code)}</button></li>`).join('');
      return `<form data-scenario-form="promotion"><label>${e(promotions.label)}<input name="code" autocomplete="off"></label><button>Apply code</button></form>${feedback ? `<p role="status">${e(feedback.code)}: ${e(feedback.feedback)}</p>` : ''}${applied ? `<ul aria-label="Applied codes">${applied}</ul>` : ''}${promotions.claims.map(claim => `<p>${e(claim)}</p>`).join('')}`;
    },
  };
  const decorators = [root => {
    const label = settings.delivery.prominent_label;
    if (!label || !view) return;
    for (const input of root.querySelectorAll('input[data-service-group]')) {
      const row = input.closest('label');
      if (!row || row.querySelector('[data-scenario-badge]') || !view.prominent_option_ids.includes(input.value)) continue;
      const badge = document.createElement('strong');
      badge.dataset.scenarioBadge = ''; badge.className = 'scenario-badge'; badge.textContent = label;
      row.append(' ', badge);
    }
  }];

  const part = (name, label, body) => `<section data-scenario-part="${name}" aria-label="${label}">${body}${problem && name !== 'totals' ? `<p role="alert">${e(problem)}</p>` : ''}</section>`;
  const parts = {
    controls: () => !settings.newsletter && !settings.extras.length ? ''
      : part('controls', 'Order options', view ? renderers.checkoutControls({view, settings}) : '<p role="status">Loading order options…</p>'),
    totals: () => {
      displayedTotal = view?.quote ? view.grand_total_minor : null;
      return part('totals', 'Order total', view ? renderers.totals({view, settings}) : '<p role="status">The total is being calculated.</p>');
    },
    promotion: () => part('promotion', 'Promotion codes', view ? renderers.promotionForm({view, settings}) : ''),
  };

  function renderDialog() {
    const cookie = settings.cookie;
    let host = document.getElementById('commerce-scenario-consent');
    if (!cookie || !view?.cookie.open) { host?.remove(); pane = false; toggles = null; return; }
    if (!host) {
      host = document.createElement(cookie.blocking ? 'dialog' : 'section');
      host.id = 'commerce-scenario-consent';
      host.dataset.design = cookie.design;
      host.setAttribute('aria-label', 'Cookie choices');
      if (!cookie.blocking) host.setAttribute('role', 'dialog');
      document.body.append(host);
      if (cookie.blocking) { host.addEventListener('cancel', event => event.preventDefault()); host.showModal(); }
    }
    toggles ||= {...(view.cookie.pending || view.cookie.preferences)};
    const body = pane ? renderers.cookieSettingsPane({cookie, view, toggles}) : renderers.cookieFirstLevel({cookie, view, toggles});
    host.innerHTML = body + (problem ? `<p role="alert">${e(problem)}</p>` : '');
  }

  // Replace only the scenario's own blocks, so a host reply never disturbs a form being filled in.
  function refresh() {
    for (const node of document.querySelectorAll('[data-scenario-part]')) {
      // A family may update a block in place (e.g. flip a checkbox) instead of replacing it.
      if (view && renderers.patch?.[node.dataset.scenarioPart]?.(node, {view, settings})) continue;
      const body = parts[node.dataset.scenarioPart]?.();
      if (body) node.outerHTML = body;
    }
    decorate(document);
    renderDialog();
  }
  function decorate(root) { for (const decorator of decorators) decorator(root, {view, settings}); }

  document.addEventListener('click', event => {
    const target = event.target.closest('[data-consent],[data-scenario-remove-code]');
    if (!target) return;
    if (target.dataset.scenarioRemoveCode) { send('promotion_remove', {code: target.dataset.scenarioRemoveCode}); return; }
    const action = target.dataset.consent;
    if (action === 'settings' || action === 'back') { pane = action === 'settings'; renderDialog(); }
    else if (action === 'dismiss') send('cookie_dialog', {event: 'dismiss'});
    else if (action === 'save_settings') send('cookie_save', {action, preferences: {...toggles}});
    else send('cookie_save', {action});
  });
  document.addEventListener('change', event => {
    const input = event.target;
    if (input.dataset?.consentPurpose) toggles[input.dataset.consentPurpose] = input.checked;
    else if (input.dataset?.scenarioExtra) send('extras_set', {extra_id: input.dataset.scenarioExtra, value: input.checked});
    else if ('scenarioNewsletter' in (input.dataset || {})) send('newsletter_set', {value: input.checked});
  });
  document.addEventListener('submit', event => {
    if (event.target.dataset?.scenarioForm !== 'promotion') return;
    event.preventDefault();
    const code = String(new FormData(event.target).get('code') || '').trim();
    if (code) send('promotion_apply', {code});
  });

  const link = document.createElement('link');
  link.rel = 'stylesheet';
  document.head.append(link);
  link.href = 'commerce-scenario.css';
  const api = {settings, presentation: settings.presentation, view: () => view, send, refresh,
    renderers, decorators, escape: e, money, page};
  const pieces = settings.pieces.map(name => {
    if (name.endsWith('.css')) {
      const sheet = document.createElement('link');
      sheet.rel = 'stylesheet'; sheet.href = name;
      document.head.append(sheet);
      return null;
    }
    return import('./' + name).then(piece => piece.attach(api));
  });
  const first = send(settings.cookie ? 'cookie_dialog' : 'state', settings.cookie ? {event: 'load'} : {});

  return {
    promotionField: settings.promotions.field,
    ready: Promise.all([first, ...pieces]).catch(failure => { problem = failure.message; }).then(refresh),
    sync,
    chose(state) { state.scenarioChosen = JSON.stringify(state.basketSelection); },
    checkoutControls: () => parts.controls(),
    totals: () => parts.totals(),
    promotionForm: () => parts.promotion(),
    decorate,
    // The order is armed with exactly the total last rendered; the host refuses a different one.
    async armOrder() {
      sync();
      await settled();
      if (displayedTotal === null) { page.notify(view?.quote_reason || problem || 'The order total is not available yet.'); return false; }
      const reply = await send('order_arm', {grand_total_minor: displayedTotal});
      if (reply?.order?.armed) return true;
      page.notify(reply?.order?.reason || problem || 'The order could not be confirmed.');
      return false;
    },
  };
}
