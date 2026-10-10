"""Episode-local Python source files; exact edits and immutable trace versions."""
from copy import deepcopy
import hashlib
from pathlib import Path
import re


class ScriptWorkspace:
    def __init__(self, directory, *, max_bytes=65536, total_bytes=1024*1024, max_files=32):
        self.directory = Path(directory)
        self.max_bytes, self.total_bytes, self.max_files = max_bytes, total_bytes, max_files
        self.files = {}
        self.bytes = 0  # All retained versions count, not just current files.

    def read(self, file_path, expected_revision=None):
        if not isinstance(file_path, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\.py', file_path):
            raise ValueError('Use a simple episode-local Python filename, e.g. analysis.py; no directories.')
        if file_path not in self.files:
            raise ValueError('Unknown script filename; create it first.')
        binding = self.files[file_path]
        if expected_revision is not None and expected_revision != binding['revision']:
            raise ValueError('Script revision changed; view the file before editing or executing it.')
        data = (self.directory / binding['path']).read_bytes()
        if hashlib.sha256(data).hexdigest() != binding['sha256'] or len(data) != binding['bytes']:
            raise ValueError('Script artifact changed; operation refused.')
        return data.decode('utf-8'), deepcopy(binding)

    def _save(self, file_path, text, previous=None):
        data = text.encode('utf-8')
        if len(data) > self.max_bytes or self.bytes + len(data) > self.total_bytes:
            raise ValueError('Script storage limit exceeded; no change saved.')
        if previous is None and len(self.files) >= self.max_files:
            raise ValueError('Script file count limit exceeded; no change saved.')
        version = (previous['version'] if previous else 0) + 1
        digest = hashlib.sha256(data).hexdigest()
        path = f'script-{file_path}-v{version:03d}.py'
        # Existing evidence is never overwritten, including competing writers.
        with (self.directory / path).open('xb') as output:
            output.write(data)
        binding = {'file_path': file_path, 'version': version, 'revision': f'v{version}:{digest}',
                   'path': path, 'sha256': digest, 'bytes': len(data)}
        self.files[file_path] = binding
        self.bytes += len(data)
        return deepcopy(binding)

    def execute(self, command, file_path, **args):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,79}\.py', file_path):
            raise ValueError('Use a simple episode-local Python filename, e.g. analysis.py; no directories.')
        if command == 'create':
            if file_path in self.files:
                raise ValueError('Script already exists; view and edit it instead of overwriting.')
            if set(args) != {'content'}:
                raise ValueError('create requires only content.')
            return {**self._save(file_path, args['content']), 'operation': 'created'}
        text, previous = self.read(file_path, args.get('expected_revision'))
        if command == 'view':
            if set(args) - {'start_line', 'limit'}:
                raise ValueError('view accepts start_line and limit only.')
            start, limit = args.get('start_line', 1), args.get('limit', 40)
            if type(start) is not int or start < 1 or type(limit) is not int or not 1 <= limit <= 100:
                raise ValueError('start_line must be positive; limit must be between 1 and 100.')
            lines = text.splitlines()
            selected = lines[start-1:start-1+limit]
            next_line = start + len(selected)
            return {**previous, 'operation': 'viewed', 'line_count': len(lines),
                    'start_line': start, 'content': '\n'.join(f'{start+i}: {line}' for i, line in enumerate(selected)),
                    'next_line': next_line if next_line <= len(lines) else None}
        if command != 'edit':
            raise ValueError('Unknown script command.')
        if set(args) - {'expected_revision', 'old_string', 'new_string', 'replace_all'} or not {
                'expected_revision', 'old_string', 'new_string'} <= set(args):
            raise ValueError('edit requires expected_revision, old_string and new_string.')
        old, new = args['old_string'], args['new_string']
        if not old or old == new:
            raise ValueError('old_string must be nonempty and differ from new_string.')
        count = text.count(old)
        if not count:
            raise ValueError('old_string not found exactly; view the relevant lines and preserve whitespace.')
        if count != 1 and not args.get('replace_all', False):
            raise ValueError(f'old_string matches {count} times; include more context or explicitly use replace_all.')
        updated = text.replace(old, new, -1 if args.get('replace_all', False) else 1)
        return {**self._save(file_path, updated, previous), 'operation': 'edited',
                'previous_revision': previous['revision'], 'replacements': count if args.get('replace_all', False) else 1,
                'old_string': old, 'new_string': new}

    def checkpoint_state(self):
        return {'files': deepcopy(self.files), 'bytes': self.bytes}

    def restore_state(self, state, prefix='inherited/'):
        self.files = deepcopy(state['files'])
        self.bytes = state['bytes']
        for binding in self.files.values():
            binding['path'] = prefix + binding['path']
        for file_path in self.files:
            self.read(file_path)  # Verify inherited bytes before exposing the workspace.
