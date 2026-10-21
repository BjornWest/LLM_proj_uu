"""Opt-in shallow main-document observation with owner-thread full capture.

The preview is not a full AX index. Visible preview elements can receive native
BIDs early; every proposed BID must match the full capture before dispatch. Native extraction and all
subsequent action guards remain authoritative for targets and frame coverage.
"""
from copy import deepcopy
import threading
import time

from .cdp_json import send_json
from .frame_capture import frame_documents, main_signature
import os
from .observation_pipeline import ObservationChanged

PROPERTIES = frozenset(('disabled', 'checked', 'selected', 'expanded', 'pressed',
                       'readonly', 'required', 'focusable', 'level'))


def semantics(node):
    return {'backend_node_id': node.get('backendDOMNodeId'),
            **{key: node.get(key, {}).get('value') for key in ('role', 'name', 'value')},
            'state': {p['name']: p['value'].get('value')
                      for p in node.get('properties', []) if p['name'] in PROPERTIES}}


def main_nodes(tree, frame):
    """Frame namespace + DOM identity + role; inline text shares its parent's DOM ID."""
    raw = tree['nodes']; by_id = {n['nodeId']: n for n in raw}; seen = set(); result = {}
    def walk(key, owner):
        if key in seen: return
        seen.add(key); node = by_id.get(key)
        if node is None: return
        owner = node.get('frameId', owner)
        if owner == frame and node.get('backendDOMNodeId') is not None:
            result.setdefault((node['backendDOMNodeId'], node.get('role', {}).get('value')), []).append(node)
        for child in node.get('childIds', []): walk(child, owner)
    for node in raw:
        if node.get('frameId') == frame: walk(node['nodeId'], frame)
    return result


class DynamicPreview:
    def __init__(self, human, trace, *, depth=2, max_nodes=64, preview_bids=True):
        self.human, self.trace = human, trace
        self.depth, self.max_nodes = depth, max_nodes
        self.preview_bids = preview_bids
        self.owner = threading.get_ident()
        self.pending = None; self.full = None; self.serial = 0

    def identity(self):
        if threading.get_ident() != self.owner:
            raise RuntimeError('Browser capture left its owner thread')
        self.human.sync()
        state = self.human.states().get(self.human.active)
        if state is None or state['state'] != 'agent_controlled':
            raise ObservationChanged('Preview custody unavailable')
        return {'tab': self.human.active, 'cycle': state['handover_id'],
                'document': main_signature(frame_documents(self.human.env.page))}

    def preview(self, previous):
        from .native_capture import CaptureBudget
        self.human.prepare()  # Any supervised human wait is outside the deadline.
        budget=CaptureBudget(self.human.env.page,self.trace,event_prefix='dynamic_preview',
                             enforce=self.human.capture_timeout_mode=='bounded')
        with budget.rpc_deadline():
            return budget.timed('shallow_main_document',lambda:self._preview(previous))

    def _preview(self, previous):
        start = time.monotonic(); self.full = None; self.pending = None; self.changed_bids = set()
        self.previous_metadata={k:deepcopy(previous[k]) for k in ('goal','goal_object') if k in previous}
        h = self.human
        # Returned tabs require the existing full recapture/resume lifecycle.
        if h.states()[h.active]['state'] == 'returned': return None
        identity = self.identity(); page = h.env.page
        cdp = page.context.new_cdp_session(page)
        bid_start=time.monotonic();bid_seconds=0
        try:
            raw = send_json(cdp,'Accessibility.getFullAXTree', {'depth': self.depth})['nodes']
            nodes = [deepcopy(n) for n in raw if not n.get('ignored') and n.get('backendDOMNodeId') is not None]
            omitted = max(0, len(nodes) - self.max_nodes); nodes = nodes[:self.max_nodes]
            bids={}
            if self.preview_bids:
                from .preview_bids import assign_preview_bids
                bid_start=time.monotonic()
                bids=assign_preview_bids(page,cdp,nodes)
                bid_seconds=time.monotonic()-bid_start
        finally: cdp.detach()
        if self.identity() != identity:
            raise ObservationChanged('Document/custody changed during preview')
        # Preserve hierarchy edges only within the delivered subset. A missing
        # child never means removed. No bid from old history is assigned here.
        ids = {n['nodeId'] for n in nodes}
        for node in nodes:
            node.pop('browsergym_id', None)
            if node.get('backendDOMNodeId') in bids:node['browsergym_id']=bids[node['backendDOMNodeId']]
            if 'childIds' in node: node['childIds'] = [i for i in node['childIds'] if i in ids]
        snapshot = h.controller.snapshot()
        live = [t for t in snapshot['tabs'] if t['state'] != 'closed']
        obs = {k: deepcopy(previous[k]) for k in ('goal', 'goal_object') if k in previous}
        obs.update(url=page.url, chat_messages=deepcopy(h.env.chat.messages),
            last_action=h.env.last_action, last_action_error=h.env.last_action_error,
            open_pages_urls=tuple(t['url'] for t in live),
            open_pages_titles=tuple(t['title'] for t in live),
            active_page_index=[next(i for i, t in enumerate(live) if t['tab_id'] == h.active)],
            human_tabs={'active_tab_id':h.active, 'revision':snapshot['revision'], 'tabs':deepcopy(live),
                'recent_transitions':deepcopy(h.notices),
                'scope':'Stable custody; titles/URLs are last captured display metadata.'},
            human_tab_capture={'tab_id':h.active, 'document':identity['document'], 'attempts':1},
            axtree_object={'nodes':nodes}, dom_object=None, screenshot=None,
            extra_element_properties={}, focused_element_bid=None,
            observation_capture={'version':'dynamic-main-preview-v2' if self.preview_bids else 'dynamic-main-preview-v1', 'coverage':'partial',
                'child_documents':'not_captured', 'dom_snapshot':'not_captured', 'geometry':'not_captured',
                'screenshots':'not_captured', 'shallow_depth':self.depth, 'node_limit':self.max_nodes,
                'preview_nodes_omitted':omitted, 'preview_bids':self.preview_bids,
                'bid_scope':'visible main-document preview elements; full-capture identity agreement required' if self.preview_bids else 'none; use full-tree query results for targets'})
        self.pending = {'identity':identity, 'semantics':[semantics(n) for n in nodes],
                        'bids':[(n['backendDOMNodeId'],n['role']['value'],n['browsergym_id']) for n in nodes if n.get('browsergym_id') is not None]}
        self.trace.event('dynamic_preview_completed',seconds=time.monotonic()-start,
            nodes=len(nodes),omitted=omitted,identity=identity,owner_thread=self.owner,
            bid_assignment_seconds=bid_seconds,preview_bids=len(bids),
            scope='Partial main-document orientation; not a full AX snapshot or task verdict')
        return obs

    def deferred_observation(self):
        """Acknowledge execution without claiming a new AX/DOM snapshot.

        Only used after the final browser call in an opted-in batch. The next
        decision captures its preview AFTER pacing/human input, never reuses this
        empty tree as a full observation. Native task validation still ran.
        """
        h=self.human;h.prepare()
        if h.states()[h.active]['state']!='agent_controlled':return h.capture()
        identity=self.identity()
        snapshot=h.controller.snapshot();live=[t for t in snapshot['tabs'] if t['state']!='closed']
        obs=deepcopy(self.previous_metadata)
        obs.update(url=h.env.page.url,chat_messages=deepcopy(h.env.chat.messages),
            last_action=h.env.last_action,last_action_error=h.env.last_action_error,
            open_pages_urls=tuple(t['url'] for t in live),open_pages_titles=tuple(t['title'] for t in live),
            active_page_index=[next(i for i,t in enumerate(live) if t['tab_id']==h.active)],
            human_tabs={'active_tab_id':h.active,'revision':snapshot['revision'],'tabs':deepcopy(live),
                        'recent_transitions':deepcopy(h.notices)},
            human_tab_capture={'tab_id':h.active,'document':identity['document'],'attempts':0},
            axtree_object={'nodes':[]},dom_object=None,screenshot=None,extra_element_properties={},focused_element_bid=None,
            observation_capture={'version':'deferred-post-action-v1','coverage':'partial',
                'deferred':True,'scope':'Execution metadata only; AX/DOM not observed. Fresh preview follows pacing before next request.'})
        self.trace.event('post_action_capture_deferred',action=h.env.last_action,
            action_error=h.env.last_action_error,identity=identity,scope=obs['observation_capture']['scope'])
        return obs

    def capture(self):
        if self.identity() != self.pending['identity']:
            raise ObservationChanged('Document/custody changed before background capture')
        self.full = self.human.capture()
        artifact = self.trace.observation(self.serial, self.full,
            'Full background observation; not itself delivered to policy.', phase='background')
        self.serial += 1
        return artifact

    def validate(self):
        if self.identity() != self.pending['identity']:
            raise ObservationChanged('Document/custody changed during inference or background capture')
        if self.full is None: raise ObservationChanged('No full background observation')
        if self.full['human_tab_capture']['document'] != self.pending['identity']['document']:
            raise ObservationChanged('Background capture changed document')
        indexed = main_nodes(self.full['axtree_object'], self.pending['identity']['document']['frame_id'])
        # Only elements the decision acts on must still match. Other preview nodes may change
        # on live-content pages (carousels, tickers); recording them instead of rejecting the
        # whole decision lets the runner check just the targeted BIDs (HARNESS_STRICT_PREVIEW=1
        # restores the old all-or-nothing rejection).
        strict = os.environ.get('HARNESS_STRICT_PREVIEW') == '1'
        bid_of = {(b, r): bid for b, r, bid in self.pending.get('bids', [])}
        self.changed_bids = set(); changed_nodes = 0
        for node in self.pending['semantics']:
            candidates = indexed.get((node['backend_node_id'], node['role']), [])
            if not any(node == semantics(n) for n in candidates):
                if strict: raise ObservationChanged('Delivered preview disagrees with full capture')
                changed_nodes += 1
                bid = bid_of.get((node['backend_node_id'], node['role']))
                if bid is not None: self.changed_bids.add(bid)

        for backend,role,bid in self.pending.get('bids',[]):
            candidates=indexed.get((backend,role),[])
            if not candidates or any(n.get('browsergym_id')!=bid for n in candidates):
                if strict: raise ObservationChanged('Preview BID no longer names the same full-capture element')
                self.changed_bids.add(bid); continue
            # A duplicate in the merged tree must never authorize ambiguous lookup.
            owners={n.get('backendDOMNodeId') for n in self.full['axtree_object']['nodes'] if n.get('browsergym_id')==bid}
            if owners!={backend}:
                if strict: raise ObservationChanged('Preview BID became ambiguous')
                self.changed_bids.add(bid)
        if (changed_nodes or self.changed_bids) and getattr(self, 'trace', None) is not None:
            self.trace.event('dynamic_preview_partially_stale', changed_nodes=changed_nodes,
                             changed_bids=sorted(self.changed_bids),
                             scope='Decisions targeting these BIDs are not executed; other actions proceed')
