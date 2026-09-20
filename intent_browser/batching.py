"""Sequential native-call batches. Public evidence only; no action replay."""
from copy import deepcopy


def document_signature(env):
    """Conservatively stop across tab, frame, URL or document replacement."""
    page = env.unwrapped.page
    return [(id(p), [(id(f), f.evaluate('() => [location.href, performance.timeOrigin]'))
                     for f in p.frames]) for p in page.context.pages]


def target_signature(observation, bid):
    nodes = observation['axtree_object'].get('nodes', [])
    by_id = {n['nodeId']: n for n in nodes}
    parents = {child: n['nodeId'] for n in nodes for child in n.get('childIds', [])}
    matches = [n for n in nodes if n.get('browsergym_id') == bid and not n.get('ignored')]
    if len(matches) != 1: return None
    n = matches[0]; chain = []; visited = set()
    while n['nodeId'] not in visited:
        visited.add(n['nodeId'])
        chain.append((n.get('backendDOMNodeId'), n.get('frameId'),
                      n.get('role', {}).get('value'), n.get('name', {}).get('value')))
        if n['nodeId'] not in parents: break
        n = by_id[parents[n['nodeId']]]
    return chain


def batch_result(raw, positioning=None):
    """Per-call execution status; page diffs/events are consolidated elsewhere."""
    result = {k: deepcopy(raw[k]) for k in ('tool', 'execution', 'error', 'timeout_context') if k in raw}
    if positioning is not None: result['positioning'] = deepcopy(positioning)
    return result


def batch_events(records):
    """Retain transient events across all calls, with explicit call attribution.

    AX content is supplied once by the next fresh observation, never by each
    before/after delta. Existing common presentation budgets apply to this union.
    """
    events, warnings, omitted = [], [], 0
    for record in records:
        raw = record.get('_batch_feedback')
        if raw is None: continue
        preceding = raw.get('between_decision_and_action', {})
        for event in [*preceding.get('events', []), *raw.get('page_events', [])]:
            events.append({**deepcopy(event), 'batch_call':record['batch_call']})
        omitted += raw.get('page_events_omitted', 0) + preceding.get('omitted', 0)
        warnings += raw.get('event_capture', {}).get('warnings', []) + preceding.get('capture_warnings', [])
    return {'events':events, 'omitted':omitted, 'capture_warnings':warnings}
