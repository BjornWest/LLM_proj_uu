"""Sequential native-call batches. Public evidence only; no action replay."""
from copy import deepcopy
from playwright.sync_api import Error as PlaywrightError
from .feedback_presentation import present_action_error


class DocumentScanInvalidated(RuntimeError):
    """A read-only guard lost its frame/document; no action should be dispatched."""
    def __init__(self, detail):
        super().__init__('Browser document changed during batch guard')
        self.detail = detail


def interrupted_step_feedback(record, error):
    """Dispatch without a returned observation never establishes non-execution."""
    execution=record.get('action_execution')
    status='failed_effects_unknown'
    if execution is not None:
        status=('action_failed_observation_unavailable' if execution['action_error']
                else 'action_completed_observation_unavailable')
    return {'execution':status,'error':str(error),'observation':'unavailable',
        'action_error':execution['action_error'] if execution is not None else None,
        'instruction':'The action was dispatched and may have changed the site. '
            'Do not repeat it automatically; inspect fresh state before deciding what to do.'}


def document_signature(env, *, active_only=False):
    """Conservatively stop across tab, frame, URL or document replacement.

    Frame evaluation yields to browser events: a child or secondary tab may
    disappear even though the active page is healthy. Never treat a partial
    scan as a matching signature, and never retry an action here.
    """
    page = env.unwrapped.page
    context = page.context
    def require_active_page():
        if page.is_closed() or (context.browser is not None and not context.browser.is_connected()):
            raise PlaywrightError('Batch guard: active page or browser has been closed')
    require_active_page()
    pages = [page] if active_only else list(context.pages)
    topology = [(p, list(p.frames)) for p in pages]
    signature = []
    for pi, (p, frames) in enumerate(topology):
        values = []
        for fi, f in enumerate(frames):
            try:
                value = f.evaluate('() => [location.href, performance.timeOrigin]')
            except PlaywrightError as exc:
                detail = {'page_index': pi, 'frame_index': fi,
                          'active_page': p is page, 'main_frame': f is p.main_frame,
                          'frame_detached': f.is_detached(), 'page_closed': p.is_closed(),
                          'error': f'{type(exc).__name__}: {exc}'}
                # Retain the exact diagnostic even on fatal failures. Do not
                # downgrade browser/active-page closure or unrelated JS errors.
                exc.document_scan_detail = detail
                browser = context.browser
                active_alive = not page.is_closed() and (browser is None or browser.is_connected())
                message = str(exc).lower()
                context_lost = any(s in message for s in (
                    'execution context was destroyed', 'cannot find context with specified id',
                    'frame was detached', 'frame has been detached',
                    'target page, context or browser has been closed'))
                # A closed main target is not evidence of a child-frame race.
                child_or_other_page = p is not page or f is not page.main_frame
                if active_alive and context_lost and (
                        child_or_other_page or 'execution context was destroyed' in message):
                    raise DocumentScanInvalidated(detail) from exc
                raise
            values.append((id(f), value))
        signature.append((id(p), values))
    require_active_page()
    if (not active_only and pages != list(context.pages)) or any(frames != list(p.frames) for p, frames in topology):
        raise DocumentScanInvalidated({'reason': 'frame_or_tab_set_changed_during_scan'})
    return signature


def target_signature(observation, bid):
    nodes = observation['axtree_object'].get('nodes', [])
    # Chrome can repeat identical native-option records in a flat AX capture.
    # Only collapse copies of the same AX node; conflicting records remain unsafe.
    by_id, conflicts = {}, set()
    for node in nodes:
        node_id = node['nodeId']
        if node_id in by_id and by_id[node_id] != node:
            conflicts.add(node_id)
        else:
            by_id[node_id] = node
    parents = {child: n['nodeId'] for n in by_id.values() for child in n.get('childIds', [])}
    matches = {n['nodeId'] for n in nodes if n.get('browsergym_id') == bid and not n.get('ignored')}
    if len(matches) != 1: return None
    n = by_id[next(iter(matches))]; chain = []; visited = set()
    while n['nodeId'] not in visited:
        if n['nodeId'] in conflicts: return None
        visited.add(n['nodeId'])
        chain.append((n.get('backendDOMNodeId'), n.get('frameId'),
                      n.get('role', {}).get('value'), n.get('name', {}).get('value')))
        if n['nodeId'] not in parents: break
        n = by_id[parents[n['nodeId']]]
    return chain


def batch_result(raw, positioning=None):
    """Per-call execution status; page diffs/events are consolidated elsewhere."""
    result = {k: deepcopy(raw[k]) for k in ('tool', 'execution', 'error', 'timeout_context') if k in raw}
    present_action_error(result)
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
