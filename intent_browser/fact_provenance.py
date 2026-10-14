"""Opt-in, private AX source/output provenance. Never changes policy text.

Website supplies already resolved, versioned source fields. This module maps
only exact formatting operations and retained-request acknowledgements; meanings,
task relevance, screenshots and unsupported accessible-name joins are not inferred.
"""
from collections import OrderedDict, defaultdict
from copy import deepcopy
import hashlib
import json
import re

from .trace import write_json

VERSION = 'ax-fact-provenance-v1'


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def object_digest(value):
    return digest(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'), allow_nan=False))


def u16(text):
    return len(text.encode('utf-16-le')) // 2


def slice16(text, start, end):
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= u16(text):
        raise ValueError('Invalid UTF-16 interval')
    return text.encode('utf-16-le')[2*start:2*end].decode('utf-16-le')


def json_string_boundaries(text):
    """Decoded UTF16 boundary -> escaped UTF16 boundary (never split escapes)."""
    result = {0: 0}; plain = escaped = 0
    for char in text:
        plain += u16(char)
        escaped += u16(json.dumps(char, ensure_ascii=False)[1:-1])
        result[plain] = escaped
    return result


def json_layout(value):
    """Exact default JSON formatting, with structurally located string contents."""
    parts = []; length = 0; strings = {}
    def append(text):
        nonlocal length
        parts.append(text); length += u16(text)
    def emit(item, path):
        if isinstance(item, str):
            text = json.dumps(item, ensure_ascii=False)
            strings[path] = (length+1, length+u16(text)-1)
            append(text)
        elif isinstance(item, dict):
            append('{')
            for i, key in enumerate(sorted(item)):
                if i: append(', ')
                append(json.dumps(key, ensure_ascii=False)); append(': ')
                emit(item[key], path+(key,))
            append('}')
        elif isinstance(item, list):
            append('[')
            for i, child in enumerate(item):
                if i: append(', ')
                emit(child, path+(i,))
            append(']')
        else:
            append(json.dumps(item, ensure_ascii=False, allow_nan=False))
    emit(value, ())
    text = ''.join(parts)
    if text != encoded(value): raise ValueError('Unsupported JSON layout')
    return text, strings



class FactCaptureBoundary:
    """Instance-only native capture bracket. Never retries a browser operation."""
    def __init__(self,env,observer,trace):
        self.env,self.observer,self.trace=env,observer,trace
        self.had_override='_get_obs' in vars(env)
        self.original=env._get_obs
        self.pairs=OrderedDict()
        env._get_obs=self.capture

    def capture(self,*args,**kwargs):
        called=False;result=None;browser_error=None
        def operation():
            nonlocal called,result,browser_error
            if called:
                if browser_error is not None:raise browser_error
                return result
            called=True
            try:result=self.original(*args,**kwargs)
            except BaseException as exc:browser_error=exc;raise
            return result
        accepted=False
        try:
            observed=self.observer(operation)
            if not called or observed is not result:
                raise ValueError('Capture observer did not return the exact original observation')
            accepted=True
        except Exception as exc:
            if browser_error is not None:raise browser_error
            try:
                self.trace.event('fact_capture_unknown',error_type=type(exc).__name__,
                    scope='Native capture observer; no action or capture replay')
            except Exception:
                pass  # Private diagnostics must not suppress ordinary capture.
        # Even an observer failing before operation must leave ordinary capture intact.
        result=operation()
        self.pairs[id(result)]=(result,accepted)
        while len(self.pairs)>16:self.pairs.popitem(last=False)
        return result

    def confirmed(self,observation):
        entry=self.pairs.get(id(observation))
        return entry is not None and entry[0] is observation and entry[1]

    def close(self):
        if self.had_override:self.env._get_obs=self.original
        else:del self.env._get_obs
        self.pairs.clear()

class FactRecorder:
    """Episode-local observer; attach only when the trusted caller opts in.

    Current capture plus 64 output objects and 256 historical refs are cached.
    Full historical records live in private trace sidecars, not policy messages.
    """
    def __init__(self, trace, provider=None, capture_observer=None, *, pipeline_boundary=None):
        self.trace, self.provider = trace, provider
        self.capture_observer=capture_observer;self.boundary=None
        self.pipeline_boundary=pipeline_boundary
        # Decision outputs staged against a capture whose provenance arrives with
        # the background capture: (value, staged entry, registered sources).
        self.deferred=[]
        self.decision_capture=None
        self.env = None; self.step = 0
        self.current = None; self.capture_count = self.output_count = 0
        self.outputs = OrderedDict(); self.content_outputs = {}
        self.ack_refs = defaultdict(OrderedDict)
        self.retained_confirmed = set()
        self.originals = {}; self._preparing = False

    def describe(self):
        return {'enabled': True, 'version': VERSION, 'source_schema': 'ax-fact-sources-v1',
                'policy_context_added': False, 'extra_ax_captures': False,
                'coverage': 'Exact emitted AX name/value slices only; unsupported mappings unknown',
                'source_provider': self.provider is not None,
                'capture_boundary': ('native-full-v1' if self.capture_observer is not None else self.pipeline_boundary),
                **({'decision_outputs': 'staged against the decision AX read, re-bound to the validated background capture before acknowledgment'}
                   if self.pipeline_boundary else {}),
                'offset_unit':'utf16_code_units', 'output_cache_entries': 64,
                'historical_ref_cache_entries': 256}

    def observe(self, operation, *args, **kwargs):
        """Recording failures are private unknowns, never browser/tool failures."""
        try:
            return operation(*args, **kwargs)
        except Exception as exc:
            if operation == self.capture: self.current = None
            if operation == self.stage and len(args)>1: self.outputs.pop(id(args[1]), None)
            try:
                self.trace.event('fact_recording_unknown', step=self.step,
                                 operation=getattr(operation,'__name__',type(operation).__name__), error_type=type(exc).__name__)
            except Exception:
                pass
            return None

    def attach(self, explorer):
        """Wrap one AXContext instance, never global BrowserGym/Website methods."""
        self.explorer = explorer
        names = ('capture', 'page_update', 'prepare_observation', 'partial_overview', 'search', 'read')
        self.originals = {name: getattr(explorer, name) for name in names}
        def capture(observation):
            result = self.originals['capture'](observation)
            self.observe(self.capture, explorer, observation)
            return result
        def page_update(*args, **kwargs):
            result = self.originals['page_update'](*args, **kwargs)
            if not self._preparing: self.observe(self.stage, explorer, result)
            return result
        def partial_overview(observation, *args, **kwargs):
            result = self.originals['partial_overview'](observation, *args, **kwargs)
            preview = explorer._preview_explorer
            self.observe(self.capture, preview, observation)
            if not self._preparing: self.observe(self.stage, preview, result, preview=True)
            return result
        def prepare_observation(observation):
            self._preparing = True
            try: result = self.originals['prepare_observation'](observation)
            finally: self._preparing = False
            preview = observation.get('observation_capture', {}).get('coverage') == 'partial'
            self.observe(self.stage, explorer._preview_explorer if preview else explorer, result, preview=preview)
            return result
        def search(*args, **kwargs):
            result = self.originals['search'](*args, **kwargs)
            self.observe(self.stage, explorer, result, search=True)
            return result
        def read(*args, **kwargs):
            result = self.originals['read'](*args, **kwargs)
            self.observe(self.stage, explorer, result, node_page=True)
            return result
        for name, method in locals().copy().items():
            if name in names: setattr(explorer, name, method)

    def install_capture_boundary(self,env):
        if self.capture_observer is not None:
            self.boundary=FactCaptureBoundary(env,self.capture_observer,self.trace)

    def close(self):
        if self.boundary is not None:self.boundary.close()
        for name, original in self.originals.items(): setattr(self.explorer, name, original)
        self.originals.clear(); self.outputs.clear(); self.current = None

    def capture(self, explorer, observation):
        context = {'snapshot_id': explorer.snapshot, 'step': self.step,
                   'coverage': observation.get('observation_capture', {}).get('coverage', 'full')}
        diagnostics = []; supplied = None
        deferred = (self.pipeline_boundary is not None and
                    observation.get('observation_capture', {}).get('version') == 'budgeted-decision-v1')
        post_action = observation.get('observation_capture', {}).get('version') == 'deferred-post-action-v1'
        if deferred:
            # No DOM/probe work before inference: provenance comes from the
            # background capture of the same page revision.
            diagnostics.append({'reason': 'deferred_to_background_capture'})
            self.decision_capture = f'fact-capture-{self.capture_count:04d}'
        elif post_action:
            # Execution metadata only; the next decision/background capture
            # observes the resulting page. Nothing was captured to map.
            diagnostics.append({'reason': 'post_action_capture_deferred'})
        elif self.provider is not None:
            try:
                if self.boundary is not None and not self.boundary.confirmed(observation):
                    raise ValueError('Observation lacks its accepted original capture bracket')
                supplied = self.provider(self.env, observation, deepcopy(context))
                if len(encoded(supplied).encode('utf-8')) > 16*1024*1024:
                    raise ValueError('Oversized source export')
                if supplied['schema'] != 'ax-fact-sources-v1' or not isinstance(supplied['sources'], list) or len(supplied['sources']) > 4096:
                    raise ValueError('Unsupported source export')
            except Exception as exc:
                supplied = None; diagnostics.append({'reason': 'source_provider_rejected', 'error_type': type(exc).__name__})
        else: diagnostics.append({'reason': 'source_provider_unavailable'})
        raw_digest=object_digest(observation['axtree_object'])
        packet_digest=object_digest(supplied) if supplied is not None else None
        key = object_digest([context['snapshot_id'], raw_digest, packet_digest])
        if self.current is not None and self.current['key'] == key:
            return
        capture_id = f'fact-capture-{self.capture_count:04d}'; self.capture_count += 1
        raw = {}
        for n in observation['axtree_object'].get('nodes', []):
            ident = str(n['nodeId'])
            if ident in raw and raw[ident] != n: raise ValueError('Conflicting raw AX identity')
            raw[ident] = n
        parents = {}; ambiguous = set()
        for ident, node in raw.items():
            for child in node.get('childIds', []):
                child = str(child)
                if child in parents and parents[child] != ident: ambiguous.add(child)
                parents[child] = ident
        indexed = {str(n['raw_node_id']): n['index'] for n in explorer.nodes}
        def ancestors(ident):
            seen = set()
            while ident in raw:
                if ident in seen or ident in ambiguous: raise ValueError('Ambiguous raw ancestry')
                seen.add(ident); yield ident
                ident = parents.get(ident)
        def nearest(ident):
            return next((p for p in ancestors(ident) if p in indexed), None)
        sources = []; fields = defaultdict(lambda: defaultdict(list)); export_ids = set()
        for source in (supplied or {}).get('sources', []):
            try:
                source = deepcopy(source); sid = source['id']; binding = source['binding']; text = source['text']
                if not isinstance(sid, str) or not sid or sid in export_ids: raise ValueError('Duplicate source ID')
                export_ids.add(sid)
                if not isinstance(text, str) or digest(text) != source['sha256']: raise ValueError('Source hash mismatch')
                # Valid UTF16 text; reject orphan surrogates rather than guess offsets.
                u16(text)
                if binding['snapshot_id'] != explorer.snapshot or binding['field'] not in ('name', 'value'):
                    raise ValueError('Stale snapshot or unsupported field')
                if not all(isinstance(binding[k], str) and binding[k] for k in ('node_id', 'frame_id', 'document_id')):
                    raise ValueError('Missing scoped identity')
                node_id = binding['node_id']; node = raw[node_id]; field = binding['field']
                if node.get('ignored'): raise ValueError('Ignored raw AX source')
                frame = next((raw[p].get('frameId') for p in ancestors(node_id) if raw[p].get('frameId')), None)
                if frame != binding['frame_id'] or node.get(field, {}).get('value') != text:
                    raise ValueError('Frame or source field mismatch')
                target = nearest(node_id)
                if target is None: raise ValueError('No indexed projection')
                index = indexed[target]; rendered = explorer.nodes[index][field]; start = 0
                if target != node_id:
                    if field != 'name' or node.get('role', {}).get('value') != 'StaticText' or not text:
                        raise ValueError('Unsupported suppression join')
                    choices = [p for p, n in raw.items() if n.get('role', {}).get('value') == 'StaticText'
                               and n.get('name', {}).get('value') == text and nearest(p) == target]
                    evidence = [s for s in raw[target].get('name', {}).get('sources', [])
                                if s.get('type') == 'contents' and not s.get('superseded') and not s.get('invalid')
                                and s.get('value', {}).get('value') == rendered]
                    if rendered.count(text) != 1 or len(choices) != 1 or not evidence:
                        raise ValueError('Ambiguous/unsupported ancestor name provenance')
                    start = rendered.index(text)
                elif rendered != text: raise ValueError('Indexed field mismatch')
                allocated = capture_id + f'-source-{len(sources):04d}'
                source.update(id=allocated, export_id=sid, captured_step=self.step)
                sources.append(source)
                fields[explorer.ref(index)][field].append({'source': source, 'indexed_start': start,
                                                         'indexed_end': start+len(text)})
            except (KeyError, TypeError, ValueError, UnicodeError) as exc:
                diagnostics.append({'reason': 'unsupported_source_binding', 'source_id': source.get('id') if isinstance(source,dict) else None,
                                    'error_type': type(exc).__name__})
        artifact = capture_id + '.json'
        record = {'schema': VERSION, 'offset_unit':'utf16_code_units', 'id': capture_id, 'step': self.step, **context,
                  'raw_ax_sha256':raw_digest, 'provider_packet_sha256':packet_digest,
                  'sources': sources, 'diagnostics': diagnostics,
                  'private_context': deepcopy((supplied or {}).get('private_context', {})),
                  'mapping_inventory_complete': (supplied or {}).get('mapping_inventory_complete') is True and not diagnostics}
        write_json(self.trace.directory/artifact, record)
        self.current = {'key': key, 'artifact': artifact, 'fields': fields, 'snapshot': explorer.snapshot,
                        'diagnostics': diagnostics, 'deferred': deferred}
        self.trace.event('fact_capture_recorded', step=self.step, artifact=artifact)

    def stage(self, explorer, value, *, preview=False, search=False, node_page=False, artifact=None):
        """Freeze a generated output before later captures or batch execution."""
        projections = []; references = []; diagnostics = []
        body = json.loads(value) if isinstance(value, str) else value
        text = value if isinstance(value, str) else encoded(value)
        if len(text.encode('utf-8')) > 4*1024*1024: return None
        fields = self.current['fields'] if self.current is not None and self.current['snapshot']==explorer.snapshot else {}
        if self.current is not None and self.current['snapshot']!=explorer.snapshot:
            diagnostics.append({'reason':'source_capture_snapshot_mismatch'})

        def emit(ref, field, begin, end, path, output_begin=0, *, transform='identity', boundaries=None):
            # All bounds here are codepoints within the known indexed field.
            original = explorer.nodes[explorer.resolve(ref)][field]
            for entry in fields.get(ref, {}).get(field, []):
                a, b = max(begin, entry['indexed_start']), min(end, entry['indexed_end'])
                if a >= b: continue
                source = entry['source']
                source_a = u16(original[entry['indexed_start']:a]); source_b = u16(original[entry['indexed_start']:b])
                out_a = u16(original[begin:a]); out_b = u16(original[begin:b])
                if boundaries is not None: out_a, out_b = boundaries[out_a], boundaries[out_b]
                projections.append({'source_id':source['id'], 'source_sha256':source['sha256'],
                    'binding_sha256':object_digest(source['binding']), 'source_start':source_a, 'source_end':source_b,
                    'output_path':list(path), 'output_start':output_begin+out_a, 'output_end':output_begin+out_b,
                    'encoding':transform, 'ref':ref})

        def node(item, path, ref=None, preview_caps=None):
            ref = ref or item.get('ref')
            if ref is None: return
            try: n = explorer.nodes[explorer.resolve(ref)]
            except (KeyError, ValueError): return
            if item.get('unchanged') or item.get('reused_from'):
                references.append({'ref': ref, 'historical_ref':item.get('reused_from',ref)})
            for field in ('name','value'):
                shown = item.get(field)
                if not isinstance(shown,str) or not shown: continue
                if shown == n[field]: end = len(shown)
                elif preview_caps and explorer._clip(n[field],preview_caps[field])[0] == shown:
                    prefix = shown[:-1] if explorer._clip(n[field],preview_caps[field])[1] else shown
                    if not n[field].startswith(prefix): continue
                    end = len(prefix)
                elif item.get(field+'_partial') is True and shown.endswith('…') and n[field].startswith(shown[:-1]):
                    end = len(shown)-1
                else:
                    diagnostics.append({'reason':'unsupported_field_transform','ref':ref,'field':field});continue
                if end: emit(ref,field,0,end,path+(field,))
        def walk(item, path=()):
            if isinstance(item,dict):
                node(item,path)
                for key,child in item.items():walk(child,path+(key,))
            elif isinstance(item,list):
                for i,child in enumerate(item):walk(child,path+(i,))
        if preview:
            for i,item in enumerate(body.get('items',[])):
                node(item,('items',i),explorer.ref(i),{'name':40,'value':32})
        else:
            walk(body)
            if body.get('unchanged') and body.get('root'):
                references.append({'ref':body['root'],'historical_ref':body['root']})
            if body.get('visited_content_unchanged'):
                # A page-wide unchanged summary references only previously known
                # node descriptions. It never gives exposure to a fresh capture.
                references.extend({'ref':ref,'historical_ref':ref} for ref in explorer._known())

        if search:
            for i,item in enumerate(body.get('items',[])):
                ref = item.get('ref')
                try: n = explorer.nodes[explorer.resolve(ref)]
                except (KeyError,ValueError):continue
                excerpts = item.get('excerpts') or [{'term':body.get('query'), **{k:item[k] for k in ('match','normalized_match') if k in item}}]
                for j,ex in enumerate(excerpts):
                    if 'normalized_match' in ex:
                        diagnostics.append({'reason':'normalized_match_not_identity','ref':ref});continue
                    term = ex.get('term'); shown = ex.get('match')
                    if isinstance(term,str):term=term.strip()  # Same normalization as AXContext.search.
                    if not isinstance(term,str) or not isinstance(shown,str): continue
                    source = n['source_text']; hit = re.search(re.escape(term),source,re.IGNORECASE)
                    if not hit:continue
                    begin = max(0,hit.start()-48); selected = source[begin:hit.end()+96]
                    expected,partial = explorer._clip(selected,80)
                    plain = shown[:-1] if partial else shown
                    if shown != expected or not selected.startswith(plain):continue
                    path = ('items',i,'excerpts',j,'match') if item.get('excerpts') else ('items',i,'match')
                    cursor = len(n['role'])+1
                    for field in ('name','value'):
                        a,b = max(begin,cursor),min(begin+len(plain),cursor+len(n[field]))
                        if a<b:emit(ref,field,a-cursor,b-cursor,path,u16(source[begin:a]))
                        cursor += len(n[field])+1

        if node_page and isinstance(body.get('text'),str):
            ref = body['root']; n = explorer.nodes[explorer.resolve(ref)]
            verbose = bool(body.get('metadata'))
            full = explorer._project(ref,verbose);full.update(name=n['name'],value=n['value'])
            full.pop('name_partial',None);full.pop('value_partial',None)
            serialized, layout = json_layout(full)
            encoded_node = explorer.tokenizer.encode(serialized,add_special_tokens=False)
            start = body['text_offset']; end = body.get('next_text_offset') or len(encoded_node.ids)
            fragment = body['text']
            if start < end and end <= len(encoded_node.offsets):
                a,b = encoded_node.offsets[start][0],encoded_node.offsets[end-1][1]
                # Token byte fragments can decode to replacement characters: never relocate them.
                if fragment == serialized[a:b]:
                    page_a,page_b = u16(serialized[:a]),u16(serialized[:b])
                    for field in ('name','value'):
                        if not n[field]:continue
                        field_a,_ = layout[(field,)]; boundaries=json_string_boundaries(n[field])
                        # Complete escaped characters only. Prefix/suffix cuts inside an escape earn no credit.
                        eligible=[plain for plain,escaped in boundaries.items() if page_a <= field_a+escaped <= page_b]
                        if len(eligible)<2:continue
                        lo,hi=min(eligible),max(eligible)
                        prefix=slice16(n[field],0,lo) if lo else ''
                        piece=slice16(n[field],lo,hi)
                        emit(ref,field,len(prefix),len(prefix)+len(piece),('text',),field_a+boundaries[lo]-page_a,
                             transform='json_string',boundaries=json_string_boundaries(piece))
                else:diagnostics.append({'reason':'token_page_not_exact_character_slice','ref':ref})
        restaged = artifact is not None
        if artifact is None:
            artifact = f'fact-output-{self.output_count:04d}.json'; self.output_count += 1
        if restaged:diagnostics.append({'reason':'rebound_to_background_capture'})
        record={'schema':VERSION,'offset_unit':'utf16_code_units','id':artifact[:-5],'step':self.step,'text_sha256':digest(text),
                'capture':self.current['artifact'] if self.current else None,
                'projections':projections,'references':references,'diagnostics':diagnostics}
        write_json(self.trace.directory/artifact, record)
        entry={'record':record,'artifact':artifact,'text':text,'body':deepcopy(body),
               'stage_options':{'preview':preview,'search':search,'node_page':node_page}}
        self.outputs[id(value)]=(value,entry)
        self.outputs.move_to_end(id(value))
        while len(self.outputs)>64:self.outputs.popitem(last=False)
        if not restaged and self.current is not None and self.current.get('deferred'):
            self.deferred.append([value,entry,[],self.decision_capture])
        return record['id']

    def finish_decision(self, outcome):
        """Bind decision outputs only to a background capture of the same revision.

        Identical AX text is not proof of identical private provenance, so an
        invalidated decision or an unproven revision leaves mappings unknown.
        """
        # Only the decision being validated may be bound; outputs of any earlier
        # decision (e.g. one whose completion failed) are never re-bound later.
        stale = [item for item in self.deferred if item[3] != self.decision_capture]
        if stale:
            self.deferred = [item for item in self.deferred if item[3] == self.decision_capture]
            self._annotate(stale, 'decision_superseded_no_rebinding')
        if outcome.get('valid') and outcome.get('revision_proven'):
            return self.restage_deferred()
        reason = ('decision_invalidated_no_rebinding' if not outcome.get('valid')
                  else 'decision_background_revision_unproven')
        return self.drop_deferred(reason)

    def drop_deferred(self, reason):
        pending, self.deferred = self.deferred, []
        self._annotate(pending, reason)

    def _annotate(self, pending, reason):
        for value, entry, sources, decision in pending:
            def annotate(entry=entry):
                record = entry['record']
                record['diagnostics'].append({'reason': reason})
                write_json(self.trace.directory/entry['artifact'], record)
            self.observe(annotate)
        if pending:
            try:self.trace.event('fact_rebinding_skipped', step=self.step, reason=reason, outputs=len(pending))
            except Exception:pass

    def restage_deferred(self):
        """Re-bind decision outputs to the current (background) capture.

        Rewrites the same output/policy artifacts before acknowledgment; a capture
        without provenance leaves them unknown with explicit diagnostics.
        """
        pending, self.deferred = self.deferred, []
        for value, entry, sources, decision in pending:
            def rebind(value=value, entry=entry, sources=sources):
                self.stage(self.explorer, value, artifact=entry['artifact'], **entry['stage_options'])
                # Update the staged entry in place: delivery bookkeeping may hold
                # this object and register it only at acknowledgment.
                entry.update(self.select(value))
                self.outputs[id(value)] = (value, entry)
                for source in sources:
                    self.register(source, entry)
            self.observe(rebind)

    def select(self, value):
        item=self.outputs.get(id(value))
        return item[1] if item is not None and item[0] is value else None

    def lookup(self, artifact):
        # Deferred batch registration selects the frozen generation, not latest AX.
        return next((entry[1] for entry in self.outputs.values()
                     if entry[1]['artifact'] == artifact), None) if artifact else None

    def register(self, source, output=None):
        """Bind explicitly selected generation metadata; never infer it from text."""
        if output is not None:
            for item in self.deferred:
                if item[1] is output and source not in item[2]:item[2].append(source)
        record={'schema':VERSION,'offset_unit':'utf16_code_units','content_id':source['id'],'text_sha256':source['sha256'],'output_artifact':None,'projections':[],
                'references':[],'diagnostics':[]}
        if output is not None:
            base = output['text']; text=source['text']; projections=deepcopy(output['record']['projections'])
            if text == base:
                record.update(output_artifact=output['artifact'],projections=projections,
                              references=deepcopy(output['record']['references']))
            elif text.count(base)==1:
                # Known whole AX envelope within a browser/tab wrapper, not source-text relocation.
                prefix=u16(text[:text.index(base)]); _,layout=json_layout(output['body'])
                for projection in projections:
                    path=tuple(projection['output_path']);value=output['body']
                    for key in path:value=value[key]
                    bounds=json_string_boundaries(value)
                    # Nested JSON pages require composing escapes; leave those unsupported in wrappers.
                    if projection['encoding']!='identity':continue
                    projection.update(output_path=[],output_start=prefix+layout[path][0]+bounds[projection['output_start']],
                        output_end=prefix+layout[path][0]+bounds[projection['output_end']],encoding='json_string')
                    record['projections'].append(projection)
                record.update(output_artifact=output['artifact'],references=deepcopy(output['record']['references']))
            else:record['diagnostics'].append({'reason':'selected_output_changed'})
        else:record['diagnostics'].append({'reason':'no_selected_ax_output'})
        artifact=f"fact-policy-{source['id']}.json"
        write_json(self.trace.directory/artifact,record)
        self.content_outputs[source['id']]=artifact
        return artifact

    def delivery(self, receipt):
        recipient=receipt['recipient']; refs=self.ack_refs[recipient]; delivered=[]
        for item in receipt['items']:
            path=self.content_outputs.get(item['content_id'])
            if path is None:continue
            confirmed=bool(item['confirmed'] and receipt['scope']=='retained_request_completion')
            key=(recipient,item['content_id'])
            if confirmed and key in self.retained_confirmed:
                delivered.append({'content_id':item['content_id'],'artifact':path,'confirmed':True,
                                  'previously_confirmed':True,'references':[]})
                continue
            output=json.loads((self.trace.directory/path).read_text())
            delivered.append({'content_id':item['content_id'],'artifact':path,'confirmed':confirmed,
                              'references':deepcopy(output['references'])})
            if confirmed:
                self.retained_confirmed.add(key)
                for ref in {p['ref'] for p in output['projections']}:
                    ids=refs.setdefault(ref,[])
                    if item['content_id'] not in ids:ids.append(item['content_id'])
                    del ids[:-16];refs.move_to_end(ref)
                while len(refs)>256:refs.popitem(last=False)
        for item in delivered:
            for reference in item['references']:
                reference['acknowledged_content_ids']=list(refs.get(reference['historical_ref'],[])) if item['confirmed'] else []
                reference['scope']='Historical output only; no new fact/state exposure credit'
        record={'schema':VERSION,'offset_unit':'utf16_code_units','step':receipt['step'],'recipient':recipient,'scope':receipt['scope'],
                'items':delivered,'policy_receipt_sha256':object_digest(receipt),
                'messages_sha256':receipt['messages_sha256'],'ledger_artifact':'policy-delivery.jsonl',
                'http_dispatch_observed_by_ledger':False}
        with (self.trace.directory/'fact-delivery.jsonl').open('a',encoding='utf-8') as file:
            file.write(json.dumps(record,ensure_ascii=False)+'\n')
