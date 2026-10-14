"""CDP conversion of settled copied-renderer registrations to actual DOM runs.

This is a scripted capture utility, not a recipient-delivery recorder. Consumers
must keep exposure unknown until Harness output maps and acknowledgments exist.
"""
from hashlib import sha256
from functools import lru_cache
from pathlib import Path
from .fact_exposure import utf16_length, utf16_slice
from .website_projection import direct_sources


def _text_hash(text):
    return sha256(text.encode()).hexdigest()


@lru_cache(maxsize=1)
def _render_attestation_function():
    # Reuse the exact producer function rather than maintaining two normalizers.
    source=(Path(__file__).parent/'assets'/'fact_render_recorder.js').read_text()
    function=source.split('export function renderAttestation(root) {',1)[1]
    function=function.split('\nexport function createFactRecorder',1)[0]
    return 'function renderAttestation(root) {'+function


def read_attestation(page, commit, *, attestation_function=None):
    """Read one live snapshot; callers validate its exact corresponding export."""
    expected=commit['meta']
    selector=expected.get('root_selector','#app')
    state_kind=expected.get('state_kind','local_storage')
    if selector not in ('#app','#main','main','body') or state_kind not in ('local_storage','static_review'):
        raise ValueError('Unqualified render root or state kind')
    if selector == 'main' and page.locator('main').count() != 1:
        raise ValueError('Expected exactly one native main root')
    if 'render_state' in expected:
        if expected['render_state'].get('schema')!='fact-render-state-browsergym-v1':
            raise ValueError('Unqualified render attestation schema')
        script='(config)=>{'+(attestation_function or _render_attestation_function())+'''
          return {url:location.href,render_state:renderAttestation(document.querySelector(config.selector)),
            draft:config.static?null:JSON.parse(localStorage.getItem(config.key))};}'''
    else:
        script='(config)=>({url:location.href,html:document.querySelector(config.selector).outerHTML,draft:config.static?null:JSON.parse(localStorage.getItem(config.key))})'
    config={'selector':selector,'key':expected['state_key'],'static':state_kind=='static_review'}
    actual=page.evaluate(script,config)
    required={'url','draft','render_state' if 'render_state' in expected else 'html'}
    if set(actual)!=required:raise ValueError('Incomplete live render attestation')
    return actual


def validate_attestation(actual, commit):
    expected=commit['meta']
    if any(expected.get(key)!=value for key,value in actual.items()):
        raise ValueError('Render content, URL or effective state is stale')


def attest(page, commit, *, attestation_function=None):
    """Check live render/state against its export; legacy exports stay strict."""
    actual=read_attestation(page,commit, **(
        {'attestation_function':attestation_function} if attestation_function is not None else {}))
    validate_attestation(actual,commit)
    return actual


def _child(node, path):
    for index in path:
        if type(index) is not int or index < 0:
            raise ValueError('Invalid DOM child path')
        node = node['children'][index]
    return node


def normalize(commit, app_node, *, snapshot_id, document_id, frame_id, control_values=None):
    """Bind actual nodes and keep per-part intervals; fail on stale paths/text."""
    if commit['schema'] != 'fact-render-dom-v1' or commit['offset_unit'] != 'utf16_code_units':
        raise ValueError('Expected opt-in UTF-16 render export')
    runs, occurrences = [], {}
    for number, registration in enumerate(commit['registrations']):
        node = _child(app_node, registration['element_path'])
        if node['nodeType'] != 1:
            raise ValueError('Registration is not an existing DOM element')
        occurrence = registration['occurrence']
        key = f'{snapshot_id}/{occurrence["id"]}'
        item = occurrences.setdefault(key, {'id':key,'binding':occurrence['binding'],
            'effective_state':occurrence['effective_state'],'parts':[],
            'semantic_status':'producer_qualification_required','exposure':'unknown'})
        if item['binding'] != occurrence['binding'] or item['effective_state'] != occurrence['effective_state']:
            raise ValueError('Conflicting occurrence identity/state')
        ids = []
        for index, run in enumerate(registration['runs']):
            actual = _child(node, run['relative_child_path'])
            if run['kind'] == 'text_node' and (actual['nodeType'] != 3 or actual['nodeValue'] != run['text']):
                raise ValueError('Stale text binding')
            if run['kind'] == 'control_value':
                if actual['nodeType'] != 1 or (control_values or {}).get(actual['backendNodeId']) != run['text']:
                    raise ValueError('Verified live control value required')
            elif run['kind'] != 'text_node':
                raise ValueError('Unsupported DOM source kind')
            if run['end'] - run['start'] != utf16_length(run['text']):
                raise ValueError('Invalid UTF-16 run interval')
            identity = f'{snapshot_id}/element-{number}/run-{index}'
            ids.append(identity)
            runs.append({'id':identity,'kind':run['kind'],'backend_node_id':actual['backendNodeId'],
                         'text':run['text'],'sha256':_text_hash(run['text'])})
        for part in registration['parts']:
            spans = []
            for span in part['ranges']:
                run = registration['runs'][span['run_index']]
                utf16_slice(run['text'], span['start'], span['end'])
                spans.append({'source_id':ids[span['run_index']], 'start':span['start'],'end':span['end']})
            if sum(s['end']-s['start'] for s in spans) != part['end']-part['start']:
                raise ValueError('Incomplete DOM part binding')
            item['parts'].append({'part':part['part'],'spans':spans})
    return {'schema':'fact-render-normalized-v1','snapshot_id':snapshot_id,
        'document_id':document_id,'frame_id':frame_id,'render_revision':commit['revision'],
        'runs':runs,'occurrences':list(occurrences.values()),'diagnostics':commit['diagnostics'],
        'delivery_evidence':False,'inventory_complete':False}


def capture(page, cdp, commit, *, snapshot_id, raw_ax=None, attestation_function=None):
    """Capture unchanged DOM/AX and normalize exact-path registrations."""
    before = attest(page,commit, **(
        {'attestation_function':attestation_function} if attestation_function is not None else {}))
    doc = cdp.send('DOM.getDocument', {'depth':-1})['root']
    app_id = cdp.send('DOM.querySelector', {'nodeId':doc['nodeId'],
        'selector':commit['meta'].get('root_selector','#app')})['nodeId']
    app = cdp.send('DOM.describeNode', {'nodeId':app_id,'depth':-1})['node']
    frame = cdp.send('Page.getFrameTree')['frameTree']['frame']['id']
    ax = raw_ax if raw_ax is not None else cdp.send('Accessibility.getFullAXTree')['nodes']
    snapshot = cdp.send('DOMSnapshot.captureSnapshot', {'computedStyles':[]})
    after = attest(page,commit, **(
        {'attestation_function':attestation_function} if attestation_function is not None else {}))
    if before != after:
        raise ValueError('DOM, URL or effective state changed during capture')
    controls={}
    for document in snapshot['documents']:
        if snapshot['strings'][document['frameId']] != frame:
            continue
        nodes=document['nodes'];values=nodes.get('inputValue', {'index':[],'value':[]})
        for index,value in zip(values['index'],values['value']):
            controls[nodes['backendNodeId'][index]]='' if value == -1 else snapshot['strings'][value]
    # Validate each exact run a second time against the same captured DOMSnapshot.
    snapshot_backend={}
    for document in snapshot['documents']:
        if snapshot['strings'][document['frameId']] != frame:continue
        nodes=document['nodes']
        for index,backend in enumerate(nodes['backendNodeId']):
            snapshot_backend[backend]=(nodes['nodeType'][index],snapshot['strings'][nodes['nodeValue'][index]])
    normalized = normalize(commit, app, snapshot_id=snapshot_id,
                           document_id=str(doc['backendNodeId']),frame_id=frame,control_values=controls)
    for run in normalized['runs']:
        if run['kind']=='text_node' and snapshot_backend.get(run['backend_node_id']) != (3,run['text']):
            raise ValueError('DOM snapshot/text-node mismatch')
    sources, diagnostics = direct_sources(ax,normalized['runs'],snapshot_id=snapshot_id,
                           document_id=normalized['document_id'],frame_id=frame)
    normalized.update(ax_sources=sources, ax_diagnostics=diagnostics)
    return {'normalized':normalized,'raw_ax':ax,'dom_snapshot':snapshot,'app_node':app,'commit':commit}


def harness_source_packet(normalized):
    """Pure handoff to ax-fact-sources-v1; preserves unknown exposure qualification.

    The live callback must validate capture identity/race against its existing raw
    capture. This function does not install a provider or assert delivery.
    """
    from copy import deepcopy
    from .fact_exposure import object_digest
    if normalized['schema'] != 'fact-render-normalized-v1':
        raise ValueError('Expected normalized render export')
    references={}
    for occurrence in normalized['occurrences']:
        state_id=object_digest(occurrence['effective_state'])
        for part in occurrence['parts']:
            for span in part['spans']:
                references.setdefault(span['source_id'],[]).append({'occurrence_id':occurrence['id'],
                    'state_id':state_id,'part':part['part'],'start':span['start'],'end':span['end']})
    sources=[]
    for raw in normalized['ax_sources']:
        source=deepcopy(raw)
        source['opaque_binding']={'render_revision':normalized['render_revision'],
                                  'parts':deepcopy(references.get(raw['id'],[]))}
        sources.append(source)
    return {'schema':'ax-fact-sources-v1','sources':sources,
        'private_context':{'schema':'fact-render-occurrence-joins-v1','occurrences':deepcopy(normalized['occurrences']),
            'diagnostics':deepcopy(normalized['diagnostics']),'unsupported_ax':deepcopy(normalized['ax_diagnostics']),
            'inventory_complete':False,'delivery_evidence':False}}


def snapshot_tree(dom, frame_id, selector):
    """Rebuild a describeNode-shaped subtree from an existing DOMSnapshot.

    Children follow JS childNodes order: pseudo-element and shadow-root nodes
    (and the flattened shadow content below them) are skipped. Returns the
    selected root and the document backend ID; no browser call is made.
    """
    strings = dom['strings']
    documents = [d for d in dom['documents'] if strings[d['frameId']] == frame_id]
    if len(documents) != 1:
        raise ValueError('Main document absent from DOM snapshot')
    nodes = documents[0]['nodes']
    count = len(nodes['parentIndex'])
    skipped = set(nodes.get('pseudoType', {}).get('index', [])) | set(nodes.get('shadowRootType', {}).get('index', []))
    children = [[] for _ in range(count)]
    for index, parent in enumerate(nodes['parentIndex']):
        if parent >= 0:
            children[parent].append(index)
    def value(index):
        raw = nodes['nodeValue'][index]
        return '' if raw == -1 else strings[raw]
    def name(index):
        return strings[nodes['nodeName'][index]]
    def attributes(index):
        raw = nodes['attributes'][index]
        return {strings[k]: strings[v] for k, v in zip(raw[::2], raw[1::2])}
    document = next((i for i in range(count) if nodes['nodeType'][i] == 9), None)
    if document is None:
        raise ValueError('Document node absent from DOM snapshot')
    if selector in ('#app', '#main'):
        matches = [i for i in range(count) if nodes['nodeType'][i] == 1 and i not in skipped
                   and attributes(i).get('id') == selector[1:]]
    elif selector in ('main', 'body'):
        matches = [i for i in range(count) if nodes['nodeType'][i] == 1 and i not in skipped
                   and name(i).lower() == selector]
    else:
        raise ValueError('Unqualified render root')
    if len(matches) != 1:
        raise ValueError('Render root absent or ambiguous in DOM snapshot')
    def build(index, depth=0):
        if depth > 512:
            raise ValueError('DOM snapshot subtree too deep')
        return {'nodeType': nodes['nodeType'][index], 'nodeName': name(index), 'nodeValue': value(index),
                'backendNodeId': nodes['backendNodeId'][index],
                'children': [build(c, depth+1) for c in children[index] if c not in skipped]}
    return build(matches[0]), nodes['backendNodeId'][document]


def capture_from_snapshot(commit, dom, raw_ax, *, snapshot_id, frame_id):
    """Normalize a probe export against the harness capture's own DOM/AX data.

    The caller must establish that the page did not change between the probe and
    the DOM/AX extraction (public revision bracket). No DOM.getDocument,
    describeNode, frame-tree or second DOMSnapshot request is made here.
    """
    app, document_backend = snapshot_tree(dom, frame_id, commit['meta'].get('root_selector', '#app'))
    strings = dom['strings']
    controls = {}
    for document in dom['documents']:
        if strings[document['frameId']] != frame_id:
            continue
        nodes = document['nodes']; values = nodes.get('inputValue', {'index': [], 'value': []})
        for index, value in zip(values['index'], values['value']):
            controls[nodes['backendNodeId'][index]] = '' if value == -1 else strings[value]
    normalized = normalize(commit, app, snapshot_id=snapshot_id, document_id=str(document_backend),
                           frame_id=frame_id, control_values=controls)
    sources, diagnostics = direct_sources(raw_ax, normalized['runs'], snapshot_id=snapshot_id,
                                          document_id=normalized['document_id'], frame_id=frame_id)
    normalized.update(ax_sources=sources, ax_diagnostics=diagnostics)
    return {'normalized': normalized, 'raw_ax': raw_ax, 'commit': commit,
            'capture_boundary': 'harness-dom-snapshot-v1'}
