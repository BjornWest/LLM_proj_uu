"""Conservative offline projection from captured DOM runs to raw CDP AX fields.

Only direct StaticText names and actual control values are supported. Equality
validates an already identified backend node; it never relocates repeated text.
Render/source/state provenance must be validated by the capture normalizer first.
"""
from .fact_exposure import digest, indexed, object_digest, require, utf16_length, utf16_slice, coverage

TEXT_ROLES = {'StaticText', 'InlineTextBox'}
VALUE_ROLES = {'textbox', 'combobox', 'spinbutton', 'slider', 'searchbox'}


def direct_sources(nodes, runs, *, snapshot_id, document_id, frame_id):
    """Return mapped AX sources and per-run diagnostics; unsupported stays absent."""
    require(all(isinstance(v, str) and v for v in (snapshot_id, document_id, frame_id)), 'Scoped capture identity required')
    ax = {}
    for node in nodes:
        key = str(node['nodeId'])
        record = dict(node, id=key)
        require(key not in ax or ax[key] == record, 'Conflicting duplicate AX node')
        ax[key] = record
    parents = {}
    for node in ax.values():
        for child in node.get('childIds', []):
            child = str(child)
            require(child not in parents or parents[child] == node['id'], 'Ambiguous AX parent')
            parents[child] = node['id']

    def effective_frame(node_id):
        seen = set()
        while node_id in ax:
            require(node_id not in seen, 'Cyclic AX parent relation')
            seen.add(node_id)
            node = ax[node_id]
            if node.get('frameId'):
                return node['frameId']
            node_id = parents.get(node_id)
        return None

    sources, diagnostics = [], []
    for run in indexed(runs, 'DOM run').values():
        require(run['kind'] in ('text_node', 'control_value'), 'Supported explicit DOM run kind required')
        require(isinstance(run['text'], str) and digest(run['text']) == run['sha256'], 'DOM run hash mismatch')
        require(type(run['backend_node_id']) is int and run['backend_node_id'] > 0, 'Actual backend node identity required')
        field = 'name' if run['kind'] == 'text_node' else 'value'
        roles = TEXT_ROLES if field == 'name' else VALUE_ROLES
        matches = [node for node in ax.values() if node.get('backendDOMNodeId') == run['backend_node_id']
                   and not node.get('ignored', False) and effective_frame(node['id']) == frame_id
                   and node.get('role', {}).get('value') in roles
                   and node.get(field, {}).get('value') == run['text']]
        if len(matches) != 1:
            diagnostics.append(dict(run_id=run['id'], reason='unsupported_or_ambiguous_direct_ax_binding', matches=len(matches)))
            continue
        node = matches[0]
        sources.append(dict(id=run['id'], text=run['text'], sha256=run['sha256'],
                            binding=dict(snapshot_id=snapshot_id, document_id=document_id, frame_id=frame_id,
                                         node_id=node['id'], field=field)))
    return sources, diagnostics


def scripted_ranges(sources, selections):
    """Freeze actual selected AX slices without pretending to make model calls.

    Outputs and exact projection maps are explicit. Repeated/overlapping reads
    union later; callers retain selections for audit and must attest completeness.
    """
    source_map = indexed(sources, 'AX source')
    outputs, ranges = [], {sid: [] for sid in source_map}
    for i, selection in enumerate(selections):
        source = source_map[selection['source_id']]
        fragment = utf16_slice(source['text'], selection['start'], selection['end'])
        outputs.append(dict(id=f'scripted-selection-{i}', scope='scripted_context_selection',
                            text=fragment, sha256=digest(fragment), source_id=source['id'],
                            source_sha256=source['sha256'], binding_sha256=object_digest(source['binding']),
                            source_start=selection['start'], source_end=selection['end'],
                            output_start=0, output_end=utf16_length(fragment)))
        ranges[source['id']].append((selection['start'], selection['end']))
    return outputs, ranges


def part_coverage(spans, source_map, ranges, *, inventory_complete):
    """Conjunctive spans; missing source yields unknown even if other text arrived."""
    if not spans or any(span['source_id'] not in source_map for span in spans):
        return dict(status='unknown', observed_utf16_fraction=None, reason='unsupported_source_projection')
    total = observed = 0
    for span in spans:
        source = source_map[span['source_id']]
        utf16_slice(source['text'], span['start'], span['end'])
        total += span['end'] - span['start']
        observed += coverage(ranges.get(span['source_id'], []), span['start'], span['end'])
    status = ('complete' if observed == total else 'partial' if observed else
              'unseen' if inventory_complete else 'unknown')
    return dict(status=status, observed_utf16_fraction=observed/total if status != 'unknown' else None)
