'use strict';
(() => {
  const panel = document.getElementById('consent-ui');
  if (!panel) return;
  const prefs = document.getElementById('consent-preferences');
  const manage = document.getElementById('consent-manage');
  const cancel = document.getElementById('consent-cancel');
  const error = document.getElementById('consent-error');
  const modal = panel.tagName === 'DIALOG';
  let decided = panel.dataset.decided === 'true';
  let pending = false;
  let restoreFocus = null;
  let committed = Object.fromEntries([...panel.querySelectorAll('input')].map(el => [el.name, el.checked]));
  const controls = [...panel.querySelectorAll('button,input')];
  function expand() {
    prefs.hidden = false;
    manage.setAttribute('aria-expanded', 'true');
  }
  function open(settings) {
    restoreFocus = document.activeElement;
    panel.hidden = false;
    error.textContent = '';
    prefs.hidden = !settings;
    manage.setAttribute('aria-expanded', String(settings));
    cancel.hidden = !decided;
    for (const el of panel.querySelectorAll('input')) el.checked = committed[el.name];
    if (modal && !panel.open) panel.showModal();
    // Banner remains nonmodal: the underlying page stays available to AX.
    if (settings) manage.focus();
  }
  function close() {
    if (modal) panel.close();
    panel.hidden = true;
    if (restoreFocus && restoreFocus.isConnected) restoreFocus.focus();
  }
  document.getElementById('cookie-settings').addEventListener('click', () => open(true));
  manage.addEventListener('click', expand);
  document.getElementById('consent-details-link').addEventListener('click', ev => {
    ev.preventDefault(); const details = document.getElementById('consent-details');
    details.open = true; details.querySelector('summary').focus();
  });
  cancel.addEventListener('click', () => { if (!pending && decided) close(); });
  panel.addEventListener('cancel', ev => {
    ev.preventDefault();
    if (!pending && decided) close(); // Escape never silently grants consent.
  });
  panel.addEventListener('click', async ev => {
    const button = ev.target.closest('[data-consent-action]');
    if (!button || pending) return;
    pending = true; controls.forEach(el => { el.disabled = true; }); error.textContent = '';
    const preferences = Object.fromEntries([...panel.querySelectorAll('input')].map(el => [el.name, el.checked]));
    try {
      const response = await fetch('/_consent/choose', {
        method: 'POST', credentials: 'same-origin', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({csrf: panel.dataset.csrf, revision: Number(panel.dataset.revision), action: button.dataset.consentAction, preferences})
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Could not save cookie preferences.');
      panel.dataset.revision = String(result.revision);
      committed = result.preferences; decided = true; panel.dataset.decided = 'true';
      close();
    } catch (err) {
      error.textContent = err.message || 'Could not save cookie preferences. Please try again.';
    } finally {
      pending = false; controls.forEach(el => { el.disabled = false; });
    }
  });
  if (!decided) open(false);
})();
