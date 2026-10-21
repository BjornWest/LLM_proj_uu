/* Raven user memory: a small dialog shared by the full-page chat and the side panel. */
(() => {
  'use strict';
  const LABELS = {name: 'Name', shoe_size_eu: 'Shoe size (EU)', clothing_size: 'Clothing size', preferred_colours: 'Preferred colours',
    delivery_address_city: 'Delivery city', budget_note: 'Budget', preferred_stores: 'Preferred stores', avoid_sites: 'Sites to avoid',
    dietary_preferences: 'Diet', newsletter_opt_in: 'Newsletter sign-ups', notes: 'Notes'};
  const label = key => LABELS[key] || String(key).replace(/_/g, ' ');
  const style = document.createElement('style');
  style.textContent = '.raven-memory-button{font:12px system-ui;border:1px solid #d9e1e9;background:white;border-radius:6px;padding:4px 9px;cursor:pointer;color:#24323f}'
    + 'dialog.raven-memory{border:1px solid #d9e1e9;border-radius:12px;padding:0;width:min(560px,94vw);max-height:86vh;font:14px/1.45 system-ui;color:#1d2a36;box-shadow:0 12px 40px #20304a33}'
    + 'dialog.raven-memory::backdrop{background:#1d2a3633}.raven-memory header{display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border-bottom:1px solid #e8edf2}'
    + '.raven-memory h2{font-size:16px;margin:0}.raven-memory .rows{padding:6px 16px 14px;overflow:auto;max-height:66vh}.raven-memory .row{display:grid;grid-template-columns:minmax(110px,34%) 1fr auto auto;gap:6px;align-items:center;padding:5px 0;border-bottom:1px solid #f1f4f7}'
    + '.raven-memory .row.empty .name{color:#8a97a4}.raven-memory input,.raven-memory select{font:inherit;border:1px solid #d9e1e9;border-radius:6px;padding:4px 7px;min-width:0}'
    + '.raven-memory button{font:inherit;font-size:12.5px;border:1px solid #d9e1e9;background:#f7f9fb;border-radius:6px;padding:4px 8px;cursor:pointer}.raven-memory .note{padding:0 16px 12px;font-size:12px;color:#6b7a88}'
    + '@media (max-width:560px){.raven-memory .row{grid-template-columns:1fr auto auto;row-gap:3px}.raven-memory .row .name{grid-column:1/-1;font-size:12.5px}}'
    + '.raven-memory .row.saved{background:#eaf7ee}.raven-memory-updated{display:block;margin-top:6px;font:12px system-ui;opacity:.85}';
  document.head.append(style);

  async function call(method, key, value) {
    const response = await fetch('/api/memory' + (key ? '/' + encodeURIComponent(key) : ''), {method,
      headers: {'Content-Type': 'application/json'}, body: method === 'PUT' ? JSON.stringify({value}) : undefined});
    const data = await response.json();
    if (!response.ok) throw new Error(data.problem || 'Could not save that.');
    return data;
  }

  class RavenMemory {
    constructor() {
      this.dialog = document.createElement('dialog'); this.dialog.className = 'raven-memory';
      this.dialog.innerHTML = '<header><h2>What Raven remembers about you</h2><button type="button" data-close>Close</button></header><div class="rows"></div><p class="note" role="status">Raven reads this before each task and saves lasting preferences you mention.</p>';
      document.body.append(this.dialog);
      this.dialog.querySelector('[data-close]').onclick = () => this.dialog.close();
      this.rows = this.dialog.querySelector('.rows'); this.note = this.dialog.querySelector('.note');
      document.addEventListener('raven-memory-changed', () => this.dialog.open && this.refresh());
      setInterval(() => { if (this.dialog.open && !this.dialog.contains(document.activeElement?.closest?.('input,select'))) this.refresh(); }, 4000);
    }
    button(container) {
      const button = document.createElement('button'); button.type = 'button'; button.className = 'raven-memory-button';
      button.textContent = 'Memory'; button.title = 'What Raven remembers about you';
      button.onclick = () => { this.dialog.showModal(); this.refresh(); };
      container.append(button); return button;
    }
    async refresh() {
      let data;
      try { data = await call('GET'); } catch { this.note.textContent = 'Memory is unavailable right now.'; return; }
      const rows = Object.entries(data.fields).map(([key, schema]) => {
        const row = document.createElement('div'), has = key in data.values; row.className = 'row' + (has ? '' : ' empty');
        const name = document.createElement('span'); name.className = 'name'; name.textContent = label(key);
        let input;
        if (schema.enum) { input = document.createElement('select'); input.append(...['', ...schema.enum].map(v => { const o = document.createElement('option'); o.value = v; o.textContent = v || '—'; return o; })); }
        else { input = document.createElement('input'); input.type = schema.type === 'number' ? 'number' : 'text'; input.placeholder = schema.description || ''; }
        input.value = has ? String(data.values[key]) : ''; input.setAttribute('aria-label', label(key));
        const save = document.createElement('button'); save.type = 'button'; save.textContent = 'Save';
        const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = 'Delete'; remove.disabled = !has;
        save.onclick = async () => {
          if (input.value === '') return remove.click();
          try { await call('PUT', key, schema.type === 'number' ? Number(input.value) : input.value); row.classList.add('saved'); this.note.textContent = 'Saved ' + label(key) + '.'; setTimeout(() => this.refresh(), 600); }
          catch (e) { this.note.textContent = label(key) + ': ' + e.message; }
        };
        input.onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); save.click(); } };
        remove.onclick = async () => { try { await call('DELETE', key); this.note.textContent = 'Deleted ' + label(key) + '.'; this.refresh(); } catch (e) { this.note.textContent = e.message; } };
        row.append(name, input, save, remove); return row;
      });
      this.rows.replaceChildren(...rows.sort((a, b) => a.classList.contains('empty') - b.classList.contains('empty')));
    }
  }
  window.RavenMemoryLabel = label;
  window.addEventListener('DOMContentLoaded', () => { window.ravenMemory = new RavenMemory(); });
})();
