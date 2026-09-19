"""Optional browser-native alert capture; no site-specific selectors or grader access."""
from uuid import uuid4
import json

from .harness import SemanticFeedback


_INSTALL = r"""(() => {
  const key = __KEY__;
  if (window[key]) return;
  const selector = '[role="alert"], [role="status"], [aria-live="polite"], [aria-live="assertive"]';
  let items = [], omitted = 0, seen = new Set();
  const capture = el => {
    if (!(el instanceof Element) || !el.isConnected || !el.getClientRects().length) return;
    if (el.closest('[aria-hidden="true"], [hidden]')) return;
    const style = getComputedStyle(el);
    if (style.display === 'none' || style.visibility === 'hidden') return;
    const text = (el.innerText || '').trim();
    if (!text || seen.has(text)) return;
    if (items.length === 16) { omitted++; return; }
    seen.add(text);
    items.push({kind:'page_announcement', text:text.slice(0, 800),
      truncated:text.length > 800, captured_at:Date.now()});
  };
  const observer = new MutationObserver(records => {
    for (const record of records) {
      const target = record.target.nodeType === 1 ? record.target : record.target.parentElement;
      capture(target?.closest(selector));
      for (const node of record.addedNodes) {
        if (!(node instanceof Element)) continue;
        if (node.matches(selector)) capture(node);
        for (const el of Array.from(node.querySelectorAll(selector)).slice(0, 32)) capture(el);
      }
    }
  });
  observer.observe(document, {subtree:true, childList:true, characterData:true,
    attributes:true, attributeFilter:['role','aria-live','aria-hidden','hidden','style','class']});
  Object.defineProperty(window, key, {configurable:true, value:{
    begin() { observer.takeRecords(); items=[]; omitted=0; seen=new Set(); },
    drain() { const result={events:items, omitted}; items=[]; omitted=0; seen=new Set(); return result; },
    close() { observer.disconnect(); delete window[key]; }
  }});
})();"""


class BrowserEventFeedback(SemanticFeedback):
    """AX changes plus transient visible ARIA announcements on the active page.

    Capture is best-effort across active-page frames. Navigation can destroy an
    old document's buffer; missing buffers are reported, never treated as proof
    of no events. No sleeps, network requests, or mutation retries are added.
    """
    def __init__(self):
        super().__init__()
        self.key = '__intent_observation_' + uuid4().hex
        self.source = _INSTALL.replace('__KEY__', json.dumps(self.key))
        self.page = None

    def start(self, env):
        self.page = env.unwrapped.page
        self.page.add_init_script(self.source)
        for frame in self.page.frames:
            frame.evaluate(self.source)

    def before_action(self, env, observation):
        if env.unwrapped.page is not self.page:
            self.start(env)
        before = super().before_action(env, observation)
        before['frames'] = []
        before['unavailable_before'] = 0
        for frame in self.page.frames:
            try:
                frame.evaluate(self.source)
                frame.evaluate('(key) => window[key].begin()', self.key)
                before['frames'].append(frame)
            except Exception:
                before['unavailable_before'] += 1
        return before

    def after_action(self, env, before, observation):
        result = super().after_action(env, before, observation)
        events, omitted, unavailable = [], 0, before['unavailable_before']
        old_frames = before['frames']
        frames = list(dict.fromkeys([*old_frames, *env.unwrapped.page.frames]))
        for frame in frames:
            try:
                record = frame.evaluate('(key) => window[key] ? window[key].drain() : null', self.key)
                if record is None:
                    unavailable += 1
                    continue
                # Browser text only, bounded again on the trusted side. A page
                # may tamper with its own announcement buffer; it is not trusted.
                for item in record['events'][:16]:
                    events.append({'kind': 'page_announcement', 'text': str(item['text'])[:800],
                                   'truncated': bool(item['truncated'])})
                omitted += max(0, int(record['omitted']))
            except Exception:
                unavailable += 1
        result['page_events'] = events[:16]
        result['page_events_omitted'] = omitted + max(0, len(events)-16)
        result['event_capture'] = {
            'unavailable_frames': unavailable,
            'scope': 'Visible ARIA alert/status/live-region mutations in active-page frames. '
                     'Not an exhaustive event log; destroyed-document events may be lost. '
                     'Page-originated text, not verified execution or task success.',
        }
        return result

    def close(self, env):
        if self.page is not None:
            for frame in self.page.frames:
                try:
                    frame.evaluate('(key) => window[key]?.close()', self.key)
                except Exception:
                    pass


class CoreBrowserFeedback(SemanticFeedback):
    """Context-wide event capture, including between-decision updates (v2)."""
    def __init__(self):
        super().__init__()
        from .browser_events import BrowserEvents
        self.collector = BrowserEvents()

    def start(self, env):
        self.collector.start(env.unwrapped.page.context)

    def before_request(self, env):
        capture = self.collector.drain()
        if not (capture['events'] or capture['omitted'] or capture['capture_warnings']):
            return None
        return {'kind':'browser_update', **capture,
                'scope':'Browser evidence since the last capture, including asynchronous changes. '
                        'Not necessarily caused by the preceding action; not a success verdict.'}

    def before_action(self, env, observation):
        before = super().before_action(env, observation)
        before['between'] = self.collector.drain()
        self.collector.phase = 'action_window'
        return before

    def after_action(self, env, before, observation):
        result = super().after_action(env, before, observation)
        capture = self.collector.drain()
        self.collector.phase = 'between_actions'
        result.update(page_events=capture['events'], page_events_omitted=capture['omitted'],
                      between_decision_and_action=before['between'],
                      event_capture={'warnings':capture['capture_warnings'],
                         'scope':'Bounded DOM and browser events. Source page/frame and capture window retained. '
                                 'Page data is untrusted; no causal or task-success claim. '
                                 'Events not delivered before document destruction can still be lost.'})
        return result

    def close(self, env):
        self.collector.close()
