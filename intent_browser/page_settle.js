// Harness-side page readiness and public-change revision (no site cooperation).
// Readiness: no in-flight fetch/XHR started by this document, no counted DOM
// change for a quiet period, then two animation frames. Revision: a counter of
// DOM/form changes that excludes attributes written by BrowserGym marking, so a
// capture can tell whether the page changed since an earlier AX snapshot.
// Not a completeness proof: shadow roots, canvas and timers are not observed.
(() => {
  if (globalThis.__intentPageSettle) return;
  const HARNESS_ATTRIBUTES = new Set(['bid', 'browsergym_visibility_ratio', 'browsergym_set_of_marks',
    'aria-roledescription', 'aria-description', 'value', 'checked']);
  let revision = 0, pending = 0, lastChange = performance.now(), marking = 0;
  const documentId = Array.from(crypto.getRandomValues(new Uint32Array(4)), x => x.toString(16)).join('-');
  const touch = () => { revision++; lastChange = performance.now(); };
  const observer = new MutationObserver(records => {
    for (const record of records) {
      // Marking temporarily writes value/checked to mirror live properties;
      // those writes are excluded only while the harness marks the page.
      if (record.type === 'attributes' && HARNESS_ATTRIBUTES.has(record.attributeName) &&
          (marking > 0 || !['value', 'checked'].includes(record.attributeName))) continue;
      touch(); return;
    }
  });
  observer.observe(document, {subtree: true, childList: true, attributes: true, characterData: true});
  for (const event of ['input', 'change', 'reset', 'toggle', 'hashchange', 'popstate'])
    addEventListener(event, touch, true);
  const setter = (proto, key) => {
    const d = Object.getOwnPropertyDescriptor(proto, key);
    if (!d?.set || !d.configurable) return;
    Object.defineProperty(proto, key, {...d, set(value) { d.set.call(this, value); touch(); }});
  };
  for (const [proto, keys] of [
    [HTMLInputElement.prototype, ['value', 'checked']],
    [HTMLTextAreaElement.prototype, ['value']],
    [HTMLSelectElement.prototype, ['value', 'selectedIndex']],
    [HTMLOptionElement.prototype, ['selected']],
  ]) for (const key of keys) setter(proto, key);
  const originalFetch = globalThis.fetch;
  if (typeof originalFetch === 'function') {
    globalThis.fetch = function (...args) {
      pending++; touch();
      let result;
      try { result = originalFetch.apply(this, args); }
      catch (error) { pending--; touch(); throw error; }
      // Observe settlement without replacing the site's returned Promise.
      result.then(() => { pending--; touch(); }, () => { pending--; touch(); });
      return result;
    };
  }
  const send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function (...args) {
    let settled = false;
    const done = () => { if (!settled) { settled = true; pending--; touch(); } };
    pending++; touch();
    this.addEventListener('loadend', done, {once: true});
    try { return send.apply(this, args); }
    catch (error) { this.removeEventListener('loadend', done); done(); throw error; }
  };
  // Two animation frames, but never past the caller's remaining deadline:
  // a suspended document or stalled scheduler yields 'frame_timeout'.
  const frames = remainingMs => new Promise(resolve => {
    let finished = false;
    const timer = setTimeout(() => { if (!finished) { finished = true; resolve(false); } }, Math.max(0, remainingMs));
    requestAnimationFrame(() => requestAnimationFrame(() => {
      if (!finished) { finished = true; clearTimeout(timer); resolve(true); }
    }));
  });
  globalThis.__intentPageSettle = Object.freeze({
    version: 'page-settle-v2',
    state: () => ({documentId, revision, pending}),
    beginMarking: () => { marking++; return revision; },
    endMarking: () => { marking = Math.max(0, marking - 1); return revision; },
    async wait(quietMs, timeoutMs) {
      const started = performance.now();
      const result = status => ({status, waited_ms: performance.now() - started, revision, pending, documentId});
      while (true) {
        const now = performance.now();
        const remaining = timeoutMs - (now - started);
        if (remaining <= 0) return result(pending ? 'pending' : 'busy');
        if (pending === 0 && now - lastChange >= quietMs) {
          const before = revision;
          if (!await frames(remaining)) return result('frame_timeout');
          if (revision === before && pending === 0) return result('ready');
          continue;
        }
        await new Promise(resolve => setTimeout(resolve, Math.max(0, Math.min(quietMs, 10, remaining))));
      }
    },
  });
})();
