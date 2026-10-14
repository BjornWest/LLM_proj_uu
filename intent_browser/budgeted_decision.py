"""Decision observation = one unmarked AX read; full capture overlaps inference.

The delivered context is the ordinary token-budgeted AX overview (what the
model sees is configured by the AX profile, not by this capture). Before the
model call only the main page's merged accessibility tree is read, without
BrowserGym's temporary marking. BIDs come from earlier DOM snapshots of the
same elements; elements first seen now get native-compatible BIDs assigned in
breadth-first overview order, bounded by the overview budget.

The background capture (marking, DOMSnapshot, unmarked AX) runs on the
browser-owner thread while the request is in flight and becomes the AX index
for tools, targeted guards and recording. Validation after completion requires
the same document/custody and either an unchanged public page revision or the
same indexed AX semantics; otherwise the decision is invalidated and the model
is told, never silently executed against a different page.
"""
from copy import deepcopy
from uuid import uuid4
import asyncio
import json
import threading
import time

from .agent_browser import dom_bid_map, attach_bids, settle_call
from .cdp_json import extract_json
from .dynamic_preview import DynamicPreview
from .observation_pipeline import ObservationChanged
from .preview_bids import TAGS, GENERATOR

VERSION = 'budgeted-decision-v1'
SKIP_ROLES = ('none', 'LineBreak', 'InlineTextBox')

# Same allocator/whitelist as BrowserGym marking and preview BIDs, but without
# the viewport restriction: native marking assigns BIDs to every element.
ASSIGN = '''function(...elements) {
''' + TAGS + GENERATOR + '''
    const first = !("browsergym_elem_counter" in window);
    if (!first && (!Number.isSafeInteger(window.browsergym_elem_counter) ||
        window.browsergym_elem_counter < 0 || !window.browsergym_frame_id_generator ||
        typeof window.browsergym_frame_id_generator.next !== 'function'))
        return elements.map(() => null);
    let initialized = !first;
    return elements.map(elem => {
        if (!elem || elem.nodeType !== 1 || elem.ownerDocument !== document || !elem.isConnected)
            return null;
        let root = elem.getRootNode();
        while (root instanceof ShadowRoot) {
            if (root.mode !== 'open') return null;
            root = root.host.getRootNode();
        }
        if (root !== document) return null;
        const tag = elem.tagName.toLowerCase();
        if (!html_tags.has(tag) || ['iframe','frame'].includes(tag)) return null;
        if (first && elem.hasAttribute('bid')) return null;
        if (!initialized) {
            window.browsergym_elem_counter = 0;
            window.browsergym_frame_id_generator = new IFrameIdGenerator();
            initialized = true;
        }
        let bid = elem.getAttribute('bid');
        if (bid === null) {
            if (window.browsergym_elem_counter >= Number.MAX_SAFE_INTEGER) return null;
            bid = String(window.browsergym_elem_counter++);
            elem.setAttribute('bid',bid);
        }
        return /^(0|[1-9][0-9]*)$/.test(bid) ? bid : null;
    });
}'''


def breadth_first_elements(nodes, frame_id, limit):
    """Backend IDs of indexed (useful) main-frame nodes in overview BFS order.

    Uses the AX explorer's node filter, expanding only as far as needed.
    """
    by_id = {n['nodeId']: n for n in nodes}

    def fields(node):
        role = str(node.get('role', {}).get('value', ''))
        name = str(node.get('name', {}).get('value', ''))
        value = str(node.get('value', {}).get('value', ''))
        props = [p for p in node.get('properties', []) if isinstance(p.get('value'), dict) and 'value' in p['value']
                 and p.get('name') not in ('focusable', 'settable', 'editable')]
        return role, name, value, props

    def useful(node, parent_name):
        role, name, value, props = fields(node)
        if node.get('ignored', False) or role in SKIP_ROLES:
            return False
        if role == 'generic' and not name and not value and not props:
            return False
        return not (role == 'StaticText' and parent_name is not None and name and name in parent_name)

    def children(raw_id, parent_name):
        out, stack, seen = [], list(reversed(by_id[raw_id].get('childIds', []))), set()
        while stack:
            child = stack.pop()
            if child in seen or child not in by_id:
                continue
            seen.add(child)
            node = by_id[child]
            if useful(node, parent_name):
                out.append(child)
            else:
                stack.extend(reversed(node.get('childIds', [])))
        return out

    roots = [n['nodeId'] for n in nodes if n.get('frameId') == frame_id and n.get('role', {}).get('value') == 'RootWebArea']
    queue, result = list(roots[:1]), []
    while queue and len(result) < limit:
        raw_id = queue.pop(0)
        node = by_id[raw_id]
        role, name, _, _ = fields(node)
        if node.get('backendDOMNodeId') is not None and role not in ('RootWebArea', 'StaticText'):
            result.append(node['backendDOMNodeId'])
        queue.extend(children(raw_id, name))
    return result


def ax_signatures(tree):
    """Raw AX node multiset without BIDs (synthetic layout IDs normalized)."""
    from collections import Counter
    from .observation_pipeline import ax_node_signature
    return Counter(ax_node_signature({k: v for k, v in n.items() if k != 'browsergym_id'})
                   for n in tree['nodes'])


class BudgetedDecision(DynamicPreview):
    mode = VERSION
    preview_bids = True

    def __init__(self, human, trace, *, budget_tokens):
        super().__init__(human, trace, depth=1, max_nodes=1, preview_bids=True)
        self.budget_tokens = budget_tokens  # callable -> next automatic overview budget

    def preview(self, previous):
        from .native_capture import CaptureBudget
        self.human.prepare()  # Outside the decision deadline, as for previews.
        budget = CaptureBudget(self.human.env.page, self.trace, event_prefix='budgeted_decision',
                               enforce=self.human.capture_timeout_mode == 'bounded')
        with budget.rpc_deadline():
            return budget.timed('decision_ax_read', lambda: self._preview(previous))

    def _preview(self, previous):
        start = time.monotonic(); self.full = None; self.pending = None
        self.previous_metadata = {k: deepcopy(previous[k]) for k in ('goal', 'goal_object') if k in previous}
        h = self.human
        if h.states()[h.active]['state'] == 'returned':
            return None
        identity = self.identity(); page = h.env.page
        frame_id = identity['document']['frame_id']
        identity_url = page.url
        before = settle_call(page, 'state')
        from browsergym.core import observation as core
        ax_start = time.monotonic()
        tree = extract_json(core.extract_merged_axtree, page)
        ax_seconds = time.monotonic() - ax_start
        bids = h.known_bids(identity['document'])
        budget = self.budget_tokens() or 0
        # ~50-60 Qwen tokens per overview entry: 2x headroom over the entries
        # that fit, so delivered first-seen elements carry their BIDs.
        limit = max(48, budget // 20)
        candidates = [b for b in breadth_first_elements(tree['nodes'], frame_id, limit) if b not in bids]
        assign_start = time.monotonic()
        assigned = self._assign(page, candidates) if candidates else {}
        assign_seconds = time.monotonic() - assign_start
        bids.update(assigned); h.remember_bids(identity['document'], assigned)
        after = settle_call(page, 'state')
        if before is None or after is None:
            # No page-side revision tracker: fall back to the full identity scan.
            if self.identity() != identity:
                raise ObservationChanged('Document/custody changed during decision capture')
        elif before != after or page.url != identity_url:
            # Same tracker instance (document) and revision: unchanged main document.
            raise ObservationChanged('Page changed during decision capture')
        attach_bids(tree, bids)
        # Same display projection a full capture registers; the title is the
        # document title as exposed by the AX root (no extra page.title() call).
        root = next((n for n in tree['nodes'] if n.get('frameId') == frame_id
                     and n.get('role', {}).get('value') == 'RootWebArea'), None)
        title = str((root or {}).get('name', {}).get('value', ''))[:1000]
        h.controller.register(h.active, title=title, url=h.display_url(page.url))
        h.emit()
        snapshot = h.controller.snapshot()
        live = [t for t in snapshot['tabs'] if t['state'] != 'closed']
        obs = dict(self.previous_metadata)
        obs.update(url=page.url, chat_messages=deepcopy(h.env.chat.messages),
            last_action=h.env.last_action, last_action_error=h.env.last_action_error,
            open_pages_urls=tuple(t['url'] for t in live), open_pages_titles=tuple(t['title'] for t in live),
            active_page_index=[next(i for i, t in enumerate(live) if t['tab_id'] == h.active)],
            human_tabs={'active_tab_id': h.active, 'revision': snapshot['revision'], 'tabs': deepcopy(live),
                        'recent_transitions': deepcopy(h.notices)},
            human_tab_capture={'tab_id': h.active, 'document': identity['document'], 'attempts': 1},
            axtree_object=tree, dom_object=None, screenshot=None, extra_element_properties={},
            focused_element_bid=None, page_revision=after,
            observation_capture={'version': VERSION, 'coverage': 'full',
                'ax': 'complete merged accessibility tree, unmarked', 'dom_snapshot': 'deferred_to_background',
                'screenshots': 'not_captured', 'bids': 'known elements plus first-seen overview candidates',
                'scope': 'Decision context; full capture validates identity before tools execute'})
        self.pending = {'identity': identity, 'revision': after, 'tree': tree,
                        'bids': [(n['backendDOMNodeId'], n.get('role', {}).get('value'), n['browsergym_id'])
                                 for n in tree['nodes'] if n.get('browsergym_id') is not None
                                 and n.get('backendDOMNodeId') in assigned]}
        self.trace.event('budgeted_decision_completed', seconds=time.monotonic() - start,
            ax_seconds=ax_seconds, raw_nodes=len(tree['nodes']), bid_candidates=len(candidates),
            bids_assigned=len(assigned), bid_assignment_seconds=assign_seconds, overview_budget=budget,
            identity=identity, owner_thread=self.owner,
            scope='Decision AX read only; DOM snapshot, index and recording follow in the background')
        return obs

    def _assign(self, page, backend_ids):
        group = 'intent-decision-' + uuid4().hex
        cdp = page.context.new_cdp_session(page)
        try:
            async def resolve_all():
                semaphore = asyncio.Semaphore(8)
                async def resolve(node):
                    async with semaphore:
                        return await cdp._impl_obj.send('DOM.resolveNode', {'backendNodeId': node, 'objectGroup': group})
                return await asyncio.gather(*(resolve(n) for n in backend_ids), return_exceptions=True)
            results = page._sync(resolve_all())
            pairs = [(node, r.get('object', {}).get('objectId')) for node, r in zip(backend_ids, results)
                     if not isinstance(r, BaseException)]
            pairs = [(node, obj) for node, obj in pairs if obj]
            if not pairs:
                return {}
            result = cdp.send('Runtime.callFunctionOn', {'objectId': pairs[0][1], 'functionDeclaration': ASSIGN,
                'arguments': [{'objectId': o} for _, o in pairs], 'returnByValue': True})
            if result.get('exceptionDetails'):
                raise ObservationChanged('Decision BID assignment failed')
            values = result.get('result', {}).get('value')
            if not isinstance(values, list) or len(values) != len(pairs):
                raise ObservationChanged('Invalid decision BID assignment result')
            return {node: bid for (node, _), bid in zip(pairs, values) if isinstance(bid, str)}
        finally:
            try:
                cdp.send('Runtime.releaseObjectGroup', {'objectGroup': group})
            finally:
                cdp.detach()

    def validate(self):
        if self.identity() != self.pending['identity']:
            raise ObservationChanged('Document/custody changed during inference or background capture')
        if self.full is None:
            raise ObservationChanged('No full background observation')
        if self.full['human_tab_capture']['document'] != self.pending['identity']['document']:
            raise ObservationChanged('Background capture changed document')
        same_revision = (self.pending['revision'] is not None and
                         self.full.get('page_revision') == self.pending['revision'])
        if not same_revision and ax_signatures(self.full['axtree_object']) != ax_signatures(self.pending['tree']):
            raise ObservationChanged('Page changed during inference; decision context is stale')
        by_backend = {}
        for node in self.full['axtree_object']['nodes']:
            if node.get('browsergym_id') is not None:
                by_backend.setdefault(node.get('backendDOMNodeId'), set()).add(node['browsergym_id'])
        for backend, role, bid in self.pending['bids']:
            if by_backend.get(backend) != {bid}:
                raise ObservationChanged('Decision BID no longer names the same full-capture element')
