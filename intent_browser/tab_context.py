"""Append-only tab snapshot/deltas; rendering alone never acknowledges delivery."""
from copy import deepcopy
import hashlib
import json


class TabContext:
    def __init__(self):
        self.previous = None
        self.event_sequence = -1

    @staticmethod
    def state(snapshot):
        return {'active_tab_id': snapshot['active_tab_id'],
                'tabs': {t['tab_id']: deepcopy(t) for t in snapshot['tabs']}}

    @staticmethod
    def identity(state):
        return 'tabs-' + hashlib.sha256(json.dumps(state, sort_keys=True,
            ensure_ascii=False).encode()).hexdigest()[:16]

    def project(self, snapshot):
        state = self.state(snapshot)
        result = {'id': self.identity(state)}
        if self.previous is None:
            result.update(kind='snapshot', **state)
        elif state == self.previous:
            result['kind'] = 'unchanged'
        else:
            old = self.previous
            result.update(kind='delta', base=self.identity(old))
            if state['active_tab_id'] != old['active_tab_id']:
                result['active_tab_id'] = state['active_tab_id']
            changes = {}
            for key, tab in state['tabs'].items():
                if key not in old['tabs']:
                    changes[key] = tab
                else:
                    diff = {k: v for k, v in tab.items() if old['tabs'][key].get(k) != v}
                    if diff: changes[key] = diff
            if changes: result['set'] = changes
            removed = sorted(set(old['tabs']) - set(state['tabs']))
            if removed: result['removed'] = removed
        events = [e for e in snapshot.get('recent_transitions', [])
                  if e['sequence'] > self.event_sequence]
        if events: result['events'] = deepcopy(events)
        return result

    def commit(self, snapshot):
        """Commit only when this snapshot enters constructed conversation history."""
        projected = self.project(snapshot)
        self.previous = self.state(snapshot)
        for event in snapshot.get('recent_transitions', []):
            self.event_sequence = max(self.event_sequence, event['sequence'])
        return projected
