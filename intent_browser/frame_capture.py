"""Document-scoped projection of a successful native capture.

A changing child must not invalidate unrelated stable documents. Unstable frame
content is omitted explicitly, never treated as an empty/verified page. Native
extraction still owns DOM/AX collection; this does not bypass its failures.
"""
from copy import deepcopy
from browsergym.core.observation import extract_dom_extra_properties
from .batching import DocumentScanInvalidated


def frame_documents(page,*,timed=None):
    """One CDP tree read, not serial JS evaluation in every advertising frame."""
    call=timed or (lambda name,fn:fn())
    cdp=call('identity_session_create',lambda:page.context.new_cdp_session(page))
    try:
        tree=call('identity_frame_tree',lambda:cdp.send('Page.getFrameTree'))['frameTree']
        main_document=call('identity_main_document',lambda:cdp.send('DOM.getDocument',{'depth':0}))['root']['backendNodeId']
    except BaseException:
        # Keep the original phase failure if detach is also blocked/expired.
        try:call('identity_session_detach',cdp.detach)
        except Exception:pass
        raise
    else:call('identity_session_detach',cdp.detach)
    frames={}
    def visit(entry,parent=None):
        f=entry['frame']
        frames[f['id']]={'loader_id':f.get('loaderId'), 'url':f['url']+f.get('urlFragment',''),'parent':parent}
        for child in entry.get('childFrames',[]):visit(child,f['id'])
    visit(tree)
    return {'page_id':id(page),'main_frame':tree['frame']['id'],'main_document':main_document,'frames':frames,
        'browser_frame_count':len(page.frames)}


def main_signature(documents):
    key=documents['main_frame']
    return {'page_id':documents['page_id'],'frame_id':key,'backend_document_id':documents.get('main_document'),**documents['frames'][key]}


def project_capture(obs,before,after,*,scale_factor=1.0,excluded_frames=(),exclude_children=False):
    if main_signature(before)!=main_signature(after):
        raise DocumentScanInvalidated({'reason':'main_document_changed_during_scoped_capture'})
    stable={key for key,value in before['frames'].items() if value.get('loader_id') and value==after['frames'].get(key)}
    stable.difference_update(excluded_frames)
    if exclude_children:stable.intersection_update({before['main_frame']})
    # A child of a replaced ancestor cannot independently claim continuity.
    for key in list(stable):
        parent=after['frames'][key]['parent'];seen=set()
        while parent is not None:
            if parent in seen or parent not in stable:
                stable.discard(key);break
            seen.add(parent);parent=after['frames'][parent]['parent']
    nodes=obs['axtree_object']['nodes'];by_id={n['nodeId']:n for n in nodes}
    owners={}
    def assign(node_id,frame):
        if node_id in owners:return
        n=by_id.get(node_id)
        if n is None:return
        owner=n.get('frameId',frame)
        owners[node_id]=owner
        for child in n.get('childIds',[]):assign(child,owner)
    # Root frame IDs override inheritance through merged iframe child edges.
    for n in nodes:
        if n.get('frameId'):assign(n['nodeId'],n['frameId'])
    kept={key for key,frame in owners.items() if frame in stable}
    projected=[]
    for n in nodes:
        if n['nodeId'] not in kept:continue
        n=deepcopy(n)
        if n.get('role',{}).get('value') in ('Iframe','IframePresentational') and (
                not n.get('childIds') or any(c not in kept for c in n['childIds'])):
            n.pop('browsergym_id',None)  # Clicking a frame container can enter its unknown document.
        if 'childIds' in n:n['childIds']=[c for c in n['childIds'] if c in kept]
        if n.get('parentId') not in kept:n.pop('parentId',None)
        projected.append(n)
    dom=deepcopy(obs['dom_object']);strings=dom['strings'];documents=dom['documents']
    def frame_id(doc):return strings[doc['frameId']]
    old_indices=[i for i,d in enumerate(documents) if frame_id(d) in stable]
    index_map={old:new for new,old in enumerate(old_indices)}
    dom['documents']=[documents[i] for i in old_indices]
    for d in dom['documents']:
        refs=d['nodes'].get('contentDocumentIndex')
        if refs:
            pairs=[(node,index_map[doc]) for node,doc in zip(refs['index'],refs['value']) if doc in index_map]
            refs['index']=[n for n,_ in pairs];refs['value']=[v for _,v in pairs]
    covered={frame_id(d) for d in dom['documents']} | {owners[k] for k in kept}
    main=before['main_frame']
    if main not in covered:
        raise DocumentScanInvalidated({'reason':'main_document_missing_from_native_capture'})
    omitted=sorted((set(before['frames']) | set(after['frames']) | {frame_id(d) for d in documents}
                    | {v for v in owners.values() if v})-covered)
    removed=len(nodes)-len(projected)
    # Some browser/CDP transports omit out-of-process children from the root
    # Page.getFrameTree response. An empty omission list cannot establish full
    # coverage when Playwright independently knows more frames exist.
    unresolved={name:max(0,docs.get('browser_frame_count',len(docs['frames']))-len(docs['frames']))
                for name,docs in (('before',before),('after',after))}
    coverage={'version':'stable-frame-projection-v1','partial':bool(omitted or removed or any(unresolved.values())),
        'included_frames':sorted(covered),'omitted_frames':omitted,'omitted_ax_nodes':removed,
        'scope':'Only documents stable across native capture are included. Omitted frames are unknown, not empty. '
                'Screenshot depicts the whole viewport at its capture time, including omitted frames.',
        'documents':{k:after['frames'][k] for k in covered},
        'bid_frames':{n['browsergym_id']:owners[n['nodeId']] for n in projected if n.get('browsergym_id')}}
    if any(unresolved.values()):
        coverage['unresolved_browser_frames']=unresolved
        coverage['scope']+=' Additional browser frames are absent from the CDP identity tree; their content is unknown.'
    if excluded_frames or exclude_children:
        coverage['native_exclusions']={'frames':sorted(excluded_frames),'all_children':exclude_children,
            'reason':'Frame RPC deadline/quarantine; unknown content, no target permission'}
    obs=dict(obs,axtree_object={**obs['axtree_object'],'nodes':projected},dom_object=dom,
        extra_element_properties=extract_dom_extra_properties(dom,scale_factor=scale_factor),
        frame_capture=coverage)
    if obs.get('focused_element_bid') not in coverage['bid_frames']:obs['focused_element_bid']=''
    return obs


def target_document_error(ticket,current,bid):
    frames=ticket.get('frame_capture',{})
    key=frames.get('bid_frames',{}).get(bid)
    if not key:return 'target_not_in_captured_stable_document'
    docs=frames.get('documents',{});seen=set()
    while key is not None:
        if key in seen or key not in docs or current['frames'].get(key)!=docs[key]:
            return 'target_frame_document_changed'
        seen.add(key);key=docs[key]['parent']
    return None


def quarantined_documents(obs,prefixes):
    """Map marked iframe-owner BIDs to native document IDs without child JS."""
    wanted=set(prefixes);resolved=set();excluded=set()
    dom=obs['dom_object'];strings=dom['strings'];docs=dom['documents']
    for doc in docs:
        nodes=doc['nodes'];refs=nodes.get('contentDocumentIndex',{})
        for owner,child in zip(refs.get('index',[]),refs.get('value',[])):
            attrs=nodes['attributes'][owner]
            values={strings[k]:strings[v] for k,v in zip(attrs[::2],attrs[1::2])}
            bid=values.get('bid')
            if bid in wanted:
                resolved.add(bid);excluded.add(strings[docs[child]['frameId']])
    return excluded,bool(wanted-resolved)
