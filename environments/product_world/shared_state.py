"""Read-only JSON trees and small, operation-owned sampling contexts.

These retain dict/list compatibility for the existing expression interpreter and
JSON encoder. They enforce normal mutation APIs, not a sandbox against code
deliberately invoking dict.__setitem__ or list.append on their base classes.
"""
import json

from .product_expressions import ExpressionError, get_path, unresolved


def _readonly(*args, **kwargs):
    raise TypeError('Shared sampling data is read-only')


class FrozenDict(dict):
    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _readonly
    __ior__ = _readonly

    def __init__(self, *args, **kwargs):
        # Construction is private to freeze; prohibit reinitializing an instance.
        if hasattr(self, '_sealed'):
            _readonly()
        dict.__init__(self, *args, **kwargs)
        self._sealed = True

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self


class FrozenList(list):
    __setitem__ = __delitem__ = append = extend = insert = pop = remove = clear = sort = reverse = _readonly
    __iadd__ = __imul__ = _readonly

    def __init__(self, *args):
        if hasattr(self, '_sealed'):
            _readonly()
        list.__init__(self, *args)
        self._sealed = True

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        return self


def freeze(value):
    """Freeze newly owned nodes once; already frozen branches remain shared.

    Status, tuple and set normalization matches the existing JSON wire format.
    Source documents and sampled entities contain only JSON-compatible values.
    """
    if isinstance(value, (FrozenDict, FrozenList)):
        return value
    if unresolved(value):
        return FrozenDict(status=value.reason)
    if isinstance(value, dict):
        return FrozenDict((k, freeze(v)) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return FrozenList(freeze(v) for v in value)
    if isinstance(value, set):
        return FrozenList(sorted((freeze(v) for v in value), key=lambda v: json.dumps(v, sort_keys=True)))
    return value


def mutable(value):
    """Explicit external boundary: produce an independently editable JSON tree."""
    if isinstance(value, dict):
        return {k: mutable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [mutable(v) for v in value]
    return value


class WorkingContext:
    """Owned root, shared read-only descendants, path copies on writes.

    Emitted arrays belong to this context and grow in place. Their entries are
    frozen, and the array itself becomes read-only at completion.
    """
    def __init__(self, shared=None):
        self.root = dict(freeze(shared or {}))
        self._arrays = {}

    def _parent(self, path):
        names = path.split('.')
        current = self.root
        for name in names[:-1]:
            existing = current.get(name, {})
            if not isinstance(existing, dict):
                raise ExpressionError(f'Cannot write through scalar {path}')
            branch = dict(existing)
            current[name] = branch
            current = branch
        return current, names[-1]

    def set(self, path, value):
        parent, name = self._parent(path)
        parent[name] = freeze(value)

    def append(self, path, value):
        rows = get_path(self.root, path)
        if unresolved(rows):
            rows = []
        elif self._arrays.get(id(rows)) is not rows:
            rows = list(rows)
        self._arrays[id(rows)] = rows
        parent, name = self._parent(path)
        parent[name] = rows
        rows.append(freeze(value))

    def finish(self):
        return freeze(self.root)
