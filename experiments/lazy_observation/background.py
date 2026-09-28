"""Experimental shallow-first observation with serialized browser ownership.

No production imports/patches. The inference caller never receives Playwright
objects. Full snapshots remain historical public observations, not live truth.
"""
from concurrent.futures import Future, ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass
import json
import threading
import time
from uuid import uuid4

from prototype import LazyAX, StaleTarget, semantic


class ObsoleteObservation(RuntimeError):
    pass


@dataclass(frozen=True)
class Observation:
    initial: Future
    ready: Future
    epoch: int


STAMP = """() => {
  if (!globalThis.__lazyAXRevision) {
    const s = {document: Array.from(crypto.getRandomValues(new Uint32Array(4)),
      n => n.toString(16).padStart(8, '0')).join(''), revision: 0};
    const observer = new MutationObserver(() => s.revision++);
    observer.observe(document, {subtree:true,childList:true,attributes:true,characterData:true});
    for (const name of ['input','change','resize']) addEventListener(name, () => s.revision++, true);
    globalThis.__lazyAXRevision = {s, observer};
  }
  const {s,observer} = globalThis.__lazyAXRevision;
  if (observer.takeRecords().length) s.revision++;
  return {...s, url:location.href};
}"""


def tree_signature(nodes):
    """Exact CDP node content, including focus/ignored nodes and native hierarchy."""
    return json.dumps(sorted(nodes, key=lambda n:n['nodeId']), sort_keys=True)


class BackgroundBrowser:
    def __init__(self, setup, *, capture_hook=None, strict=False):
        """setup(page) and test-only capture_hook(stage, self) run on owner thread."""
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='ax-browser')
        self.lock = threading.Lock()
        self.epoch = 0
        self.closed = False
        self.capture_hook = capture_hook
        # Historical performance experiments used revision guards only. Strict
        # mode is a correctness reference, with a deliberate full-read cost.
        self.strict = strict
        self.log = []
        self.snapshots = {}
        self.setup_future = self.pool.submit(self._open, setup)

    def _open(self, setup):
        from playwright.sync_api import sync_playwright
        self.pw = self.browser = self.lazy = None
        self.owner_thread = threading.get_ident()
        try:
            self.pw = sync_playwright().start()
            self.browser = self.pw.chromium.launch(headless=True)
            self.context = self.browser.new_context(viewport={'width':1280,'height':900})
            self.context.add_init_script('(' + STAMP + ')()')
            self.page = self.context.new_page()
            setup(self.page)
            self.lazy = LazyAX(self.page)
        except BaseException:
            self._cleanup()
            raise

    def _record(self, phase, **fields):
        self.log.append(dict(phase=phase, time=time.perf_counter(),
                             thread=threading.get_ident(), **fields))

    def _reserve_epoch(self):
        with self.lock:
            if self.closed:
                raise RuntimeError('Browser worker is closed')
            self.epoch += 1
            return self.epoch

    def _current(self, epoch):
        with self.lock:
            if self.closed or epoch != self.epoch:
                raise ObsoleteObservation('Observation superseded or browser closed')

    def _stamp(self):
        return self.page.evaluate(STAMP)

    def _requires_full_validation(self, snapshot):
        return self.strict

    def _freshness_label(self, snapshot):
        return ('full_foreground_AX_equal_at_validation' if self.strict else
                'DOM/event revision checked; not a complete AX change detector')

    def observe(self, *, url=None, reload=False):
        epoch = self._reserve_epoch()
        initial, ready = Future(), Future()
        self.pool.submit(self._observe, epoch, initial, ready, url, reload)
        return Observation(initial, ready, epoch)

    def _observe(self, epoch, initial, ready, url, reload):
        try:
            self.setup_future.result()
            self._current(epoch)
            if url is not None:
                self.page.goto(url)
            elif reload:
                self.page.reload()
            self.snapshots.clear()
            self._record('overview_start', epoch=epoch)
            stamp = self._stamp()
            shallow = self.lazy.overview()
            if self.strict and stamp != self._stamp():
                raise ObsoleteObservation('Page changed during shallow capture')
            self._current(epoch)
            self._record('initial_published', epoch=epoch)
            # Deep copy: later cache loading never modifies delivered observations.
            initial.set_result(deepcopy(dict(shallow, observation_epoch=epoch,
                                            background_pending=True)))
            self._record('full_start', epoch=epoch)
            if self.capture_hook:
                self.capture_hook('before', self)
            self._current(epoch)
            nodes = self.lazy.send('Accessibility.getFullAXTree')['nodes']
            if self.capture_hook:
                self.capture_hook('after', self)
            end_stamp = self._stamp()
            self.lazy.check()
            self._current(epoch)
            if stamp != end_stamp:
                raise ObsoleteObservation('Page changed during observation; request a fresh overview')
            if self.strict:
                by_id = {n['nodeId']:n for n in nodes}
                for item in shallow['items']:
                    node = by_id.get(item['ref'].split(':', 1)[1])
                    if node is None or semantic(node) != {k:item[k] for k in semantic(node)}:
                        raise ObsoleteObservation('Shallow and complete observations disagree')
            snapshot_id = uuid4().hex
            self.lazy._store(nodes)
            snapshot = dict(id=snapshot_id, epoch=epoch, stamp=end_stamp, nodes=nodes,
                            captured_at=time.perf_counter(), root_key=self.lazy.root_key,
                            generation=self.lazy.generation)
            with self.lock:
                if self.closed or self.epoch != epoch:
                    raise ObsoleteObservation('Superseded before snapshot publication')
                self.snapshots[snapshot_id] = snapshot
            self._record('full_published', epoch=epoch, snapshot=snapshot_id, nodes=len(nodes))
            ready.set_result(dict(snapshot_id=snapshot_id, observation_epoch=epoch,
                                  nodes=len(nodes), captured_at=snapshot['captured_at']))
        except BaseException as error:
            self._record('observation_failed', epoch=epoch, error=type(error).__name__)
            if not initial.done():
                initial.set_exception(error)
            ready.set_exception(error)

    def _snapshot(self, observation):
        # The queued browser job starts only after capture completes. This also
        # propagates extraction errors before executing any page action.
        meta = observation.ready.result()
        self._current(observation.epoch)
        value = self.snapshots[meta['snapshot_id']]
        self.lazy.check()
        if self.lazy.root_key != value['root_key'] or self._stamp() != value['stamp']:
            raise ObsoleteObservation('Observed document changed; request a fresh observation')
        if self._requires_full_validation(value):
            # DOM mutation listeners miss value/checked property writes, CSSOM
            # changes, focus and other AX effects. Until a complete application
            # revision contract exists, never certify a cached tree from those
            # listeners alone. Compare against the same foreground CDP capture.
            current = self.lazy.send('Accessibility.getFullAXTree')['nodes']
            self._current(observation.epoch)
            if (self._stamp() != value['stamp'] or
                    tree_signature(current) != tree_signature(value['nodes'])):
                raise ObsoleteObservation('Foreground AX differs; request a fresh observation')
            self._record('foreground_verified', epoch=observation.epoch, nodes=len(current))
        return value

    def search(self, observation, terms, *, role=None, limit=5, scope=None):
        return self.pool.submit(self._search, observation, terms, role, limit, scope,
                                time.perf_counter())

    def _search(self, observation, terms, role, limit, scope, submitted):
        started = time.perf_counter()
        snapshot = self._snapshot(observation)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError('limit must be an integer from 1 to 100')
        if isinstance(terms, str):
            terms = [terms]
        nodes = snapshot['nodes']
        by_id = {n['nodeId']:n for n in nodes}
        allowed = set(by_id)
        if scope:
            root = self.lazy._resolve(scope)['nodeId']
            if root not in by_id:
                raise StaleTarget('Search scope is not in snapshot')
            allowed = set(); pending = [root]
            while pending:
                node_id = pending.pop()
                if node_id in allowed: continue
                allowed.add(node_id)
                pending.extend(by_id.get(node_id, {}).get('childIds', []))
        found = []
        for node in nodes:
            if node['nodeId'] not in allowed or node.get('ignored'): continue
            item = semantic(node)
            if role and item['role'] != role: continue
            text = json.dumps(item, ensure_ascii=False).casefold()
            if terms and not any(term.casefold() in text for term in terms): continue
            found.append(node)
        result = dict(items=[self.lazy.describe(n) for n in found[:limit]],
                      total_matches=len(found), snapshot_id=snapshot['id'],
                      coverage='complete_captured_snapshot_not_live_document',
                      freshness=self._freshness_label(snapshot),
                      queue_wait_seconds=started-submitted,
                      execution_seconds=time.perf_counter()-started)
        self._record('search_finished', epoch=observation.epoch, **{k:result[k] for k in
                     ('queue_wait_seconds','execution_seconds','total_matches')})
        return result

    def act(self, observation, ref, *, operation='click', text=None):
        return self.pool.submit(self._act, observation, ref, operation, text,
                                time.perf_counter())

    def _act(self, observation, ref, operation, text, submitted):
        started = time.perf_counter()
        snapshot = self._snapshot(observation)
        node_id = ref.split(':',1)[-1]
        old = next((n for n in snapshot['nodes'] if n['nodeId']==node_id), None)
        if old is None or ref != f"d{snapshot['generation']}:{node_id}":
            raise StaleTarget('Target was not present in the supplied snapshot')
        # Validate semantics against what was captured, not against a silently
        # refreshed cache. Property-only JS changes can evade mutation observers.
        token = self.lazy.prepare_target(ref)
        target = self.lazy.tokens[token]
        by_id = {n['nodeId']:n for n in snapshot['nodes']}
        chain = []; n = old
        while n is not None:
            chain.append((n.get('backendDOMNodeId'),semantic(n)))
            n = by_id.get(n.get('parentId'))
        if chain != target['chain']:
            self.lazy.tokens.pop(token)
            raise StaleTarget('Target/ancestor changed since delivered snapshot')
        # Check and invalidate atomically with respect to a caller requesting a
        # replacement observation. In-flight native actions cannot be cancelled.
        with self.lock:
            if self.closed or self.epoch != observation.epoch:
                raise ObsoleteObservation('Action superseded before dispatch')
            self.epoch += 1
        # All known actions invalidate the full snapshot even if execution fails.
        self.snapshots.clear()
        self._record('action_start', epoch=observation.epoch)
        result = self.lazy.act(token, operation=operation, text=text)
        self._record('action_finished', epoch=observation.epoch)
        return dict(result, queue_wait_seconds=started-submitted,
                    execution_seconds=time.perf_counter()-started)

    def diagnostic(self, callback):
        """Privileged test fixture access; never a policy/model tool."""
        def run():
            self.setup_future.result()
            return callback(self)
        return self.pool.submit(run)

    def _cleanup(self):
        try:
            if self.browser:
                self.browser.close()
                self.browser = None
        finally:
            if self.pw:
                self.pw.stop()
                self.pw = None

    def close(self):
        with self.lock:
            if self.closed: return
            self.closed = True
            self.epoch += 1
        try:
            self.pool.submit(self._cleanup).result(timeout=30)
        finally:
            self.pool.shutdown(wait=True)
