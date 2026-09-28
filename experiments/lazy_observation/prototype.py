"""Experimental Chromium AX reader; never used by the production harness.

Main-frame only, explicit coverage, no private website state. Unknown structures
fail closed. Global search deliberately retains a full-AX fallback.
"""
from copy import deepcopy
import json
import time
from uuid import uuid4


class StaleTarget(ValueError):
    pass


class UnsupportedStructure(ValueError):
    pass


def semantic(node):
    return {'role': node.get('role', {}).get('value', ''),
            'name': node.get('name', {}).get('value', ''),
            'value': node.get('value', {}).get('value', ''),
            'properties': {p['name']: p.get('value', {}).get('value')
                           for p in node.get('properties', [])
                           if p['name'] not in ('focused',)}}


class LazyAX:
    def __init__(self, page, *, events=None):
        self.page, self.events = page, events
        self.cdp = page.context.new_cdp_session(page)
        self.calls = []
        self.generation = 0
        self.root_key = None
        self.nodes = {}
        self.requested = {}
        self.tokens = {}
        self.updated = set()
        self.attribute = 'data-lazy-probe-' + uuid4().hex
        self.send('Accessibility.enable')
        self.cdp.on('Accessibility.nodesUpdated', self._updated)

    def send(self, method, params=None):
        start = time.perf_counter()
        result = self.cdp.send(method, params or {})
        self.calls.append({'method':method, 'seconds':time.perf_counter()-start,
                           'response_json_bytes':len(json.dumps(result).encode()),
                           'returned_nodes':len(result.get('nodes', []))})
        return result

    def _updated(self, event):
        # Events are hints, not a complete change detector or delivery guarantee.
        for node in event.get('nodes', []):
            self.updated.add(node['nodeId'])

    def check(self):
        if len(self.page.frames) != 1:
            raise UnsupportedStructure('Multiple frames require full-capture fallback; never silently omit them')
        root = self.send('Accessibility.getRootAXNode')['node']
        key = (root['nodeId'], root.get('backendDOMNodeId'), root.get('frameId'), self.page.url)
        if key != self.root_key:
            self.generation += 1
            self.root_key = key
            self.nodes.clear(); self.requested.clear(); self.tokens.clear(); self.updated.clear()
        self.nodes[root['nodeId']] = root
        return root

    def _store(self, nodes):
        for node in nodes:
            self.nodes[node['nodeId']] = node

    def ref(self, node):
        return f"d{self.generation}:{node['nodeId']}"

    def _resolve(self, ref):
        if not isinstance(ref, str) or not ref.startswith(f'd{self.generation}:'):
            raise StaleTarget('Reference belongs to another document')
        node = self.nodes.get(ref.split(':',1)[1])
        if node is None: raise StaleTarget('Node was not loaded or has been removed')
        return node

    def describe(self, node):
        return {'ref':self.ref(node), **semantic(node),
                'ignored':node.get('ignored', False),
                'parent_ref':f"d{self.generation}:{node['parentId']}" if node.get('parentId') else None,
                'child_count':len(node.get('childIds', [])),
                'unloaded_children':sum(x not in self.nodes for x in node.get('childIds', []))}

    def overview(self, *, depth=1, limit=48):
        self.check()
        nodes = self.send('Accessibility.getFullAXTree', {'depth':depth})['nodes']
        self._store(nodes)
        visible = [n for n in nodes if not n.get('ignored')]
        return {'items':[self.describe(n) for n in visible[:limit]],
                'coverage':'depth_limited', 'fetched_nodes':len(nodes),
                'returned_items':min(len(visible),limit),
                'omitted_loaded_items':max(0,len(visible)-limit),
                'complete_document':False}

    def inspect(self, ref, *, relatives=False):
        self.check(); old = self._resolve(ref)
        if not old.get('backendDOMNodeId'):
            raise UnsupportedStructure('No DOM backing for targeted inspection')
        nodes = self.send('Accessibility.getPartialAXTree',
            {'backendNodeId':old['backendDOMNodeId'], 'fetchRelatives':relatives})['nodes']
        current = next((n for n in nodes if n.get('backendDOMNodeId') == old['backendDOMNodeId']), None)
        if current is None or current.get('ignored'):
            raise StaleTarget('Node is detached or no longer accessible')
        self._store(nodes)
        return self.describe(current)

    def children(self, ref, *, offset=0, limit=20):
        self.check(); old = self._resolve(ref)
        nodes = self.send('Accessibility.getChildAXNodes', {'id':old['nodeId']})['nodes']
        self._store(nodes)
        # Preserve native hierarchy, including explicitly marked ignored nodes.
        # CDP itself has no offset/limit; pagination here bounds presentation only.
        direct = [n for n in nodes if n.get('parentId') == old['nodeId']]
        return {'items':[self.describe(n) for n in direct[offset:offset+limit]],
                'coverage':'immediate_children', 'fetched_nodes':len(nodes),
                'total_immediate_children':len(direct),
                'next_offset':offset+limit if offset+limit<len(direct) else None}

    def search(self, terms, *, scope=None, role=None, match='any', limit=5):
        self.check()
        root_id = self._resolve(scope)['nodeId'] if scope else None
        # A deliberate correctness-preserving fallback, not a misleading cheap
        # search of only loaded nodes. All names/values/properties remain searchable.
        nodes = self.send('Accessibility.getFullAXTree')['nodes']
        self._store(nodes)
        by_id = {n['nodeId']:n for n in nodes}
        allowed = set(by_id)
        if root_id:
            if root_id not in by_id: raise StaleTarget('Search root disappeared')
            allowed = set(); pending = [root_id]
            while pending:
                n = pending.pop()
                if n in allowed: continue
                allowed.add(n); pending.extend(by_id.get(n, {}).get('childIds', []))
        if isinstance(terms,str):terms=[terms]
        found=[]
        for node in nodes:
            if node['nodeId'] not in allowed or node.get('ignored'): continue
            item=semantic(node)
            hay=' '.join((str(item['role']),str(item['name']),str(item['value']),json.dumps(item['properties'],sort_keys=True))).casefold()
            matches=[term.casefold() in hay for term in terms]
            if role and str(item['role']).casefold()!=role.casefold():continue
            if terms and not (all(matches) if match=='all' else any(matches)):continue
            found.append(node)
        return {'items':[self.describe(n) for n in found[:limit]], 'total_matches':len(found),
                'complete_document_search':True, 'strategy':'full_ax_fallback',
                'scope':scope,'omitted_matches':max(0,len(found)-limit)}

    def prepare_target(self, ref):
        self.check(); node = self._resolve(ref)
        nodes=self.send('Accessibility.getAXNodeAndAncestors',
            {'backendNodeId':node['backendDOMNodeId']})['nodes']
        current=next((n for n in nodes if n.get('backendDOMNodeId')==node['backendDOMNodeId']),None)
        if current is None or current.get('ignored'):raise StaleTarget('Target unavailable')
        by_id={n['nodeId']:n for n in nodes}; chain=[];n=current
        while n is not None:
            chain.append((n.get('backendDOMNodeId'),semantic(n)))
            n=by_id.get(n.get('parentId'))
        self._store(nodes)
        token={'generation':self.generation,'backend':current['backendDOMNodeId'],'chain':chain,'ref':self.ref(current)}
        # Return a private opaque token; do not accept caller-supplied signatures.
        key=uuid4().hex;self.tokens[key]=deepcopy(token)
        return key

    def act(self, token, *, operation='click', text=None, timeout=1000):
        old=self.tokens.pop(token)
        self.check()
        if old['generation']!=self.generation:raise StaleTarget('Document changed before action')
        fresh_token=self.prepare_target(old['ref']);fresh=self.tokens.pop(fresh_token)
        if old['chain']!=fresh['chain']:raise StaleTarget('Target or ancestor semantics changed before action')
        obj=self.send('DOM.resolveNode',{'backendNodeId':old['backend']})['object']['objectId']
        key=uuid4().hex
        try:
            self.send('Runtime.callFunctionOn',{'objectId':obj,
                'functionDeclaration':'function(attr,value){this.setAttribute(attr,value)}',
                'arguments':[{'value':self.attribute},{'value':key}]})
        finally:self.send('Runtime.releaseObject',{'objectId':obj})
        locator=self.page.locator(f'[{self.attribute}="{key}"]')
        try:
            if operation=='click':locator.click(timeout=timeout)
            elif operation=='fill':locator.fill(text,timeout=timeout)
            else:raise ValueError('Unsupported experimental action')
        finally:
            # No replay, forced click or automatic action repair on failure.
            if locator.count():locator.evaluate('(el,attr)=>el.removeAttribute(attr)',self.attribute)
        return {'executed':True,'task_success':None}

    def geometry(self, ref):
        self.check();node=self._resolve(ref)
        return self.send('DOM.getBoxModel',{'backendNodeId':node['backendDOMNodeId']})

    def watch(self, ref):
        value=self.inspect(ref)
        self.requested[ref]=value
        return value

    def poll(self):
        self.check();changes=[]
        # Explicitly recheck requested nodes: events alone are not sufficient.
        # This is O(watched nodes) CDP requests; broad watches are not optimized.
        for ref,old in list(self.requested.items()):
            try:
                value=self.inspect(ref)
            except Exception as error:
                changes.append({'ref':ref,'unavailable':True,'error':type(error).__name__})
                self.requested.pop(ref,None);continue
            if value!=old:changes.append(value)
            self.requested[ref]=value
        hints=len(self.updated);self.updated.clear()
        events=self.events.drain() if self.events else None
        return {'changes':changes,'coverage':'explicitly_watched_nodes_only',
                'unloaded_regions_may_have_changed':True,'update_hints':hints,'events':events}

    def close(self):
        self.cdp.detach()
