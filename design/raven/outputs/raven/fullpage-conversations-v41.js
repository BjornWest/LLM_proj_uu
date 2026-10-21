/* Separate full-page demo: local conversation history, raw Markdown and captured sources. */
(() => {
  'use strict';
  const STORAGE_KEY = 'raven-fullpage-conversations-v41';
  const MAX_THREADS = 30, MAX_MESSAGES = 120, MAX_TEXT = 30000;
  const plain = value => value && typeof value === 'object' && !Array.isArray(value);
  const text = (value, length = 300) => typeof value === 'string' ? value.slice(0, length) : '';
  const safeUrl = value => {
    if (typeof value !== 'string' || value.length > 2048 || /[\u0000-\u0020\u007f\\]/.test(value)) return '';
    try {
      const url = new URL(value);
      return /^https?:$/.test(url.protocol) && !url.username && !url.password ? url.href : '';
    } catch { return ''; }
  };
  const pairs = (values, keys) => Array.isArray(values) ? values.slice(0, 12).filter(plain).map(value => {
    const result = {};
    for (const key of keys) result[key] = text(value[key], key === 'value' ? 600 : 120);
    return result;
  }) : [];
  function sourcesFrom(values) {
    if (!Array.isArray(values)) return [];
    const result = [], seen = new Set();
    for (const value of values.slice(0, 32)) {
      if (!plain(value) || typeof value.id !== 'string' || !/^[A-Za-z0-9][\w:.-]{0,79}$/.test(value.id) || seen.has(value.id)) continue;
      seen.add(value.id);
      const source = {
        id: value.id, kind: text(value.kind, 40), siteName: text(value.siteName, 100), title: text(value.title, 220),
        context: text(value.context, 400), url: safeUrl(value.url), favicon: safeUrl(value.favicon),
        metric: { value: text(value.metric?.value, 120), label: text(value.metric?.label, 100) },
        facts: pairs(value.facts, ['label', 'value']), inputs: pairs(value.inputs, ['sourceId', 'label', 'value']),
        evidence: text(value.evidence, 12000), checkedAt: text(value.checkedAt, 80), checkedLabel: text(value.checkedLabel, 150),
        illustrative: value.illustrative === true
      };
      if (plain(value.history) && Array.isArray(value.history.points)) {
        const points = value.history.points.slice(0, 365);
        if (points.length > 1 && points.every(point => typeof point === 'number' && Number.isFinite(point))) {
          source.history = { points, startLabel: text(value.history.startLabel, 100), endLabel: text(value.history.endLabel, 100), unit: text(value.history.unit, 20) };
        }
      }
      result.push(source);
    }
    return result;
  }
  function messageFrom(value) {
    if (!plain(value) || typeof value.text !== 'string' || !['You', 'Raven'].includes(value.who)) return null;
    return { text: text(value.text, MAX_TEXT), who: value.who, sources: sourcesFrom(value.sources) };
  }
  function threadFrom(value) {
    if (!plain(value) || typeof value.id !== 'string' || !/^[A-Za-z0-9_-]{1,80}$/.test(value.id) || !Array.isArray(value.messages)) return null;
    const now = Date.now();
    return {
      id: value.id, title: text(value.title, 80).trim() || 'New conversation', draft: text(value.draft, 8000),
      createdAt: Number.isFinite(value.createdAt) ? value.createdAt : now,
      updatedAt: Number.isFinite(value.updatedAt) ? value.updatedAt : now,
      messages: value.messages.slice(-MAX_MESSAGES).map(messageFrom).filter(Boolean)
    };
  }
  function initialize() {
    const controller = window.ravenChatDemo;
    const list = document.getElementById('conversation-list'), input = document.getElementById('message-input');
    if (!controller || !list || !input || typeof controller.setConversation !== 'function') return;
    const search = document.getElementById('conversation-search'), title = document.getElementById('conversation-title');
    const welcome = document.getElementById('welcome-view'), notice = document.getElementById('conversation-notice');
    const sidebar = document.getElementById('conversation-sidebar');
    const sidebarToggle = document.getElementById('sidebar-toggle'), backdrop = document.getElementById('sidebar-backdrop');
    const stop = document.getElementById('stop-task'), mobile = matchMedia('(max-width: 760px)');
    const scene = document.getElementById('chat-scene');
    let threads = [], activeId = '', restoring = false, persistTimer = null, storageProblem = false;
    const active = () => threads.find(thread => thread.id === activeId);
    const setNotice = () => {
      if (!notice) return;
      notice.textContent = storageProblem ? 'Browser storage is unavailable or full. This session remains usable, but recent changes may not survive a reload.' : 'Conversations · saved in this browser';
      notice.dataset.storage = storageProblem ? 'unavailable' : 'local';
    };
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved && saved.length <= 2000000) {
        const data = JSON.parse(saved);
        if (plain(data) && data.version === 1 && Array.isArray(data.threads)) {
          const seen = new Set();
          threads = data.threads.slice(0, MAX_THREADS).map(threadFrom).filter(thread => {
            if (!thread || seen.has(thread.id)) return false;
            seen.add(thread.id); return true;
          });
          if (threads.some(thread => thread.id === data.activeId)) activeId = data.activeId;
        }
      }
    } catch { storageProblem = true; }
    if (!threads.length) threads = [{id:crypto.randomUUID(),title:'New conversation',draft:'',createdAt:Date.now(),updatedAt:Date.now(),messages:[]}];
    activeId ||= threads[0].id;
    function persist() {
      clearTimeout(persistTimer); persistTimer = null;
      try {
        const serialized = JSON.stringify({ version: 1, activeId, threads });
        if (serialized.length > 2000000) throw new Error('Conversation history exceeds the demo storage limit.');
        localStorage.setItem(STORAGE_KEY, serialized);
        storageProblem = false;
      } catch { storageProblem = true; }
      setNotice();
    }
    function schedulePersist() {
      clearTimeout(persistTimer); persistTimer = setTimeout(persist, 300);
    }
    function autoHeight() {
      input.style.height = 'auto';
      input.style.height = Math.min(150, Math.max(28, input.scrollHeight)) + 'px';
      input.style.overflowY = input.scrollHeight > 150 ? 'auto' : 'hidden';
    }
    function updateView() {
      const thread = active();
      if (title) title.textContent = thread?.title || 'New conversation';
      const empty = !thread?.messages.length;
      if (welcome) welcome.hidden = !empty;
      document.body.classList.toggle('conversation-empty', empty);
      if (scene) scene.dataset.conversationEmpty = String(empty);
    }
    function renderList() {
      const query = (search?.value || '').trim().toLocaleLowerCase();
      const fragment = document.createDocumentFragment();
      let count = 0;
      for (const thread of [...threads].sort((a, b) => b.updatedAt - a.updatedAt)) {
        const matches = !query || thread.title.toLocaleLowerCase().includes(query) || thread.messages.some(message => message.text.toLocaleLowerCase().includes(query));
        if (!matches) continue;
        count++;
        const button = document.createElement('button');
        button.type = 'button'; button.className = 'conversation-item'; button.dataset.conversationId = thread.id;
        button.setAttribute('aria-label', thread.title);
        if (thread.id === activeId) { button.classList.add('active'); button.setAttribute('aria-current', 'page'); }
        const name = document.createElement('span'), meta = document.createElement('span');
        name.className = 'conversation-name'; name.textContent = thread.title;
        meta.className = 'conversation-meta';
        meta.textContent = thread.messages.length ? `${thread.messages.length} messages` : thread.draft ? 'Draft' : 'No messages yet';
        button.append(name, meta); fragment.append(button);
      }
      if (!count) {
        const empty = document.createElement('p'); empty.className = 'conversation-list-empty'; empty.textContent = 'No conversations found.'; fragment.append(empty);
      }
      list.replaceChildren(fragment);
    }
    function setDrawer(open, restoreFocus = false) {
      const isOpen = !!open && mobile.matches;
      document.body.classList.toggle('sidebar-open', isOpen);
      if (sidebar) sidebar.inert = mobile.matches && !isOpen;
      sidebarToggle?.setAttribute('aria-expanded', String(isOpen));
      if (backdrop) backdrop.hidden = !isOpen;
      if (isOpen) search?.focus({ preventScroll: true });
      else if (restoreFocus) sidebarToggle?.focus({ preventScroll: true });
    }
    function saveDraft() {
      const thread = active();
      if (thread) thread.draft = text(input.value, 8000);
    }
    function selectConversation(id, { focusInput = false } = {}) {
      if (!threads.some(thread => thread.id === id)) return;
      if (id === activeId) { setDrawer(false, mobile.matches); return; }
      saveDraft(); activeId = id;
      const thread = active();
      restoring = true;
      try { controller.setConversation(thread.messages, { title: thread.title }); }
      finally { restoring = false; }
      input.value = thread.draft || '';
      autoHeight(); updateView(); renderList(); persist();
      setDrawer(false, mobile.matches && !focusInput);
      if (focusInput) input.focus({ preventScroll: true });
    }
    // Explicit local-store adapter: requests take a snapshot before appending the new turn.
    window.RavenConversations={getContext:()=>({conversation_id:activeId,history:active().messages.map(({who,text})=>({who,text}))})};
    // During replay setConversation can safely call the wrapped renderer without duplicating saved messages.
    const append = controller.appendMessage;
    controller.appendMessage = function (raw, who, options = {}) {
      const element = append.call(this, raw, who, options);
      if (!restoring) {
        const thread = active(), message = messageFrom({ text: raw, who, sources: options.sources || [] });
        if (thread && message) {
          thread.messages.push(message); thread.messages = thread.messages.slice(-MAX_MESSAGES); thread.updatedAt = Date.now();
          if (who === 'You') {
            thread.draft = '';
            if (thread.title === 'New conversation') thread.title = raw.trim().replace(/\s+/g, ' ').slice(0, 58) || 'New conversation';
          }
          updateView(); renderList(); persist();
        }
      }
      return element;
    };
    document.getElementById('new-conversation')?.addEventListener('click', () => {
      saveDraft();
      const now = Date.now(), id = typeof crypto?.randomUUID === 'function' ? crypto.randomUUID() : `thread-${now}-${Math.random().toString(36).slice(2, 10)}`;
      threads.push({ id, title: 'New conversation', createdAt: now, updatedAt: now, messages: [], draft: '' });
      if (threads.length > MAX_THREADS) threads = threads.sort((a, b) => b.updatedAt - a.updatedAt).slice(0, MAX_THREADS);
      selectConversation(id, { focusInput: true });
    });
    const header = document.querySelector('.app-header');
    if (window.ravenModels && header) {
      const slot = document.createElement('div'); slot.className = 'header-model';
      header.insertBefore(slot, header.querySelector('.raven-settings'));
      window.ravenModels.mount(slot, { hasConversation: () => (active()?.messages.length || 0) > 0, currentConversation: () => activeId,
        newConversation: () => document.getElementById('new-conversation')?.click() });
      window.ravenMemory?.button(slot);
    }
    list.addEventListener('click', event => {
      const button = event.target.closest('button[data-conversation-id]');
      if (button && list.contains(button)) selectConversation(button.dataset.conversationId);
    });
    search?.addEventListener('input', renderList);
    input.addEventListener('input', () => { autoHeight(); saveDraft(); schedulePersist(); });
    input.addEventListener('keydown', event => {
      if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
        event.preventDefault(); document.getElementById('chat-form')?.requestSubmit();
      }
    });
    document.querySelectorAll('[data-starter-prompt]').forEach(button => button.addEventListener('click', () => {
      input.value = text(button.dataset.starterPrompt, 8000); input.dispatchEvent(new Event('input', { bubbles: true })); input.focus({ preventScroll: true });
    }));
    sidebarToggle?.addEventListener('click', () => setDrawer(!document.body.classList.contains('sidebar-open')));
    backdrop?.addEventListener('click', () => setDrawer(false, true));
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && document.body.classList.contains('sidebar-open')) { event.preventDefault(); setDrawer(false, true); }
      else if (event.key === 'Tab' && sidebar && document.body.classList.contains('sidebar-open')) {
        const controls = [...sidebar.querySelectorAll('button:not(:disabled),a[href],input:not(:disabled),textarea:not(:disabled),select:not(:disabled)')].filter(element => element.getClientRects().length && !element.closest('[hidden]'));
        if (!controls.length) return;
        const first = controls[0], last = controls[controls.length - 1], focused = document.activeElement;
        if (!sidebar.contains(focused) || (event.shiftKey && focused === first) || (!event.shiftKey && focused === last)) {
          event.preventDefault(); (event.shiftKey ? last : first).focus({ preventScroll: true });
        }
      }
    });
    mobile.addEventListener?.('change', () => setDrawer(false));
    stop?.addEventListener('click', () => controller.cancelTask?.());
    if (stop) stop.hidden = true;
    scene?.addEventListener('raven-chat-submit', () => { if (stop) stop.hidden = false; saveDraft(); autoHeight(); persist(); });
    for (const eventName of ['raven-chat-reply', 'raven-conversation-change', 'raven-chat-cancel']) {
      scene?.addEventListener(eventName, () => { if (stop) stop.hidden = true; });
    }
    window.addEventListener('pagehide', () => { saveDraft(); persist(); });
    // Initial selection uses the same cancellation and rendering path as every sidebar switch.
    restoring = true;
    try { controller.setConversation(active().messages, { title: active().title }); }
    finally { restoring = false; }
    input.value = active().draft || '';
    setDrawer(false); autoHeight(); updateView(); renderList(); persist();
  }
  if (!window.ravenChatDemo && document.readyState !== 'complete') window.addEventListener('DOMContentLoaded', initialize, { once: true });
  else initialize();
})();
