"""Agent-only custody and unmarked capture for generated-world fast capture.

Reuses HumanBrowser's owner-thread capture/guard deadlines, stable-frame
projection and capture retries without any policy-visible human features: no
handover/tab tools, human chat, confirmations or content-change review. Every
tab is agent-controlled and BrowserGym's active-page tracking is followed as in
native mode.

The accessibility tree is extracted AFTER BrowserGym's temporary marking has
been removed, so every index (decision overview, background capture, batch
captures) sees the same unmarked page. Marking still assigns persistent BIDs;
the DOM snapshot taken while marked maps backend node IDs to those BIDs.
"""
from pathlib import Path
from types import FunctionType
import time

from browsergym.core.env import BrowserEnv
from playwright.sync_api import Error as PlaywrightError

from .cdp_json import extract_json
from .human_browser import HumanBrowser, _ObservationView
from .human_handover import HumanHandoverController
from .batching import DocumentScanInvalidated

SETTLE_PATH = Path(__file__).with_name('page_settle.js')
SETTLE_SOURCE = SETTLE_PATH.read_text()
READINESS_QUIET_MS = 60
READINESS_TIMEOUT_MS = 2000
VERSION = 'agent-custody-v1'


def dom_bid_map(dom):
    """backendNodeId -> BID attribute from a BrowserGym DOMSnapshot."""
    strings = dom['strings']; result = {}
    for document in dom['documents']:
        nodes = document['nodes']
        for index, backend in enumerate(nodes.get('backendNodeId', [])):
            attributes = nodes['attributes'][index] if index < len(nodes.get('attributes', [])) else []
            for key, value in zip(attributes[::2], attributes[1::2]):
                if strings[key] == 'bid':
                    result[backend] = strings[value]
                    break
    return result


def attach_bids(tree, bids):
    for node in tree['nodes']:
        node.pop('browsergym_id', None)
        bid = bids.get(node.get('backendDOMNodeId'))
        if bid is not None and node.get('role', {}).get('value') not in ('StaticText', 'InlineTextBox'):
            node['browsergym_id'] = bid
    return tree


def settle_call(page, expression, argument=None):
    """Evaluate against the settle tracker; None when this document lacks it."""
    try:
        return page.evaluate('([e,a])=>globalThis.__intentPageSettle?(e==="state"?__intentPageSettle.state():'
                             'e==="begin"?__intentPageSettle.beginMarking():e==="end"?__intentPageSettle.endMarking():'
                             '__intentPageSettle.wait(a[0],a[1])):null', [expression, argument])
    except PlaywrightError:
        return None


def capture_unmarked(view, budget, *, screenshots=True, hooks=()):
    """BrowserGym _get_obs (marking, DOMSnapshot, unmark, screenshot) + unmarked AX.

    The marked-time AX call is skipped; one merged AX extraction follows unmark.
    A changed public revision between marking and the AX read invalidates the
    attempt (HumanBrowser retries a fresh capture; no action is replayed).
    """
    from browsergym.core import observation as core
    page = view.page
    before = settle_call(page, 'state')
    for hook in hooks:
        hook.before_capture(page)  # Private probe; failures are the hook's unknowns.

    def pre_extract(*args, **kwargs):
        settle_call(page, 'begin')
        return budget.mark(*args, **kwargs)

    def post_extract(*args, **kwargs):
        try:
            return (budget.scoped_unmark if hasattr(budget, 'quarantined') else core._post_extract)(*args, **kwargs)
        finally:
            settle_call(page, 'end')

    obs = _clone_capture(view, budget, screenshots, pre_extract, post_extract)
    tree = budget.timed('extract_merged_axtree_unmarked',
                        lambda: extract_json(core.extract_merged_axtree, page))
    after = settle_call(page, 'state')
    if before is not None and after is not None and (
            before['documentId'] != after['documentId'] or before['revision'] != after['revision']):
        raise DocumentScanInvalidated({'reason': 'page_revision_changed_during_unmarked_capture',
            'before': before, 'after': after})
    obs['axtree_object'] = attach_bids(tree, dom_bid_map(obs['dom_object']))
    obs['page_revision'] = after
    obs['ax_extraction'] = {'version': 'unmarked-ax-v1', 'bids': 'dom_snapshot_bid_attribute',
                            'revision_checked': before is not None and after is not None}
    return obs


def _clone_capture(view, budget, screenshots, pre_extract, post_extract):
    """capture_native's measured clone with marking hooks and no marked AX read."""
    original = BrowserEnv._get_obs
    scope = dict(original.__globals__)
    replacements = {'_pre_extract': pre_extract, '_post_extract': post_extract,
                    'extract_merged_axtree': lambda page: {'nodes': []}}
    for name in ('_pre_extract', '_post_extract', 'extract_dom_snapshot', 'extract_merged_axtree',
                 'extract_focused_element_bid', 'extract_dom_extra_properties', 'extract_screenshot'):
        fn = replacements.get(name, scope[name])

        def measured(*a, _name=name, _fn=fn, **kw):
            call = (lambda: extract_json(_fn, *a, **kw)) if _name == 'extract_dom_snapshot' else (lambda: _fn(*a, **kw))
            result = budget.timed(_name, call)
            if _name == '_post_extract':
                budget.needs_unmark = False
            return result
        scope[name] = measured
    if not screenshots:
        scope['extract_screenshot'] = lambda page: None
    capture = FunctionType(original.__code__, scope, original.__name__, original.__defaults__, original.__closure__)
    return capture(view)


class AgentBrowser(HumanBrowser):
    """HumanBrowser with all tabs agent-owned and native active-page following."""

    policy_visible = False

    def __init__(self, env, trace, pipeline, *, capture_timeout_mode='bounded', readiness=True):
        super().__init__(env, HumanHandoverController(), trace, pipeline, wait_for_human=False,
                         compact_tabs=False, stable_frames=True, capture_timeout_mode=capture_timeout_mode)
        self.capture_hooks = []
        self.capture_function = lambda view, budget, *, screenshots=True: capture_unmarked(
            view, budget, screenshots=screenshots, hooks=self.capture_hooks)
        # BrowserGym's task default is 1000 ms Playwright slow motion per input
        # action. Set before reset so native and pooled launches both omit it.
        env.slow_mo = 0
        self.readiness = readiness
        self.bid_map = {}
        self.bid_document = None
        self.last_readiness = None
        self.content_agreement = False

    # -- custody --------------------------------------------------------
    def activation(self, page):
        """Native BrowserGym follows JS activation; every tab is the agent's."""
        if not self.ready:
            return self.saved['_activate_page_from_js'](page)
        self.saved['_activate_page_from_js'](page)
        self.known_agent_pages.add(page)

    def _sync(self, budget=None):
        # No human opener exists: pages the agent's documents open stay agent-owned.
        self.known_agent_pages.update(self.env.context.pages)
        return super()._sync(budget)

    def prepare(self, *, allow_wait=True):
        self.sync()
        current = self.id_for(self.env.page)
        if current is not None and not self.env.page.is_closed():
            self.active = current
        return super().prepare(allow_wait=allow_wait)

    def start(self):
        self.env.context.add_init_script(SETTLE_SOURCE)
        for page in self.env.context.pages:
            try:
                page.evaluate(SETTLE_SOURCE)
            except PlaywrightError as exc:
                self.trace.event('page_settle_install_failed', error=f'{type(exc).__name__}: {exc}')
        # The fixed BrowserGym settle delay is replaced by measured readiness.
        self.env.pre_observation_delay = 0
        super().start()

    # -- capture ----------------------------------------------------------
    def capture(self):
        obs = super().capture()
        # Pair hooks with the final (stable-frame projected) observation object:
        # the last successful attempt's probe belongs to this capture.
        frame_id = obs.get('human_tab_capture', {}).get('document', {}).get('frame_id')
        for hook in self.capture_hooks:
            hook.after_capture(obs, frame_id)
        document = obs.get('human_tab_capture', {}).get('document')
        if obs.get('dom_object') is not None and document is not None:
            self.remember_bids(document, dom_bid_map(obs['dom_object']))
        return obs

    def remember_bids(self, document, bids):
        # Backend node IDs are only meaningful within one document: after a
        # navigation Chromium can reuse small IDs for unrelated elements.
        if self.bid_document != document:
            self.bid_document, self.bid_map = document, {}
        self.bid_map.update(bids)

    def known_bids(self, document):
        return dict(self.bid_map) if self.bid_document == document else {}

    def wait(self):
        """Readiness after an action: DOM load, then network/DOM quiet."""
        if not self.ready:
            return self.saved_wait()
        super().wait()  # bounded domcontentloaded across frames
        if not self.readiness:
            return
        page = self.pages[self.active]
        started = time.monotonic()
        result = settle_call(page, 'wait', [READINESS_QUIET_MS, READINESS_TIMEOUT_MS])
        if result is None:
            # New document without the tracker (e.g. error page): short fixed wait.
            time.sleep(0.1)
            result = {'status': 'unknown', 'reason': 'settle_tracker_unavailable', 'fallback_sleep_seconds': 0.1}
        result['seconds'] = time.monotonic() - started
        self.last_readiness = result
        self.trace.event('observation_readiness', scope='page_settle_v1', **result)
        if result['status'] not in ('ready', 'unknown') and not self.env.last_action_error:
            self.env.last_action_error = (
                'Readiness ' + result['status'] + ': the page was still loading or changing after the action. '
                'Action effects are uncertain; inspect before acting. No action was replayed.')

    def content_review(self, ticket, obs, decision, *, step, call_id):
        # Native generated-world parity: no full-content agreement or proceed_action.
        return None

    def _guard(self, ticket, obs=None, *, decision=None, budget=None):
        failure = super()._guard(ticket, obs, decision=decision, budget=budget)
        return None if failure == 'tab_content_changed_since_decision' else failure

    def describe(self):
        return {'version': VERSION, 'custody': 'agent_only', 'policy_tools_added': [],
                'capture': 'unmarked-ax-v1', 'readiness': 'page-settle-v1' if self.readiness else 'native_dom_wait',
                'readiness_quiet_ms': READINESS_QUIET_MS, 'readiness_timeout_ms': READINESS_TIMEOUT_MS,
                'pre_observation_delay_seconds': 0}
