"""Snapshot-bound accessibility search/traversal, with local tokenizer budgets.

Only BrowserGym's public captured AX tree is indexed. No DOM queries, task goal,
private grader state, browser actions or inference occur during a query.
"""
from collections import deque, OrderedDict
from dataclasses import dataclass
import hashlib
import json
import re
import sys
from pathlib import Path
from .shared_tokenizer import SharedTokenizerError

AX_TOOLS = ('ax_search', 'ax_read')


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


@dataclass(frozen=True)
class AXConfig:
    tokenizer_path: str
    overview_tokens: int = 2000
    result_tokens: int = 1500
    incremental: bool = False
    verbose: bool = False
    repeat: bool = False
    revisit_reuse: bool = False
    agent_overview: bool = False
    shared_tokenizer: object = None

    def __post_init__(self):
        if self.shared_tokenizer is not None:
            from .shared_tokenizer import SharedTokenizerConfig
            if not isinstance(self.shared_tokenizer, SharedTokenizerConfig):
                raise ValueError('AX shared tokenizer requires SharedTokenizerConfig')
        for value in (self.incremental, self.verbose, self.repeat, self.revisit_reuse, self.agent_overview):
            if type(value) is not bool: raise ValueError('AX presentation controls must be boolean')
        if (self.revisit_reuse or self.agent_overview) and not self.incremental:
            raise ValueError('AX reuse and agent overview require incremental presentation')
        for value in (self.overview_tokens, self.result_tokens):
            if type(value) is not int or not 512 <= value <= 8192:
                raise ValueError('AX token budgets must be integers between 512 and 8192')
        if not Path(self.tokenizer_path).is_file():
            raise ValueError('AX requires an existing local tokenizer.json; no automatic download')

    def describe(self):
        return {**({'tokenizer_service': self.shared_tokenizer.describe()} if self.shared_tokenizer is not None else {}),
                **({'revisit_reuse':'exact-public-tree-v1', 'revisit_cache_entries':64} if self.revisit_reuse else {}),
                **({'agent_overview_tokens':[0,512,1000,2000,4000],
                    'overview_control':'one next automatic observation; last executed browser call wins'} if self.agent_overview else {}),
                'version': 'incremental-ax-v1' if self.incremental else 'progressive-ax-v1', 'overview_tokens': self.overview_tokens,
                'result_tokens': self.result_tokens, 'tokenizer_path': self.tokenizer_path,
                'tokenizer_sha256': hashlib.sha256(Path(self.tokenizer_path).read_bytes()).hexdigest(),
                'scope': 'Token counts cover selected AX text/tool JSON, not complete model requests',
                'search_defaults': {'limit': 5, 'context': 0}, 'snapshot_references': True,
                **({'context_controls': {'verbose':self.verbose,'repeat':self.repeat},
                    'delivery_tracking':'acknowledged policy spans; pending results co-delivered with next update',
                    'node_radius':{'default':0,'maximum':8,'adjacency':'parent, children, same-parent siblings','ordering':'focus then breadth-first rings'}} if self.incremental else {})}


class AXExplorer:
    def __init__(self, config):
        from .shared_tokenizer import load_tokenizer
        self.config = config
        self.tokenizer = load_tokenizer(config.tokenizer_path, shared=config.shared_tokenizer)
        self.nodes = []
        self.snapshot = None
        self._raw_digest = None
        self._token_cache = {}
        self._clip_cache = OrderedDict()
        self._clip_cache_bytes = 0

    def tokens(self, text):
        from .shared_tokenizer import count_text
        return count_text(self.tokenizer, text)

    def _clip(self, text, cap):
        # Clip label previews, never the indexed/searchable source text.
        cached = self._clip_cache.get((str(text), cap))
        if cached is not None:
            self._clip_cache.move_to_end((str(text), cap))
            return cached[0]
        ids = self.tokenizer.encode(str(text), add_special_tokens=False).ids
        if len(ids) <= cap: return str(text), False
        return self.tokenizer.decode(ids[:cap], skip_special_tokens=False) + '…', True

    def _prime_clips(self, pairs):
        """Small episode-owned batches, bounded cached previews (not full IDs)."""
        if self.config.shared_tokenizer is None:
            return
        pairs = list(dict.fromkeys((str(t), cap) for t, cap in pairs
                                   if len(str(t).encode('utf-8')) <= 8192))
        pairs = [p for p in pairs if p not in self._clip_cache]
        for start in range(0, len(pairs), 128):
            selected = pairs[start:start+128]
            texts = list(dict.fromkeys(t for t, _ in selected))
            encodings = self.tokenizer.encode_batch(texts, add_special_tokens=False)
            by_text = dict(zip(texts, (e.ids for e in encodings)))
            partial = [(t, cap) for t, cap in selected if len(by_text[t]) > cap]
            decoded = self.tokenizer.decode_batch([by_text[t][:cap] for t, cap in partial],
                                                 skip_special_tokens=False) if partial else []
            shortened = dict(zip(partial, decoded))
            for text, cap in selected:
                clipped = (text, cap) in shortened
                result = ((shortened[(text, cap)]+'…') if clipped else text, clipped)
                cost = sys.getsizeof(text)+sys.getsizeof(result[0])+256
                if cost > 1024*1024:
                    continue
                self._clip_cache[(text, cap)] = (result, cost)
                self._clip_cache_bytes += cost
                while len(self._clip_cache) > 512 or self._clip_cache_bytes > 1024*1024:
                    _, (_, previous_cost) = self._clip_cache.popitem(last=False)
                    self._clip_cache_bytes -= previous_cost

    def _prime_nodes(self, indices):
        if self.config.shared_tokenizer is None:
            return
        for start in range(0, len(indices), 16):
            pairs = []
            for index in indices[start:start+16]:
                n = self.nodes[index]
                pairs.extend((n['name'], cap) for cap in (16, 24, 40, 60))
                pairs.extend((n['value'], cap) for cap in (24, 40, 60))
                pairs.extend((str(v), 24) for v in list(n['properties'].values())[:8]
                             if not isinstance(v, (bool, int, float)) and v is not None)
            self._prime_clips(pairs)

    def _batch_candidate_counts(self, texts):
        if self.config.shared_tokenizer is not None:
            return self.tokenizer.count_batch(texts)
        return [self.tokens(t) for t in texts]

    def _packed_candidates(self, result, items, offset):
        """Preserve sequential prefix decisions; amortize up to 16 counts/RPC."""
        width = 16 if self.config.shared_tokenizer is not None else 1
        for start in range(0, len(items), width):
            candidates = []
            scratch = result
            for item in items[start:start+width]:
                scratch = {**scratch, 'items': scratch['items']+[item],
                           'next_offset': offset+len(scratch['items'])+1}
                candidates.append(scratch)
            try:
                counts = self._batch_candidate_counts([encoded(c) for c in candidates])
            except SharedTokenizerError as error:
                if error.code != 'bound' or len(candidates) == 1:
                    raise
                # Speculation must not reject a locally valid truncated prefix.
                # Count individually, lazily: callers stop before later oversized
                # candidates. This is a pure tokenizer operation, never action retry.
                for candidate in candidates:
                    yield candidate, self.tokens(encoded(candidate))
                    result = candidate
                continue
            for candidate, count in zip(candidates, counts):
                yield candidate, count
                result = candidate

    def capture(self, observation):
        tree = observation['axtree_object']
        identity = encoded({'url': observation['url'], 'tree': tree,
                            'page': list(observation.get('open_pages_urls', []))})
        raw_digest = hashlib.sha256(identity.encode()).hexdigest()
        if raw_digest == self._raw_digest: return
        self._raw_digest = raw_digest
        self.url = observation['url']
        self.nodes = []
        raw = tree.get('nodes', [])
        self.raw_count = len(raw)
        by_id = {n['nodeId']: n for n in raw}
        self.roots = []
        visited = set()
        stack = [(n['nodeId'], None) for n in reversed(raw)]
        while stack:
            raw_id, parent = stack.pop()
            if raw_id in visited or raw_id not in by_id: continue
            visited.add(raw_id)
            node = by_id[raw_id]
            role = str(node.get('role', {}).get('value', ''))
            name = str(node.get('name', {}).get('value', ''))
            value = str(node.get('value', {}).get('value', ''))
            props = {p['name']: p['value']['value'] for p in node.get('properties', [])
                     if isinstance(p.get('value'), dict) and 'value' in p['value']
                     and p.get('name') not in ('focusable', 'settable', 'editable')}
            useful = (not node.get('ignored', False) and role not in ('none', 'LineBreak', 'InlineTextBox')
                      and not (role == 'generic' and not name and not value and not props))
            # Same redundant-text reduction as the existing flat renderer; the
            # text remains searchable through the named semantic ancestor.
            if role == 'StaticText' and parent is not None and name and name in self.nodes[parent]['name']:
                useful = False
            if useful:
                index = len(self.nodes)
                current = {'index': index, 'role': role, 'name': name, 'value': value,
                           'properties': props, 'bid': node.get('browsergym_id'),
                           'parent': parent, 'children': [], 'raw_node_id': raw_id,
                           'backend_identity': node.get('backendDOMNodeId'), 'frame_identity': node.get('frameId')}
                current['source_text'] = ' '.join((role, name, value, encoded(props)))
                current['search_text'] = current['source_text'].casefold()
                self.nodes.append(current)
                if parent is None: self.roots.append(index)
                else: self.nodes[parent]['children'].append(index)
                parent = index
            stack.extend((child, parent) for child in reversed(node.get('childIds', [])))
        self.unreachable_raw_nodes = len(raw) - len(visited)
        self.positions = {n['index']: i for i, n in enumerate(self.nodes)}
        # Chromium/BrowserGym can regenerate synthetic negative text-node IDs
        # on a read alone. Bind refs to semantic topology plus real DOM identity,
        # not this transport churn. Replaced real controls still invalidate refs.
        semantic = [{k:v for k,v in n.items() if k not in ('raw_node_id','search_text','source_text')}
                    for n in self.nodes]
        snapshot = hashlib.sha256(encoded({'url': self.url, 'nodes': semantic,
            'pages': list(observation.get('open_pages_urls', []))}).encode()).hexdigest()[:16]
        if snapshot != self.snapshot: self._token_cache = {}
        self.snapshot = snapshot

    def ref(self, index): return f'ax:{self.snapshot}:{index}'

    def resolve(self, ref):
        pieces = ref.split(':')
        if len(pieces) != 3 or pieces[0] != 'ax' or pieces[1] != self.snapshot:
            raise ValueError('Stale or invalid AX reference; use references from the current snapshot')
        if not pieces[2].isdigit() or int(pieces[2]) >= len(self.nodes):
            raise ValueError('Unknown AX node reference')
        return int(pieces[2])

    def brief(self, index, cap=40):
        n = self.nodes[index]
        name, clipped = self._clip(n['name'], cap)
        value, value_clipped = self._clip(n['value'], cap)
        return {'ref': self.ref(index), 'parent_ref': self.ref(n['parent']) if n['parent'] is not None else None,
                'bid': n['bid'], 'role': n['role'], 'name': name,
                **({'value': value} if value else {}),
                **({'properties': {k:v if isinstance(v,(bool,int,float)) or v is None else self._clip(str(v),24)[0]
                                   for k,v in list(n['properties'].items())[:8]},
                    'properties_omitted': max(0,len(n['properties'])-8)} if n['properties'] else {}),
                'children': len(n['children']), 'text_truncated': clipped or value_clipped}

    def location(self, index):
        chain = []; parent = self.nodes[index]['parent']
        while parent is not None:
            n = self.nodes[parent]
            chain.append({'ref': self.ref(parent), 'role': n['role'], 'name': self._clip(n['name'], 16)[0]})
            parent = n['parent']
        return {'ancestors': list(reversed(chain[:3])), 'earlier_ancestors_omitted': max(0, len(chain)-3),
                'sibling_index': (self.nodes[self.nodes[index]['parent']]['children'].index(index)
                                  if self.nodes[index]['parent'] is not None else self.roots.index(index))}

    def _line(self, index, preview=True):
        n = self.nodes[index]
        text = f"{n['role']} {n['name']!r}"
        if n['value']: text += ' value=' + repr(n['value'])
        if n['properties']: text += ' ' + encoded(n['properties'])
        if preview:
            text, clipped = self._clip(text, 60)
            if clipped: text += ' [text shortened; ax_read view=node for more]'
        bid = f" [{n['bid']}]" if n['bid'] is not None else ''
        parent = f" parent={self.ref(n['parent'])}" if n['parent'] is not None else ''
        return f'{self.ref(index)}{bid} {text} children={len(n["children"])}{parent}'

    def overview(self, observation):
        self.capture(observation)
        prefix = (f'URL: {self._clip(observation["url"],80)[0]}\nLast action error: {self._clip(observation.get("last_action_error", ""),60)[0]}\n'
                  f'AX snapshot {self.snapshot}; semantic nodes={len(self.nodes)}; raw nodes={self.raw_count}.\n'
                  'AX refs are for ax_read; bracketed BIDs are for browser actions (pass 152, not [152]).\n')
        suffix = '\nUse ax_search for literal text/role matches; ax_read for children, subtree, ancestors, neighborhood or full node text.'
        full = [self._line(i, preview=False) for i in range(len(self.nodes))]
        whole = prefix + 'Complete semantic tree:\n' + '\n'.join(full) + suffix
        if self.tokens(whole) <= self.config.overview_tokens:
            self.last_overview = {'snapshot': self.snapshot, 'shown': len(self.nodes), 'total': len(self.nodes),
                                  'tokens': self.tokens(whole), 'complete': True}
            return whole
        queue = deque(self.roots)
        selected = []
        while queue:
            i = queue.popleft()
            line = self._line(i)
            candidate = prefix + f'Structural overview; shown={len(selected)+1}/{len(self.nodes)} (others collapsed):\n' + '\n'.join(selected+[line]) + suffix
            if self.tokens(candidate) > self.config.overview_tokens: break
            selected.append(line)
            queue.extend(self.nodes[i]['children'])
        text = prefix + f'Structural overview; shown={len(selected)}/{len(self.nodes)} (others collapsed):\n' + '\n'.join(selected) + suffix
        if self.tokens(text) > self.config.overview_tokens:
            raise ValueError('AX overview envelope exceeds configured token budget')
        self.last_overview = {'snapshot': self.snapshot, 'shown': len(selected), 'total': len(self.nodes),
                              'tokens': self.tokens(text), 'complete': False}
        return text

    def _envelope(self, tool):
        return {'tool': tool, 'snapshot': self.snapshot,
                'scope': 'Captured public accessibility tree, not live DOM or verified task state.',
                'root_refs': [self.ref(i) for i in self.roots[:8]],
                'root_refs_omitted': max(0,len(self.roots)-8),
                'indexed_nodes': len(self.nodes), 'raw_nodes': self.raw_count,
                'unreachable_raw_nodes': self.unreachable_raw_nodes}

    def _fit(self, output, items, offset, total):
        output.update(items=[], offset=offset, total_entries=total, next_offset=offset,
                      result_tokens_limit=self.config.result_tokens)
        for candidate, count in self._packed_candidates(output, items, offset):
            if count > self.config.result_tokens-64: break
            output = candidate
        output['next_offset'] = offset+len(output['items']) if offset+len(output['items']) < total else None
        output['budget_limited'] = len(output['items']) < len(items)
        if items and not output['items']:
            output['error'] = 'Requested entry/context exceeds result budget; reduce context/limit or ax_read the node directly.'
        if self.tokens(encoded(output)) > self.config.result_tokens:
            raise ValueError('AX result envelope exceeds token budget')
        return output

    def search(self, query, role=None, limit=5, context=0, offset=0, scope_ref=None):
        if not query.strip() and not role: raise ValueError('Provide nonempty query or role')
        needle = query.casefold()
        scope = None
        if scope_ref is not None:
            root = self.resolve(scope_ref); scope = set(); todo = [root]
            while todo:
                i = todo.pop(); scope.add(i); todo.extend(self.nodes[i]['children'])
        matches = [n['index'] for n in self.nodes if (scope is None or n['index'] in scope)
                   and (not role or n['role'].casefold() == role.casefold())
                   and needle in n['search_text']]
        items = []
        selected_indices = matches[offset:offset+limit]
        to_prime = set(selected_indices)
        for index in selected_indices:
            parent = self.nodes[index]['parent']
            for _ in range(3):
                if parent is None: break
                to_prime.add(parent);parent = self.nodes[parent]['parent']
            to_prime.update(range(max(0,index-context),min(len(self.nodes),index+context+1)))
        self._prime_nodes(sorted(to_prime))
        for index in matches[offset:offset+limit]:
            entry = self.brief(index)
            entry['location'] = self.location(index)
            n = self.nodes[index]
            # Show a match even when it is deep inside a very long text node.
            position = n['search_text'].find(needle)
            match = re.search(re.escape(query), n['source_text'], re.IGNORECASE)
            if match:
                entry['match_excerpt'] = n['source_text'][max(0,match.start()-48):match.end()+96]
            else:
                entry['normalized_match_excerpt'] = n['search_text'][max(0, position-48):position+len(needle)+96]
            if entry['text_truncated'] and query:
                full_line = self._line(index, preview=False)
                text_match = re.search(re.escape(query), full_line, re.IGNORECASE)
                if text_match:
                    entry['suggested_text_offset'] = max(0,self.tokens(full_line[:text_match.start()])-8)
            if context:
                entry['neighbors'] = [self.brief(i, 24) for i in range(max(0,index-context), min(len(self.nodes),index+context+1))
                                      if i != index and (scope is None or i in scope)]
            items.append(entry)
        return self._fit({**self._envelope('ax_search'), 'query': query, 'role': role,
                          'context_nodes_each_side': context, 'scope_ref': scope_ref}, items, offset, len(matches))

    def read(self, node_ref, view='children', depth=1, limit=20, offset=0, context=2, text_offset=0):
        index = self.resolve(node_ref)
        n = self.nodes[index]
        output = {**self._envelope('ax_read'), 'node': self.brief(index), 'view': view}
        if view == 'node':
            if index not in self._token_cache:
                self._token_cache[index] = self.tokenizer.encode(self._line(index, preview=False), add_special_tokens=False).ids
            ids = self._token_cache[index]
            available = max(1, self.config.result_tokens-self.tokens(encoded(output))-150)
            fragment = ids[text_offset:text_offset+available]
            output.update(text=self.tokenizer.decode(fragment, skip_special_tokens=False), text_offset=text_offset,
                          total_text_tokens=len(ids), next_text_offset=text_offset+len(fragment) if text_offset+len(fragment)<len(ids) else None)
            while self.tokens(encoded(output)) > self.config.result_tokens and fragment:
                fragment = fragment[:-32]
                output.update(text=self.tokenizer.decode(fragment, skip_special_tokens=False),
                              next_text_offset=text_offset+len(fragment))
            return output
        if view == 'children': indices = list(n['children'])
        elif view == 'ancestors':
            indices = []; parent = n['parent']
            while parent is not None:
                indices.append(parent); parent = self.nodes[parent]['parent']
        elif view == 'neighborhood':
            indices = list(range(max(0,index-context), min(len(self.nodes),index+context+1)))
        elif view == 'subtree':
            indices = []; todo = [(index,0)]
            while todo:
                i, level = todo.pop(); indices.append(i)
                if level < depth: todo.extend((child,level+1) for child in reversed(self.nodes[i]['children']))
        else: raise ValueError('Unsupported AX view')
        self._prime_nodes(indices[offset:offset+limit])
        return self._fit(output, [self.brief(i) for i in indices[offset:offset+limit]], offset, len(indices))

    def execute(self, name, arguments):
        try:
            return self.search(**arguments) if name == 'ax_search' else self.read(**arguments)
        except ValueError as exc:
            return {**self._envelope(name), 'error': str(exc), 'items': []}
