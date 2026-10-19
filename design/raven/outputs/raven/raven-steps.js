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
      this.steps = [];
    }
    reset() { this.steps = []; this.line.hidden = false; this.line.textContent = 'Working: starting research…'; }
    event(event) {
      let text;
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
