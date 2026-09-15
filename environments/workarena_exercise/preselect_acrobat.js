// Proposed session-only native-form variant. Must be browser-validated before use.
// No UI text, style or label replacement; native g_form manages the selected value.
(() => {
  if (window.top === window) return;
  if (window.__workarenaAcrobatPreselection) return;
  const state = window.__workarenaAcrobatPreselection = {
    version: 'acrobat-preselection-v4', inserted: false, stopped: false,
    startedAt: Date.now(), field: null, before: null, after: null, reason: null
  };
  let timer;
  function stop(reason) { state.stopped = true; state.reason = reason; clearInterval(timer); }
  function applyOnce() {
    if (state.stopped || state.inserted) return;
    if (Date.now() - state.startedAt > 30000) { stop('form-not-confirmed'); return; }
    // ServiceNow may initialize gsft_main as about:blank on a full reload.
    // Match only after navigation/native form loading, as upstream init helpers do.
    if (window.frameElement?.id !== 'gsft_main' ||
        !location.pathname.includes('servicecatalog_cat_item_view.do') ||
        window.WORKARENA_LOAD_COMPLETE !== true) return;
    const form = window.g_form;
    if (!form || !form.getEditableFields || !form.getControl || !form.setValue) return;
    // Require the intended native product heading, not just a field on any form.
    const title = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6,[role="heading"]')].some(x => x.textContent.trim() === 'Standard Laptop');
    if (!title) return;
    const matching = form.getEditableFields().filter(field => {
      let el = form.getControl(field);
      if (!el || el.type !== 'hidden') return false;
      for (let depth = 0; el && depth < 5; depth++, el = el.parentElement) {
        if (el.innerText && el.innerText.trim()) return el.innerText.trim() === 'Adobe Acrobat';
      }
      return false;
    });
    if (matching.length !== 1) return;
    const field = matching[0];
    const value = String(form.getValue(field)).toLowerCase();
    if (value !== 'false') { stop('unexpected-initial-value'); return; }
    // Stop before setting the value so synchronous callbacks cannot reapply it.
    stop('applying');
    state.field = field; state.before = value;
    form.setValue(field, 'true');
    state.after = String(form.getValue(field)).toLowerCase();
    state.inserted = state.after === 'true';
    state.reason = state.inserted ? 'inserted-once' : 'native-state-not-confirmed';
    state.insertedAt = Date.now();
  }
  timer = setInterval(applyOnce, 100);
  // Native bootstrap can emit pagehide while retaining this window for the
  // product document. Do not cancel initialization on that intermediate event.
  // A destroyed document loses its timers; retained contexts are bounded above.

  applyOnce();
})();
