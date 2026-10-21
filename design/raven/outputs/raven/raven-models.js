/* Model picker shared by the full-page chat and the side panel. The model is fixed per conversation. */
(() => {
  'use strict';
  const PREF = 'raven.model', MAP = 'raven.conversationModels';
  const read = (key, fallback) => { try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; } };
  const write = (key, value) => { try { localStorage.setItem(key, JSON.stringify(value)); } catch {} };
  const style = document.createElement('style');
  style.textContent = '.raven-model{display:inline-flex;align-items:center;gap:6px;font:12px system-ui;color:#586a7b;flex-wrap:wrap}'
    + '.raven-model select{font:inherit;border:1px solid #d9e1e9;border-radius:6px;padding:3px 6px;background:white;color:#24323f;max-width:220px}'
    + '.raven-model .dot{width:8px;height:8px;border-radius:50%;background:#b8c2cc;flex:none}.raven-model .dot.on{background:#2fa35a}'
    + '.raven-model-note{font:11px system-ui;color:#7a5b12}.raven-model-note button{font:inherit;margin-left:6px;cursor:pointer;border:1px solid #d9c27a;background:#fff8e0;border-radius:6px;padding:2px 6px}'
    + '.raven-model-note[hidden]{display:none}.raven-model-label{display:block;margin-top:6px;font:11px system-ui;opacity:.7}';
  document.head.append(style);

  class RavenModels {
    constructor() { this.presets = []; this.serverDefault = null; this.listeners = []; this.ready = this.refresh(); setInterval(() => this.refresh(), 15000); }
    async refresh() {
      try {
        const data = await (await fetch('/api/models')).json();
        this.presets = data.presets || []; this.serverDefault = data.default;
      } catch { /* Keep the last known list; the backend still picks a default. */ }
      this.listeners.forEach(fn => fn());
    }
    label(id) { return this.presets.find(p => p.id === id)?.label || id || ''; }
    preferred() { const id = read(PREF, null); return this.presets.some(p => p.id === id) ? id : this.serverDefault; }
    /* Model for a conversation: recorded at its first message, never switched afterwards. */
    modelFor(conversationId) {
      const map = read(MAP, {});
      if (conversationId && map[conversationId]) return map[conversationId];
      const id = this.preferred();
      if (conversationId && id) { map[conversationId] = id; write(MAP, map); }
      return id;
    }
    record(conversationId, id) { if (!conversationId || !id) return; const map = read(MAP, {}); map[conversationId] = id; write(MAP, map); }
    /* container: element to fill; hasConversation(): true when the open conversation already has messages. */
    mount(container, {hasConversation, currentConversation, newConversation}) {
      const wrap = document.createElement('span'); wrap.className = 'raven-model';
      const dot = document.createElement('span'); dot.className = 'dot'; dot.setAttribute('aria-hidden', 'true');
      const select = document.createElement('select'); select.setAttribute('aria-label', 'Model for new conversations');
      const note = document.createElement('span'); note.className = 'raven-model-note'; note.hidden = true;
      const noteText = document.createElement('span'), button = document.createElement('button');
      button.type = 'button'; note.append(noteText, button); wrap.append(dot, select, note); container.append(wrap);
      const render = () => {
        const chosen = select.value || this.preferred();
        select.replaceChildren(...this.presets.map(p => {
          const o = document.createElement('option'); o.value = p.id; o.textContent = (p.available ? '● ' : '○ ') + p.label + (p.available ? '' : ' (offline)'); return o;
        }));
        if (chosen) select.value = chosen;
        const active = currentConversation?.() ? read(MAP, {})[currentConversation()] : null;
        dot.classList.toggle('on', !!this.presets.find(p => p.id === select.value)?.available);
        wrap.title = active && hasConversation?.() ? 'This conversation uses ' + this.label(active) : '';
      };
      select.onchange = () => {
        write(PREF, select.value);
        fetch('/api/model', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({id: select.value})}).catch(() => {});
        const conversation = currentConversation?.(), active = conversation && read(MAP, {})[conversation];
        if (conversation && !hasConversation?.()) { const map = read(MAP, {}); delete map[conversation]; write(MAP, map); }
        if (hasConversation?.() && active && active !== select.value) {
          noteText.textContent = 'Applies to your next conversation.';
          button.textContent = 'New conversation with ' + this.label(select.value);
          note.hidden = false;
        } else note.hidden = true;
        render();
      };
      button.onclick = () => { note.hidden = true; newConversation?.(select.value); };
      this.listeners.push(render); render();
      return {hideNote: () => { note.hidden = true; }, render};
    }
  }
  window.ravenModels = new RavenModels();
})();
