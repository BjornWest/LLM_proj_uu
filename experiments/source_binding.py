"""One rule for the code hashes recorded inside generated tasks and worlds.

Generated artifacts record the code they were produced with. By default
('current') a task runs on the one current checkout: declared code is re-hashed
and any drift is returned as provenance, while data-like sources must still
match exactly. TASK_SOURCE_BINDING=pinned restores the exact historical check.
"""
from hashlib import sha256
import os
from pathlib import Path

ENV = 'TASK_SOURCE_BINDING'


def mode():
    value = os.environ.get(ENV, 'current')
    if value not in ('current', 'pinned'):
        raise ValueError('Unknown task source binding: ' + value)
    return value


def data_source(name):
    """Declared sources that are task/world data rather than code stay exact."""
    name = str(name)
    return name.startswith('.local/') or '/data/' in name


def file_sha256(path):
    return sha256(Path(path).read_bytes()).hexdigest()


def check(root, declared, *, error, digest=file_sha256, locate=lambda name: name):
    """Verify declared sources under root; return (current hashes, code drift).

    In pinned mode, or for data-like sources, any mismatch raises
    ValueError(error + name), the loader's historical message.
    """
    root = Path(root).resolve()
    current, drift = {}, []
    pinned = mode() == 'pinned'
    for name, expected in declared.items():
        path = (root/locate(name)).resolve()
        if not path.is_relative_to(root):
            raise ValueError(error + name)
        actual = digest(path) if path.is_file() else None
        if actual != expected:
            if pinned or data_source(name):
                raise ValueError(error + name)
            drift.append({'path': name, 'declared_sha256': expected, 'current_sha256': actual})
        if actual is not None:
            current[name] = actual
    return current, drift


# Identifiers derived from task content: a schema upgrade changes them without
# changing what the task asks or how it is graded.
DERIVED_KEYS = frozenset({'task_id', 'schema_version', 'task_sha256'})


def substantive_changes(saved, rebuilt, path=''):
    """Changed or removed values, ignoring derived identifiers and added fields."""
    if isinstance(saved, dict) and isinstance(rebuilt, dict):
        changes = []
        for key, value in saved.items():
            if key in DERIVED_KEYS:
                continue
            if key not in rebuilt:
                changes.append(path + '/' + key)
            elif key == 'source_sha256' and isinstance(value, dict) and isinstance(rebuilt[key], dict):
                # A nested record of the producing code: only its data entries matter.
                changes += [f'{path}/{key}/{name}' for name in value
                            if data_source(name) and value[name] != rebuilt[key].get(name)]
            else:
                changes += substantive_changes(value, rebuilt[key], path + '/' + key)
        return changes
    if isinstance(saved, list) and isinstance(rebuilt, list) and len(saved) == len(rebuilt):
        return [c for i, (a, b) in enumerate(zip(saved, rebuilt))
                for c in substantive_changes(a, b, f'{path}[{i}]')]
    return [] if saved == rebuilt else [path or '/']


def record(manifest, kind, value):
    manifest.setdefault('source_binding', {'mode': mode()}).setdefault(kind, []).append(value)


def accept_rebuilt(manifest, label, saved, rebuilt):
    """Whether current code's rebuild of a saved task part may replace it."""
    if saved == rebuilt:
        return True
    if mode() == 'pinned' or substantive_changes(saved, rebuilt):
        return False
    record(manifest, 'rebuilt_upgrades', label)
    return True


def accept_asset_drift(manifest, saved, current):
    """Served page assets are code: current mode serves this checkout's copy."""
    if saved == current:
        return True
    if mode() == 'pinned':
        return False
    record(manifest, 'served_asset_drift', sorted(k for k in set(saved) | set(current)
                                                  if saved.get(k) != current.get(k)))
    return True
