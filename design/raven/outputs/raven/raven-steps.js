/* Human-readable activity shared by the full-page chat and extension panel. */
(() => {
  const style = document.createElement('style');
  style.textContent = '.raven-working{position:relative;z-index:3;margin:4px 14px 8px;color:#586a7b;font:12px/1.5 system-ui;overflow-wrap:anywhere}.raven-working[hidden]{display:none}.raven-steps{position:relative;z-index:3;margin-top:10px;font:12px/1.5 system-ui;color:inherit;opacity:.85}.raven-steps summary{cursor:pointer}.raven-steps ol{padding-left:20px;max-height:180px;overflow:auto}';
  document.head.append(style);
  window.RavenSteps = class {
    constructor(scene) {
      this.line = document.createElement('div');
      this.line.className = 'raven-working';
      this.line.setAttribute('role', 'status');
      this.line.setAttribute('aria-live', 'polite');
      scene.querySelector('.sky').after(this.line);
      this.line.hidden = true;
      this.steps = []; this.memory = []; this.model = null;
    }
    reset() { this.steps = []; this.model = null; this.memory = []; this.line.hidden = false; this.line.textContent = 'Working: starting research…'; }
    event(event) {
      let text;
      if (event.type === 'model') { this.model = event.notice || event.label; if (window.ravenModels && event.conversation_id) window.ravenModels.record(event.conversation_id, event.id); }
      if (event.type === 'activity') { this.line.hidden = false; this.line.textContent = 'Working: ' + event.summary; return; }
      if (event.type === 'memory') {
        const name = (window.RavenMemoryLabel || (k => k))(event.key);
        text = event.action === 'deleted' ? 'Memory updated: forgot ' + name : 'Memory updated: ' + name + ' → ' + event.value;
        this.memory.push(text); document.dispatchEvent(new CustomEvent('raven-memory-changed'));
      }
      if (event.type === 'step') text = event.summary;
      if (event.type === 'site') {
        try { text = 'Reading ' + new URL(event.url).hostname.replace(/^www\./, ''); } catch {}
      }
      if (!text) return;
      if (this.steps.at(-1) !== text) this.steps.push(text);
      this.line.hidden = false;
      this.line.textContent = 'Working: ' + text;
    }
    finish(message) {
      this.line.hidden = true;
      for (const text of (message ? this.memory || [] : [])) { const line = document.createElement('small'); line.className = 'raven-memory-updated'; line.textContent = text; message.append(line); }
      if (message && this.model) { const label = document.createElement('small'); label.className = 'raven-model-label'; label.textContent = this.model.includes('—') ? this.model : 'Answered by ' + this.model; message.append(label); }
      if (!this.steps.length || !message) return;
      const details = document.createElement('details'), summary = document.createElement('summary');
      details.className = 'raven-steps';
      summary.textContent = `Show steps (${this.steps.length})`;
      const list = document.createElement('ol');
      for (const text of this.steps) { const li = document.createElement('li'); li.textContent = text; list.append(li); }
      details.append(summary, list); message.append(details);
    }
    stop() { this.line.hidden = true; }
  };
})();
