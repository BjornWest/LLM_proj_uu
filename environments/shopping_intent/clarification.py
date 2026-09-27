"""Typed targeted-response stub, not an NLP user simulator or a question reward."""
import copy


def answer_clarification(bundle, line_id, field):
    spec = next((s for s in bundle['hidden_user_specifications']
                 if s['line_id'] == line_id and s['predicate']['field'] == field), None)
    if spec is None:
        return {'matched': False, 'reply': None}
    return {'matched': True, 'reply': spec['reply']}


def task_after_clarifications(bundle, revealed):
    """A trusted interaction log supplies (line_id, field) pairs, never the policy."""
    task = copy.deepcopy(bundle['initial_accessible_task'])
    for spec in bundle['hidden_user_specifications']:
        if (spec['line_id'], spec['predicate']['field']) in revealed:
            line = next(l for l in task['lines'] if l['id'] == spec['line_id'])
            line['requirements'].append({**copy.deepcopy(spec['predicate']),
                                         'source': {'kind': 'clarification', 'id': spec['id']}})
            line['requirements'].sort(key=lambda p: (p['field'], p['operator']))
    return task
