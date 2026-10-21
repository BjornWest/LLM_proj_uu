"""File-backed Raven user memory (schema user-memory-v1) shared by episodes and the UI."""
import fcntl
import json
import os
from contextlib import contextmanager
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
FIELDS = {
    'name': {'type': 'string', 'maxLength': 80, 'description': 'What the user likes to be called'},
    'shoe_size_eu': {'type': 'number', 'minimum': 15, 'maximum': 55, 'description': 'Shoe size, EU'},
    'clothing_size': {'type': 'string', 'maxLength': 20, 'description': 'Usual clothing size, e.g. M or 48'},
    'preferred_colours': {'type': 'string', 'maxLength': 120, 'description': 'Colours the user prefers'},
    'delivery_address_city': {'type': 'string', 'maxLength': 80, 'description': 'City for delivery estimates'},
    'budget_note': {'type': 'string', 'maxLength': 200, 'description': 'General budget preference'},
    'preferred_stores': {'type': 'string', 'maxLength': 200, 'description': 'Stores the user likes'},
    'avoid_sites': {'type': 'string', 'maxLength': 200, 'description': 'Sites or sellers to avoid'},
    'dietary_preferences': {'type': 'string', 'maxLength': 120, 'description': 'E.g. vegan, gluten-free'},
    'newsletter_opt_in': {'type': 'string', 'enum': ['never', 'ask', 'yes'],
                          'description': 'Newsletter/marketing sign-ups; default never'},
    'notes': {'type': 'string', 'maxLength': 600, 'description': 'Other durable facts, separated by semicolons'},
}
SEED = {'clothing_size': 'M', 'preferred_colours': 'black, dark blue', 'newsletter_opt_in': 'never'}


def memory_path():
    return Path(os.environ.get('RAVEN_MEMORY_FILE') or ROOT / '.local/raven-memory.json')


class MemoryStore:
    """Adapter for intent_browser.memory: describe/snapshot/update/delete with revision checks."""
    def __init__(self, path=None):
        self.path = Path(path or memory_path())

    @contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path.with_suffix('.lock'), 'w') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def _load(self):
        if not self.path.exists():
            return {'revision': 1, 'values': dict(SEED)}
        data = json.loads(self.path.read_text())
        values = {k: v for k, v in data.get('values', {}).items() if k in FIELDS}
        return {'revision': int(data.get('revision', 1)), 'values': values}

    def _save(self, data):
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1))
        tmp.replace(self.path)

    def describe(self):
        return {'schema_version': 'user-memory-v1', 'fields': json.loads(json.dumps(FIELDS))}

    def snapshot(self):
        with self._locked():
            data = self._load()
            if not self.path.exists():
                self._save(data)
        return {'revision': str(data['revision']), 'values': data['values']}

    def _change(self, key, value, expected_revision, delete=False):
        if key not in FIELDS:
            raise ValueError('Unknown memory field')
        if not delete:
            Draft202012Validator(FIELDS[key]).validate(value)
        with self._locked():
            data = self._load()
            if expected_revision is not None and str(expected_revision) != str(data['revision']):
                from intent_browser.memory import MemoryRejected
                raise MemoryRejected('Stale memory revision; read current memory before deciding again')
            if delete:
                data['values'].pop(key, None)
            else:
                data['values'][key] = value
            data['revision'] += 1
            self._save(data)
        return {'revision': str(data['revision']), 'values': data['values']}

    def update(self, key, value, expected_revision=None):
        return self._change(key, value, expected_revision)

    def delete(self, key, expected_revision=None):
        return self._change(key, None, expected_revision, delete=True)
