"""Incremental public AX presentation shared by page updates, search and traversal.

Presentation is staged until the runner acknowledges matching policy spans. Full
raw observations remain separate. No task/grader state is read here.
"""
from copy import deepcopy
from collections import Counter, deque, OrderedDict
import hashlib
import json
import re

from .ax_explorer import AXExplorer, encoded
from .feedback_presentation import summarize_action_error

CONTEXT_TOOLS = ('ax_search','ax_read','ax_changes')
class LazyEntries:
    """Ordered (item, records) pairs projected only when iterated."""
    def __init__(self,context,refs,verbose,repeat,start=0):
        self.context,self.refs,self.verbose,self.repeat,self.start=context,refs,verbose,repeat,start
    def __len__(self):return len(self.refs)-self.start
    def __getitem__(self,key):
        if not isinstance(key,slice) or key.step not in (None,1) or key.stop is not None:
            raise TypeError('LazyEntries supports only [offset:] slicing')
        return LazyEntries(self.context,self.refs,self.verbose,self.repeat,self.start+(key.start or 0))
    def __bool__(self):return len(self)>0
    def __iter__(self):
        for begin in range(self.start,len(self.refs),16):
            selected=self.refs[begin:begin+16]
            self.context._prime_nodes([self.context._indices[ref] for ref in selected])
            for ref in selected:
                item,record=self.context._item(ref,self.verbose,self.repeat)
                yield item,({ref:record} if record else {})


class AXContext(AXExplorer):
    def __init__(self,config):
        super().__init__(config)
        self.document=0
        self._document_key=None
        self._identity_refs={}
        self._next_ref=0
        self.seen={}
        self.pending={}
        self._page_seen=None
        self._page_pending=None
        self.visits=[]
        self.feedback_metadata=None
        self._revisit_cache=OrderedDict()
        self._reuse={}
        self._semantic_key=None
        self._next_overview=None

    def reset_delivery(self):
        """Required when a caller removes context. Current runner never prunes."""
        self.seen.clear();self.pending.clear()
        self._page_seen=self._page_pending=None
        self._revisit_cache.clear();self._reuse={}

    def request_overview(self,tokens):
        if tokens is not None and (type(tokens) is not int or tokens not in (0,512,1000,2000,4000)):
            raise ValueError('ax_overview_tokens must be 0, 512, 1000, 2000 or 4000')
        self._next_overview=tokens

    def discard_pending(self):
        """No automatic retry: callers abandoning an unconfirmed request can
        discard its staged visit effects without claiming delivery."""
        self.pending.clear();self._page_pending=None

    def capture(self,observation):
        super().capture(observation)
        # A new real root/backend identity is a document boundary. URL changes
        # also reset references conservatively (including same-document routes).
        roots=[(self.nodes[i]['backend_identity'],self.nodes[i]['frame_identity'],
                self.nodes[i]['raw_node_id'] if self.nodes[i]['backend_identity'] is None else None) for i in self.roots]
        key=(self.url,encoded(roots),encoded(list(observation.get('open_pages_urls',[]))))
        if key!=self._document_key:
            self.document+=1;self._document_key=key;self._identity_refs={};self._next_ref=0
            # Navigation invalidates live handles, but not acknowledged history.
            self.seen.clear();self.pending.clear()
            self._page_seen=self._page_pending=None
        identities=[]
        for n in self.nodes:
            parent=identities[n['parent']] if n['parent'] is not None else 'root'
            if n['backend_identity'] is not None:
                identity=encoded(['dom',n['frame_identity'],n['backend_identity']])
            else:
                # Missing reliable DOM identity: exact content + parent + order.
                # Ambiguous/replaced text gets a NEW ref, never silently matched
                # merely because BrowserGym reuses a BID or synthetic node ID.
                siblings=self.nodes[n['parent']]['children'] if n['parent'] is not None else self.roots
                identity=encoded(['fallback',parent,siblings.index(n['index']),n['role'],
                    n['name'],n['value'],n['properties'],n['bid']])
            identities.append(hashlib.sha256(identity.encode()).hexdigest())
        duplicates=Counter(identities)
        active_keys={identity if duplicates[identity]==1 else identity+encoded(['ambiguous',self.snapshot,i])
                     for i,identity in enumerate(identities)}
        self._identity_refs={key:ref for key,ref in self._identity_refs.items() if key in active_keys}
        self._refs=[]
        for i,identity in enumerate(identities):
            if duplicates[identity]>1: identity+=encoded(['ambiguous',self.snapshot,i])
            if identity not in self._identity_refs:
                self._identity_refs[identity]=f'd{self.document}n{self._next_ref}'
                self._next_ref+=1
            self._refs.append(self._identity_refs[identity])
        self._indices={r:i for i,r in enumerate(self._refs)}
        self._states={}
        for i,n in enumerate(self.nodes):
            siblings=self.nodes[n['parent']]['children'] if n['parent'] is not None else self.roots
            self._states[self.ref(i)]={'ref':self.ref(i),'parent':self.ref(n['parent']) if n['parent'] is not None else None,
                'position':siblings.index(i),'role':n['role'],'name':n['name'],'value':n['value'],'bid':n['bid'],
                'properties':deepcopy(n['properties']),'children':[self.ref(c) for c in n['children']]}
        if self.config.revisit_reuse:
            # Exclude only volatile handles; preserve complete semantic values,
            # topology/order and URL. Matching URLs alone never permit reuse.
            semantic=[{k:n[k] for k in ('role','name','value','properties','parent','children')}
                      for n in self.nodes]
            self._semantic_key=hashlib.sha256(encoded([self.url,semantic]).encode()).hexdigest()
            cached=self._revisit_cache.get(self._semantic_key,{})
            self._reuse={self.ref(i):record for i,record in cached.items()
                         if record['state']['ref'].split('n')[0]!=f'd{self.document}'}

    def ref(self,index):return self._refs[index]

    def resolve(self,ref):
        if ref not in self._indices:raise ValueError('Stale or unknown AX ref; inspect current page changes or search again')
        return self._indices[ref]

    def controls(self,verbose=None,repeat=None):
        values=(self.config.verbose if verbose is None else verbose,self.config.repeat if repeat is None else repeat)
        if any(type(v) is not bool for v in values):raise ValueError('verbose and repeat must be booleans')
        return values

    def _known(self):return {**self.seen,**self.pending}

    def _version(self,state):return hashlib.sha256(encoded(state).encode()).hexdigest()

    def _record(self,ref,verbose):
        state=deepcopy(self._states[ref]);known=self._known().get(ref)
        version=self._version(state)
        return {'state':state,'version':version,'verbose':verbose or bool(known and known['version']==version and known['verbose']),
                'text_ranges':list(known.get('text_ranges',[])) if known else [],
                'matches':list(known.get('matches',[])) if known and known['version']==version else []}

    def _project(self,ref,verbose):
        n=self._states[ref]
        out={'ref':ref,'role':n['role']}
        if n['parent'] is not None:out['parent']=n['parent']
        # Position matters even if label/parent/child count remain unchanged.
        out['position']=n['position']
        if n['bid'] is not None:out['bid']=n['bid']
        for key in ('name','value'):
            if n[key]:
                out[key],short=self._clip(n[key],60)
                if short:out[key+'_partial']=True
        # AX properties are webpage semantics, not harness diagnostics. Retain
        # them in both modes; verbose only exposes internal extraction identity.
        props=n['properties']
        if props:out['state']=props
        if n['children']:out['children']=len(n['children'])
        if verbose:
            raw=self.nodes[self._indices[ref]]
            out['metadata']={k:raw[k] for k in ('raw_node_id','backend_identity','frame_identity')}
        return out

    def _full_fields_known(self,ref,verbose=False):
        known=self._known().get(ref)
        return bool(known and known['state']==self._states[ref] and (not verbose or known['verbose'])
            and not any(self._clip(self._states[ref][key],60)[1] for key in ('name','value')))

    def _item(self,ref,verbose,repeat,*,known=None):
        current=self._states[ref];known=self._known().get(ref) if known is None else known
        previous=self._reuse.get(ref)
        if previous and not known and not repeat and not verbose:
            # The referenced preview was acknowledged in this conversation.
            # Explicit current handles/location avoid silently reusing old BIDs.
            item={k:current[k] for k in ('ref','parent','position','bid')}
            item['reused_from']=previous['state']['ref']
            record=self._record(ref,False)
            record['text_ranges']=deepcopy(previous.get('text_ranges',[]))
            record['matches']=deepcopy(previous.get('matches',[]))
            return item,record
        if known and not repeat:
            old=known['state']
            if old==current and (not verbose or known['verbose']):return {'ref':ref,'unchanged':True},None
            projected=self._project(ref,verbose)
            if old!=current:
                changed=[k for k in current if old.get(k)!=current[k]]
                # Supply only changed fields plus identity/location. Text changes
                # beyond a shortened preview remain explicitly signalled.
                keep={'ref','parent','position'}|set(changed)
                if 'properties' in changed:keep.add('state')
                if 'children' in changed:keep.add('children')
                keep|={k+'_partial' for k in changed}
                result={k:v for k,v in projected.items() if k in keep}
                result['changed']=changed
                result['cleared']=[k for k in changed if current[k] in ('',None,[],{})]
                if not result['cleared']:result.pop('cleared')
                if 'children' in changed:result['children_changed']=True
                if 'properties' in changed and 'state' not in result:result['state']={}
                if verbose:result['metadata']=projected['metadata']
                return result,self._record(ref,verbose)
            return {'ref':ref,'unchanged':True,'metadata':projected.get('metadata')},self._record(ref,verbose)
        return self._project(ref,verbose),self._record(ref,verbose)

    def _envelope(self,tool,verbose=False):
        out={'tool':tool,'document':f'd{self.document}'}
        if verbose:out['metadata']={'snapshot':self.snapshot,'raw_nodes':self.raw_count,
            'indexed_nodes':len(self.nodes),'unreachable_raw_nodes':self.unreachable_raw_nodes,
            'scope':'Public captured AX only; no private verifier state'}
        if verbose and tool=='ax_changes' and self.feedback_metadata is not None:
            out['metadata']['recent_action_capture']=deepcopy(self.feedback_metadata)
        return out

    def _envelope_text(self,text,cap):
        # Measure the JSON representation too: control characters can expand
        # when escaped even when their plain text fits the tokenizer budget.
        allowance=cap
        value,partial=self._clip(text,allowance)
        while self.tokens(encoded(value))>cap:
            allowance=max(1,allowance//2)
            value,partial=self._clip(text,allowance)
        return value,partial

    def feedback(self,value,*,kind,verbose=None,repeat=None):
        """Same metadata convention for historical browser feedback. Distinct
        events are NOT deduplicated across actions: two commits are two events.
        Historical AX differences/transient notices remain separate from current
        state deltas because they may vanish before the next capture."""
        verbose,_=self.controls(verbose,repeat)
        if kind not in ('browser_feedback','browser_update'):return value
        result=deepcopy(value);metadata={}
        for key in ('scope','selection'):
            if key in result:metadata[key]=result.pop(key)
        counts=metadata.get('selection',{})
        omitted={k:v for k,v in counts.items() if v and k in ('capture_omitted','selection_omitted','truncated_fields','ax_lines_omitted')}
        if omitted:result['partial_capture']=omitted
        if result.get('error') is None:result.pop('error',None)
        if result.get('url_before')==result.get('url_after'):
            result.pop('url_before',None);result.pop('url_after',None)
        sequences=[]
        for event in result.get('events',[]):
            sequences.append(event.pop('sequence',None))
        if sequences:metadata['event_sequences']=sequences
        self.feedback_metadata=metadata
        if verbose:result['metadata']=metadata
        return result

    def _pack(self,output,entries,offset,total,budget,*,stage=True):
        """entries=(public item, delivery records); stage only items that fit."""
        result={**output,'items':[],'offset':offset,'total_entries':total,'next_offset':offset}
        records={}
        if isinstance(entries,LazyEntries):
            result,records=self._pack_lazy(result,entries,offset,budget)
        else:
          candidates=self._packed_candidates(result,[item for item,_ in entries],offset)
          for (candidate,count),(_,updates) in zip(candidates,entries):
            if count>budget-70:break
            result=candidate;records.update(updates)
        result['next_offset']=offset+len(result['items']) if offset+len(result['items'])<total else None
        if len(result['items'])<len(entries):result['budget_limited']=True
        if entries and not result['items']:
            result['error']='Entry exceeds token budget; request less context or ax_read view=node.'
            result['blocked_ref']=next(iter(entries))[0].get('ref')
        if self.tokens(encoded(result))>budget:raise ValueError('AX result envelope exceeds token budget')
        if stage:self.pending.update(records)
        return result

    def _pack_lazy(self,result,entries,offset,budget):
        """Same prefix as _pack, building and counting only near the budget.

        Entries are generated in order while an additive per-entry estimate stays
        below the limit plus slack; the exact cut (first prefix whose complete
        JSON exceeds the limit) is then located with exact counts of whole
        candidates, assuming counts grow with the prefix.
        """
        limit=budget-70
        def candidate(k):
            return {**result,'items':[item for item,_ in generated[:k]],'next_offset':offset+k}
        def fits(k):
            if k not in exact:exact[k]=self.tokens(encoded(candidate(k)))<=limit
            return exact[k]
        generated=[];exact={0:True}
        estimate=self.tokens(encoded(result))
        iterator=iter(entries)
        exhausted=False
        while True:
            while not exhausted and estimate<=limit+64:
                try:item,updates=next(iterator)
                except StopIteration:
                    exhausted=True;break
                generated.append((item,updates))
                estimate+=self.tokens(encoded(item))+1
            # First failing prefix in 1..len(generated), if any.
            low,high=0,len(generated)
            if fits(high):
                if exhausted:break
                estimate=self.tokens(encoded(candidate(high)))+1  # recalibrate, keep generating
                continue
            while high-low>1:
                middle=(low+high)//2
                if fits(middle):low=middle
                else:high=middle
            generated=generated[:low]
            break
        records={}
        for _,updates in generated:records.update(updates)
        return candidate(len(generated)),records

    def _entries(self,refs,verbose,repeat):
        result=[]
        for start in range(0,len(refs),16):
            selected=refs[start:start+16]
            self._prime_nodes([self._indices[ref] for ref in selected])
            for ref in selected:
                item,record=self._item(ref,verbose,repeat)
                result.append((item,{ref:record} if record else {}))
        return result

    def _page_entries(self,verbose,repeat):
        known=self._known();full=self._page_seen is None and self._page_pending is None
        if repeat or full:
            queue=deque(self.roots);refs=[]
            while queue:
                i=queue.popleft();refs.append(self.ref(i));queue.extend(self.nodes[i]['children'])
            # Entries are built on demand: only those near the budget are projected.
            return LazyEntries(self,refs,verbose,repeat),full
        entries=[]
        for ref,record in known.items():
            if record is None:continue
            if ref not in self._states:
                entries.append(({'ref':ref,'removed':True},{ref:None}))
            elif record['state']!=self._states[ref] or (verbose and not record['verbose']):
                item,update=self._item(ref,verbose,repeat)
                entries.append((item,{ref:update} if update else {}))
        # Report new immediate children of visited nodes. Deep unknown regions
        # stay collapsed but a visited ancestor's membership change is visible.
        for ref,state in self._states.items():
            if ref in known:continue
            parent=known.get(state['parent'])
            if parent and ref not in parent['state'].get('children',[]):
                item,update=self._item(ref,verbose,repeat)
                entries.append((item,{ref:update}))
        return entries,False

    def page_update(self,observation=None,*,verbose=None,repeat=None,offset=0,stage=True,budget=None):
        if observation is not None:self.capture(observation)
        verbose,repeat=self.controls(verbose,repeat)
        budget=self.config.overview_tokens if budget is None else budget
        if budget==0:
            # Acknowledge only the page header, never node fields. Do not spring
            # an unsolicited full overview on the next targeted query. Known
            # node changes still remain pending; unknown content is searchable.
            output={**self._envelope('ax_changes',verbose),'ax_nodes_omitted':True,
                    'requested_tokens':0,'items':[],
                    'inspect_with':'ax_search, ax_read or ax_changes; omission does not mean unchanged'}
            output['url'],partial=self._envelope_text(self.url,128)
            if partial:output['url_partial']=True
            error=str((observation or {}).get('last_action_error',getattr(self,'_last_error','')))
            if error:output['last_action_error']=self._envelope_text(summarize_action_error(error),192)[0]
            self._last_error=error
            if stage:self._page_pending={'url':self.url,'error':error}
            self.last_overview={'snapshot':self.snapshot,'shown':0,'total':len(self.nodes),
                'tokens':self.tokens(encoded(output)),'complete':False,'requested_tokens':0,
                'presentation':'incremental-ax-v2'}
            return output
        entries,initial=self._page_entries(verbose,repeat)
        # Tombstones are tracked privately; _known consumers treat None as absent.
        state={'url':self.url,'error':str((observation or {}).get('last_action_error',getattr(self,'_last_error','')))}
        self._last_error=state['error']
        output=self._envelope('ax_changes',verbose)
        if self._reuse and not repeat:
            output['reuse_scope']='Exact captured public AX match; reused_from references earlier delivered descriptions. Use current ref/bid.'
        if initial or repeat:output.update(url=self.url,roots=[self.ref(i) for i in self.roots[:8]],initial_overview=True)
        prior=self._page_pending or self._page_seen
        if prior and prior['url']!=state['url']:output['url']=state['url']
        if state['error'] and (not prior or prior['error']!=state['error'] or repeat):
            summary=summarize_action_error(state['error'])
            output['last_action_error'],_=self._envelope_text(summary,min(192,budget//4))
            if output['last_action_error']!=state['error']:output['last_action_error_details_omitted']=True
        if prior and prior['error'] and not state['error']:output['last_action_error_cleared']=True
        if not initial and not entries:
            output['visited_content_unchanged']=True
            if not self._known():output['no_nodes_visited']=True
        if initial:output['coverage']='Structural overview; expand nodes or search for omitted content.'
        # Envelope text is not pageable like AX entries. Bound it before packing
        # so an error or long URL cannot consume the entire overview budget.
        if 'url' in output:
            output['url'],partial=self._envelope_text(output['url'],min(192,budget//4))
            if partial:output['url_partial']=True
        if 'metadata' in output and self.tokens(encoded(output))>budget-128:
            output.pop('metadata');output['metadata_omitted']=True
        result=self._pack(output,entries[offset:],offset,len(entries),budget,stage=stage)
        # For delta updates, delivered changes leave the pending set. Continue
        # remaining updates from offset0; offsets are only stable within a view.
        if not initial and not repeat and result['next_offset'] is not None:
            result['next_offset']=0;result['continue_with']='ax_changes'
        elif result['next_offset'] is not None:
            result['continue_with']={'ax_changes':{'repeat':True,'verbose':verbose,'offset':result['next_offset']}}
        if stage:self._page_pending=state
        self.last_overview={'snapshot':self.snapshot,'shown':len(result['items']),'total':len(self.nodes),
            'tokens':self.tokens(encoded(result)),'complete':initial and result['next_offset'] is None,
            'presentation':'incremental-ax-v2' if self.config.revisit_reuse or self.config.agent_overview else 'incremental-ax-v1'}
        if self.config.revisit_reuse:
            self.last_overview.update(semantic_sha256=self._semantic_key,
                reused_nodes=sum('reused_from' in item for item in result['items']))
        return result

    def overview(self,observation):
        # Trace-only transition rendering MUST NOT mark content delivered.
        if observation.get('observation_capture',{}).get('coverage')=='partial':
            return self.partial_overview(observation)
        return encoded(self.page_update(observation,stage=False))

    def partial_overview(self,observation,budget=None):
        """Preview only: never prune/acknowledge the full-tree visit ledger."""
        if not hasattr(self,'_preview_explorer'):
            preview=AXExplorer(self.config)
            if (self.config.shared_tokenizer is not None and
                    preview.tokenizer._instance != self.tokenizer._instance):
                from .shared_tokenizer import SharedTokenizerError
                raise SharedTokenizerError('Shared tokenizer restarted; requalification required')
            self._preview_explorer=preview
        preview=self._preview_explorer
        preview.capture(observation)
        budget=self.config.overview_tokens if budget is None else budget
        output={'coverage':'partial','url':self._clip(observation['url'],100)[0],
            'items':[], 'notice':'Depth-limited preview, not a full tree or removal report. '
                'BIDs are browser targets. Use ax_search for omitted content; full capture finishes before tools execute.',
            'ax_references':'Only full-tree query results provide ax_read references.',
            'preview_nodes_omitted':len(preview.nodes)}
        if observation.get('observation_capture',{}).get('version') in ('dynamic-main-preview-v1','dynamic-main-preview-v2'):
            output['notice']='Shallow main-document orientation, not a full tree or removal report. Child frames are omitted. No clickable BIDs are provided here; ax_search can find targets after background capture finishes.'
            if observation['observation_capture'].get('preview_bids'):
                output['notice']='Shallow main-document preview; child frames and omitted nodes remain unknown. Shown BIDs target visible elements; full capture validates identity before actions execute. Use AX tools for omitted content.'
            output['capture_node_limit']=observation['observation_capture']['node_limit']
            output['capture_nodes_omitted']=observation['observation_capture']['preview_nodes_omitted']
        if observation.get('last_action_error'):
            output['last_action_error']=self._clip(summarize_action_error(observation['last_action_error']),100)[0]
        if budget:
            for n in preview.nodes:
                item={'role':n['role'],'name':self._clip(n['name'],40)[0],
                    **({'bid':n['bid']} if n['bid'] is not None else {}),
                    **({'value':self._clip(n['value'],32)[0]} if n['value'] else {})}
                output['items'].append(item)
                output['preview_nodes_omitted']=len(preview.nodes)-len(output['items'])
                if self.tokens(encoded(output))>budget:
                    output['items'].pop()
                    output['preview_nodes_omitted']=len(preview.nodes)-len(output['items'])
                    break
        output['preview_nodes_omitted']=len(preview.nodes)-len(output['items'])
        self.last_overview={'presentation':'partial-preview-v1','complete':False,
            'shown':len(output['items']),'tokens':self.tokens(encoded(output)),'requested_tokens':budget}
        return encoded(output)

    def prepare_observation(self,observation):
        budget=self._next_overview if self.config.agent_overview else None
        if observation.get('observation_capture',{}).get('coverage')=='partial':
            self._next_overview=None
            return self.partial_overview(observation,budget)
        result=self.page_update(observation,stage=True,budget=budget)
        if self.config.agent_overview:
            result['automatic_budget_tokens']=self.config.overview_tokens if budget is None else budget
            self.last_overview['automatic_budget_tokens']=result['automatic_budget_tokens']
            self.last_overview['tokens']=self.tokens(encoded(result))
        self._next_overview=None
        return encoded(result)

    def acknowledge(self):
        self.seen.update(self.pending);self.seen={k:v for k,v in self.seen.items() if v is not None}
        self.pending.clear()
        if self._page_pending is not None:self._page_seen=self._page_pending
        self._page_pending=None
        if self.config.revisit_reuse and self._semantic_key is not None:
            records={self._indices[ref]:deepcopy(record) for ref,record in self.seen.items()
                     if ref in self._indices and record['state']==self._states[ref]}
            if records:
                self._revisit_cache[self._semantic_key]=records
                self._revisit_cache.move_to_end(self._semantic_key)
                while len(self._revisit_cache)>64:self._revisit_cache.popitem(last=False)

    def search(self,query,role=None,limit=5,context=0,offset=0,scope_ref=None,verbose=None,repeat=None,match='any'):
        verbose,repeat=self.controls(verbose,repeat)
        if match not in ('any','all'):raise ValueError('match must be any or all')
        if isinstance(query,str):
            terms=[query.strip()] if query.strip() else []
        elif isinstance(query,list) and 1<=len(query)<=8 and all(isinstance(t,str) and t.strip() for t in query):
            terms=[t.strip() for t in query]
        else:raise ValueError('query must be a phrase or 1..8 nonempty terms')
        if any(len(t)>256 for t in terms):raise ValueError('Each search term must be at most 256 characters')
        unique=[];folded=set()
        for term in terms:
            if term.casefold() not in folded:
                unique.append(term);folded.add(term.casefold())
        terms=unique
        if not terms and not role:raise ValueError('Provide nonempty query or role')
        scope=None
        if scope_ref is not None:
            root=self.resolve(scope_ref);scope=set();todo=[root]
            while todo:
                i=todo.pop();scope.add(i);todo.extend(self.nodes[i]['children'])
        matched={n['index']:[term for term in terms if term.casefold() in n['search_text']] for n in self.nodes}
        indices=[n['index'] for n in self.nodes if (scope is None or n['index'] in scope)
            and (not role or n['role'].casefold()==role.casefold())
            and (not terms or (len(matched[n['index']])==len(terms) if match=='all' else bool(matched[n['index']])))]
        entries=[]
        selected=indices[offset:offset+limit]
        to_prime=set(selected)
        for i in selected:
            parent=self.nodes[i]['parent']
            for _ in range(3):
                if parent is None:break
                to_prime.add(parent);parent=self.nodes[parent]['parent']
            to_prime.update(j for j in range(max(0,i-context),min(len(self.nodes),i+context+1))
                            if scope is None or j in scope)
        self._prime_nodes(sorted(to_prime))
        for i in indices[offset:offset+limit]:
            ref=self.ref(i);item,record=self._item(ref,verbose,repeat);updates={ref:record} if record else {}
            # Location uses the same presenter: known ancestors are short refs,
            # unknown ancestors introduce their labels once, with full ancestry
            # recoverable through ax_read(view=ancestors).
            ancestors=[];parent=self.nodes[i]['parent']
            while parent is not None:ancestors.append(parent);parent=self.nodes[parent]['parent']
            path=[]
            for parent in reversed(ancestors[:3]):
                p=self.ref(parent);part,rec=self._item(p,verbose,repeat);path.append(part)
                if rec:updates[p]=rec
            item={**item,'location':path}
            if len(ancestors)>3:item['earlier_ancestors_omitted']=len(ancestors)-3
            if isinstance(query,list):item['matched_terms']=matched[i]
            source=self.nodes[i]['source_text'];known=self._known().get(ref)
            for term in matched[i]:
                hit=re.search(re.escape(term),source,re.IGNORECASE)
                if hit:
                    excerpt=self._clip(source[max(0,hit.start()-48):hit.end()+96],80)[0];match_key='match'
                else:
                    position=source.casefold().find(term.casefold())
                    excerpt=self._clip(source.casefold()[max(0,position-48):position+len(term)+96],80)[0];match_key='normalized_match'
                match_hash=hashlib.sha256(excerpt.encode()).hexdigest()
                if repeat or (not self._full_fields_known(ref) and (not known or match_hash not in known.get('matches',[]))):
                    if isinstance(query,list):item.setdefault('excerpts',[]).append({'term':term,match_key:excerpt})
                    else:item[match_key]=excerpt
                    rec=updates.get(ref) or self._record(ref,verbose)
                    rec['matches'].append(match_hash);updates[ref]=rec
            if context:
                item['neighbors']=[]
                for neighbor in range(max(0,i-context),min(len(self.nodes),i+context+1)):
                    if neighbor==i or (scope is not None and neighbor not in scope):continue
                    r=self.ref(neighbor);part,rec=self._item(r,verbose,repeat);item['neighbors'].append(part)
                    if rec:updates[r]=rec
            entries.append((item,updates))
        output={**self._envelope('ax_search',verbose),'query':query}
        # Diagnose a common encoding mistake without changing literal semantics,
        # executing a second search, or silently replacing policy arguments.
        # A successful literal match is not treated as an input mistake.
        if not indices and isinstance(query,str) and query.strip().startswith('['):
            try:
                decoded=json.loads(query)
            except (ValueError,RecursionError):
                decoded=None
            if (isinstance(decoded,list) and 1<=len(decoded)<=8
                    and all(isinstance(t,str) and t.strip() and len(t)<=256 for t in decoded)):
                output['query_notice']={
                    'code':'array_encoded_as_literal_string',
                    'message':'No literal matches. query was a STRING and was searched exactly as written. '
                              'If you intended multiple terms, submit an actual JSON array, not array text inside a string.',
                    'array_query_example':{'query':decoded},
                    'search_was_reinterpreted':False}
                # The diagnostic shares the result budget; do not duplicate a
                # token-heavy literal just to show its decoded array example.
                if self.tokens(encoded(output))>self.config.result_tokens-120:
                    notice=output['query_notice'];notice.pop('array_query_example')
                    notice['example_omitted']='token_budget'
                    notice['message']='Searched literally. For multiple terms, replace query with an actual JSON array; keep other filters.'
        if isinstance(query,list) or match!='any':output['match']=match
        if scope_ref:output['scope_ref']=scope_ref
        if role:output['role']=role
        return self._pack(output,entries,offset,len(indices),self.config.result_tokens)

    def _radius_nodes(self,index,radius):
        """BFS with parent, child and same-parent sibling adjacency.

        A sibling edge counts as one hop by contract (not two parent-child
        edges). Expand each sibling group once to avoid quadratic wide lists.
        Distinct roots are not siblings. Order is focus first, then BFS rings;
        newly discovered neighbors are ordered by captured tree position.
        """
        distance={index:0};queue=deque([index]);order=[];expanded_groups=set()
        while queue:
            current=queue.popleft();order.append(current);d=distance[current]
            if d==radius:continue
            n=self.nodes[current];neighbors=list(n['children']);parent=n['parent']
            if parent is not None:
                neighbors.append(parent)
                if parent not in expanded_groups:
                    expanded_groups.add(parent);neighbors.extend(self.nodes[parent]['children'])
            for neighbor in sorted(set(neighbors)):
                if neighbor not in distance:
                    distance[neighbor]=d+1;queue.append(neighbor)
        return order,distance

    def read(self,node_ref,view='children',depth=1,limit=20,offset=0,context=2,text_offset=0,verbose=None,repeat=None,radius=0):
        verbose,repeat=self.controls(verbose,repeat);index=self.resolve(node_ref);n=self.nodes[index]
        if type(radius) is not int or not 0<=radius<=8:
            raise ValueError('radius must be an integer between 0 and 8')
        if radius and view!='node':
            raise ValueError('radius applies only to view=node; use context for flattened neighborhood')
        output={**self._envelope('ax_read',verbose),'root':node_ref,'view':view}
        if view=='node' and radius:
            if text_offset:
                raise ValueError('text_offset applies to node radius=0; radius results use offset/next_offset')
            if type(limit) is not int or not 1<=limit<=50 or type(offset) is not int or offset<0:
                raise ValueError('radius results require limit 1..50 and nonnegative integer offset')
            indices,distances=self._radius_nodes(index,radius)
            entries=[]
            self._prime_nodes(indices[offset:offset+limit])
            for i in indices[offset:offset+limit]:
                ref=self.ref(i);item,record=self._item(ref,verbose,repeat)
                entries.append(({**item,'distance':distances[i]},{ref:record} if record else {}))
            output.update(radius=radius,scope='structural_radius')
            result=self._pack(output,entries,offset,len(indices),self.config.result_tokens)
            self.visits.append({'document':self.document,'root':node_ref,'view':view,'radius':radius,
                'offset':offset,'returned':len(result['items']),'snapshot':self.snapshot,'verbose':verbose,'repeat':repeat})
            return result
        if view=='node':
            output.update(radius=0,scope='own_fields_only')
            if n['children']:
                output.update(children=len(n['children']),expand_with={'view':'node','radius':1})
            if not repeat and self._full_fields_known(node_ref,verbose):
                return {**output,'unchanged':True,'next_text_offset':None,
                    'repeat_hint':'Own fields already delivered; repeat=true rereads them. Descendants are separate.'}
            full=self._project(node_ref,verbose)
            # Full semantic name/value/state, independently paged from previews.
            full.update(name=n['name'],value=n['value'])
            full.pop('name_partial',None);full.pop('value_partial',None)
            text=encoded(full);ids=self.tokenizer.encode(text,add_special_tokens=False).ids
            known=self._known().get(node_ref)
            signature=hashlib.sha256(text.encode()).hexdigest()
            if known and not repeat:
                for sig,start,end in known.get('text_ranges',[]):
                    if sig==signature and start<=text_offset<end:
                        return {**output,'unchanged':True,'text_offset':text_offset,'next_text_offset':end if end<len(ids) else None,
                            'total_text_tokens':len(ids),'repeat_hint':'Use repeat=true to reread this delivered text range.'}
            count=max(1,self.config.result_tokens-self.tokens(encoded(output))-110)
            fragment=ids[text_offset:text_offset+count]
            while True:
                result={**output,'text':self.tokenizer.decode(fragment,skip_special_tokens=False),'text_offset':text_offset,
                    'next_text_offset':text_offset+len(fragment) if text_offset+len(fragment)<len(ids) else None,'total_text_tokens':len(ids)}
                if self.tokens(encoded(result))<=self.config.result_tokens:break
                if not fragment:raise ValueError('Node text envelope exceeds token budget')
                fragment=fragment[:-16]
            # A fragment does not deliver the full node preview. Preserve only
            # previously delivered node fields; range ledger is separate.
            record=deepcopy(known) if known else {'state':{},'version':'','verbose':False,'text_ranges':[]}
            record['text_ranges'].append((signature,text_offset,text_offset+len(fragment)))
            self.pending[node_ref]=record
            return result
        if view=='children':indices=list(n['children'])
        elif view=='ancestors':
            indices=[];parent=n['parent']
            while parent is not None:indices.append(parent);parent=self.nodes[parent]['parent']
        elif view=='neighborhood':indices=list(range(max(0,index-context),min(len(self.nodes),index+context+1)))
        elif view=='subtree':
            indices=[];todo=[(index,0)]
            while todo:
                i,level=todo.pop();indices.append(i)
                if level<depth:todo.extend((child,level+1) for child in reversed(self.nodes[i]['children']))
        else:raise ValueError('Unsupported AX view')
        result=self._pack(output,self._entries([self.ref(i) for i in indices[offset:offset+limit]],verbose,repeat),offset,len(indices),self.config.result_tokens)
        self.visits.append({'document':self.document,'root':node_ref,'view':view,'offset':offset,'returned':len(result['items']),
            'snapshot':self.snapshot,'verbose':verbose,'repeat':repeat})
        return result

    def execute(self,name,arguments):
        try:
            if name=='ax_changes':return self.page_update(**arguments,budget=self.config.result_tokens)
            return self.search(**arguments) if name=='ax_search' else self.read(**arguments)
        except ValueError as exc:return {'tool':name,'error':str(exc),'items':[]}
