"""Public AX snapshots and bounded, isolated standard-library Python calculations.

No browser/DOM eval, hidden state, implicit pagination, type conversion or dedupe.
Docker is an optional execution backend, never replaced by host Python execution.
"""
from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import tempfile
import time
from uuid import uuid4

TOOLS = ('extract_page', 'run_python', 'script_file')


@dataclass(frozen=True)
class DataConfig:
    image: str = 'intent-browser-python:stdlib-v1'
    timeout_seconds: int = 10
    memory_mb: int = 256
    output_bytes: int = 65536
    dataset_bytes: int = 2 * 1024 * 1024
    total_dataset_bytes: int = 16 * 1024 * 1024
    max_datasets: int = 64
    feedback_tokens: int = 1500
    script_workspace: bool = False
    script_bytes: int = 65536
    total_script_bytes: int = 1024 * 1024
    max_scripts: int = 32

    def __post_init__(self):
        if not isinstance(self.image, str) or not self.image or self.image.startswith('-'):
            raise ValueError('Python image must be a trusted local Docker image reference')
        for key, value in asdict(self).items():
            if key == 'script_workspace':
                if type(value) is not bool: raise ValueError('script_workspace must be boolean')
            elif key != 'image' and (type(value) is not int or value <= 0):
                raise ValueError(f'{key} must be a positive integer')

    def describe(self):
        return {'version': 'public-data-python-v2-scripts' if self.script_workspace else 'public-data-python-v1', **asdict(self),
                'runtime': 'Docker; no automatic pulls or host-execution fallback',
                'isolation': 'no network, no host mounts, unprivileged, read-only root, ephemeral tmpfs',
                'data_scope': 'full public semantic AX subtree from current capture; no implicit pagination',
                'packages': 'Python standard library; independent process per call',
                'limits_scope': 'byte caps bound storage/transport; feedback_tokens bounds tool feedback'}


BOOTSTRAP = '''import json, sys, traceback
payload = json.load(sys.stdin)
scope = {"__name__": "__main__", "datasets": payload["datasets"]}
try:
    exec(compile(payload["code"], "agent_script.py", "exec"), scope)
except Exception:
    traceback.print_exc()
    sys.exit(1)
'''


class DockerPython:
    def __init__(self, config): self.config = config

    def run(self, code, datasets):
        cfg = self.config
        # Resolve once per call, then run the immutable ID, not a mutable tag.
        try:
            inspected = subprocess.run(['docker', 'image', 'inspect', cfg.image, '--format', '{{.Id}}'],
                capture_output=True, text=True, timeout=5, check=True)
            image = inspected.stdout.strip()
            if not re.fullmatch(r'sha256:[0-9a-f]{64}', image):
                raise ValueError('Unexpected Python image identity')
        except (OSError, ValueError, subprocess.SubprocessError):
            return {'execution': 'unavailable', 'error': 'Python sandbox unavailable. Install/configure the trusted local image and Docker; no script was executed.',
                    'stdout': '', 'stderr': '', 'exit_code': None}
        name = 'intent-calc-' + uuid4().hex
        command = ['docker', 'run', '--pull=never', '--rm', '-i', '--name', name,
            '--network=none', '--read-only', '--user=65534:65534', '--cap-drop=ALL',
            '--security-opt=no-new-privileges', '--memory='+str(cfg.memory_mb)+'m',
            '--memory-swap='+str(cfg.memory_mb)+'m', '--cpus=1', '--pids-limit=16',
            '--ulimit=nofile=64:64', '--log-driver=none',
            '--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777', '--workdir=/tmp',
            '--entrypoint=python3', image, '-I', '-S', '-u', '-c', BOOTSTRAP]
        chunks = {'stdout': bytearray(), 'stderr': bytearray()}
        stop = None; process = None; started = time.monotonic(); cleanup_error = None
        try:
            # A bounded input file avoids blocking a pipe write before draining output.
            with tempfile.TemporaryFile() as incoming:
                incoming.write(json.dumps({'code': code, 'datasets': datasets}, ensure_ascii=False).encode())
                incoming.seek(0)
                process = subprocess.Popen(command, stdin=incoming, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                with selectors.DefaultSelector() as selector:
                    for label, stream in [('stdout', process.stdout), ('stderr', process.stderr)]:
                        os.set_blocking(stream.fileno(), False)
                        selector.register(stream, selectors.EVENT_READ, label)
                    while selector.get_map():
                        if time.monotonic() - started >= cfg.timeout_seconds:
                            stop = 'timeout'; break
                        for key, _ in selector.select(timeout=.05):
                            chunk = os.read(key.fd, 8192)
                            if not chunk:
                                selector.unregister(key.fileobj); continue
                            target = chunks[key.data]
                            remaining = cfg.output_bytes - len(target)
                            target.extend(chunk[:remaining])
                            if len(chunk) > remaining:
                                stop = 'output_limit'; break
                        if stop: break
                if not stop:
                    process.wait(timeout=max(.01, cfg.timeout_seconds-(time.monotonic()-started)))
        except subprocess.TimeoutExpired:
            stop = 'timeout'
        except OSError:
            stop = 'sandbox_transport_error'
        finally:
            if process is not None:
                if process.poll() is None: process.kill()
                process.wait()
                process.stdout.close(); process.stderr.close()
            # No model-created processes or writable state survive a call.
            try:
                cleanup = subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=5)
                if cleanup.returncode and b'No such container' not in cleanup.stderr:
                    cleanup_error = 'Container cleanup could not be confirmed'
            except (OSError, subprocess.SubprocessError):
                cleanup_error = 'Container cleanup could not be confirmed'
        exit_code = process.returncode if process is not None else None
        error = cleanup_error or stop or ('python_error' if exit_code != 0 else None)
        return {'execution': 'failed' if error else 'completed', 'error': error,
                'exit_code': exit_code, 'sandbox_image_id': image, 'seconds': time.monotonic()-started,
                'output_truncated': stop == 'output_limit',
                **{key: bytes(value).decode('utf-8', errors='replace') for key, value in chunks.items()}}


def subtree(explorer, root):
    result = []; todo = [root]
    while todo:
        index = todo.pop(); result.append(index)
        todo.extend(reversed(explorer.nodes[index]['children']))
    return result


def extract(explorer, ref, format, verbose=None):
    verbose = explorer.config.verbose if verbose is None else verbose
    root = explorer.resolve(ref)
    indices = subtree(explorer, root)
    def node(index):
        n = explorer.nodes[index]
        value = {'ref': explorer.ref(index), 'role': n['role'], 'name': n['name'], 'value': n['value'],
                 'state': deepcopy(n['properties']), 'children': [explorer.ref(i) for i in n['children']],
                 'parent': explorer.ref(n['parent']) if n['parent'] is not None else None}
        if n['bid'] is not None: value['bid'] = n['bid']
        if verbose:
            value['metadata'] = {key: n[key] for key in ('raw_node_id', 'backend_identity', 'frame_identity')}
        return value
    result = {'format': format, 'url': explorer.url, 'snapshot': explorer.snapshot, 'ref': ref,
              'coverage': 'Only the selected captured semantic AX subtree. Off-page, unloaded, hidden and other pagination content are not included.',
              'nodes': [node(i) for i in indices]}
    if format == 'text':
        # Explicit node boundaries rather than ambiguous recursive text concatenation.
        result['text'] = '\n'.join(json.dumps({k: node(i)[k] for k in ('ref', 'role', 'name', 'value')},
                                             ensure_ascii=False) for i in indices)
    elif format == 'table':
        if explorer.nodes[root]['role'] not in ('table', 'grid', 'treegrid'):
            raise ValueError('Selected node is not an accessible table/grid; select the table itself or use tree/text.')
        if any(explorer.nodes[i]['role'] in ('table','grid','treegrid') for i in indices[1:]):
            raise ValueError('Nested tables are ambiguous; extract an inner table or use tree/text.')
        header_rows = []; rows = []; row_refs = []; cell_refs = []; header_refs = []
        for i in indices:
            if explorer.nodes[i]['role'] != 'row': continue
            cells = [j for j in subtree(explorer, i)[1:] if explorer.nodes[j]['role'] in
                     ('cell', 'gridcell', 'columnheader', 'rowheader')]
            if not cells: raise ValueError('A row has no accessible cells; use tree/text rather than infer column boundaries.')
            values = []
            for j in cells:
                # Accessible names are browser-computed strings, never numeric conversions.
                n = explorer.nodes[j]
                if n['name']: value = n['name']
                elif n['value']: value = n['value']
                elif any(explorer.nodes[k]['name'] or explorer.nodes[k]['value'] for k in subtree(explorer,j)[1:]):
                    raise ValueError('A cell lacks an accessible name/value but has content; use tree/text to inspect descendants.')
                else: value = ''
                values.append(value)
            refs = [explorer.ref(j) for j in cells]
            if all(explorer.nodes[j]['role'] == 'columnheader' for j in cells):
                header_rows.append(values); header_refs.append(refs)
            else:
                rows.append(values); row_refs.append(explorer.ref(i)); cell_refs.append(refs)
        if not rows and not header_rows:
            raise ValueError('No accessible rows found; use tree/text.')
        # Ordered arrays preserve duplicate headers, ragged rows and literal values.
        result.update(columns=header_rows[0] if len(header_rows)==1 else None,
                      header_rows=header_rows, header_refs=header_refs, rows=rows,
                      row_refs=row_refs, cell_refs=cell_refs,
                      table_note='Ordered cell strings; no type inference, merged-cell expansion or deduplication. Multiple header rows leave columns=null. Inspect node state for spans/indices.')
    elif format != 'tree':
        raise ValueError('Unknown extraction format')
    return result


class DataSession:
    def __init__(self, config, directory, explorer):
        self.config, self.directory, self.explorer = config, Path(directory), explorer
        self.datasets = {}; self.bytes = 0
        self.executor = DockerPython(config)
        from .script_workspace import ScriptWorkspace
        self.scripts = ScriptWorkspace(directory, max_bytes=config.script_bytes,
            total_bytes=config.total_script_bytes, max_files=config.max_scripts) if config.script_workspace else None

    def checkpoint_state(self):
        return {'datasets': deepcopy(self.datasets), 'bytes': self.bytes,
                'scripts': self.scripts.checkpoint_state() if self.scripts is not None else None}

    def restore_state(self, state, prefix='inherited/'):
        self.datasets = deepcopy(state['datasets']); self.bytes = state['bytes']
        for binding in self.datasets.values(): binding['path'] = prefix + binding['path']
        if state.get('scripts') is not None:
            if self.scripts is None: raise ValueError('Checkpoint requires script workspace support')
            self.scripts.restore_state(state['scripts'], prefix)

    def bounded_feedback(self, value):
        result = deepcopy(value)
        tokens = self.explorer.tokenizer
        def count(): return len(tokens.encode(json.dumps(result, ensure_ascii=False), add_special_tokens=False).ids)
        # Only presentation previews/output are shortened; artifact data stays exact.
        for field in ('preview', 'stdout', 'stderr', 'content', 'old_string', 'new_string'):
            if count() <= self.config.feedback_tokens: break
            if field not in result: continue
            text = result[field] if isinstance(result[field], str) else json.dumps(result[field], ensure_ascii=False)
            ids = tokens.encode(text, add_special_tokens=False).ids
            while count() > self.config.feedback_tokens and ids:
                ids = ids[:len(ids)//2]
                result[field] = tokens.decode(ids, skip_special_tokens=False)
                result['feedback_truncated'] = True
                if field == 'content':
                    result['next_line'] = None
                    result['view_note'] = 'View was shortened for feedback; reread this start_line with a smaller limit. Exact file is retained.'
        if count() > self.config.feedback_tokens:
            return {'error': 'Feedback metadata exceeds token budget; inspect a smaller extraction.', 'artifact': result.get('artifact')}
        return result

    def execute(self, name, arguments, index, observation_ref=None, no_browser=False):
        from .trace import write_json
        artifact = f'data-result-{index:03d}.json'
        try:
            if name == 'extract_page':
                if no_browser: raise ValueError('No browser assigned; extraction unavailable. Python can still process supplied literals.')
                value = extract(self.explorer, **arguments)
                data = json.dumps(value, ensure_ascii=False).encode()
                if (len(data) > self.config.dataset_bytes or self.bytes+len(data) > self.config.total_dataset_bytes
                        or len(self.datasets) >= self.config.max_datasets):
                    raise ValueError('Extraction storage limit exceeded; narrow the subtree. No partial dataset was saved.')
                key = f'data{len(self.datasets)+1}'
                path = f'dataset-{key}.json'
                # Hash the exact immutable bytes handed to Python, including provenance.
                value['source_observation'] = deepcopy(observation_ref)
                data = json.dumps(value, ensure_ascii=False).encode()
                if len(data)>self.config.dataset_bytes or self.bytes+len(data)>self.config.total_dataset_bytes:
                    raise ValueError('Extraction storage limit exceeded; narrow the subtree.')
                (self.directory/path).write_bytes(data)
                self.datasets[key] = {'path': path, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
                self.bytes += len(data)
                result = {'tool': name, 'execution': 'completed', 'dataset_id': key, **self.datasets[key],
                    'format': value['format'], 'coverage': value['coverage'],
                    'node_count': len(value['nodes']), 'artifact': path,
                    'preview': (value['rows'][:2] if 'rows' in value else value['nodes'][:2])}
                if 'rows' in value: result.update(row_count=len(value['rows']), columns=value['columns'])
            elif name == 'run_python':
                selected = {}
                for key in arguments.get('datasets', []):
                    if key not in self.datasets: raise ValueError(f'Unknown dataset ID: {key}')
                    binding = self.datasets[key]; data = (self.directory/binding['path']).read_bytes()
                    if hashlib.sha256(data).hexdigest() != binding['sha256']:
                        raise ValueError('Dataset artifact changed; execution refused')
                    selected[key] = json.loads(data)
                has_code, has_file = 'code' in arguments, 'file_path' in arguments
                if has_code == has_file: raise ValueError('Supply exactly one of code or file_path.')
                binding = None
                if has_file:
                    if self.scripts is None: raise ValueError('Script workspace is disabled in this profile.')
                    if 'expected_revision' not in arguments: raise ValueError('Saved script execution requires expected_revision from create/view/edit.')
                    code, binding = self.scripts.read(arguments['file_path'], arguments['expected_revision'])
                else:
                    if 'expected_revision' in arguments: raise ValueError('expected_revision requires file_path.')
                    code = arguments['code']
                script = f'python-{index:03d}.py'
                with (self.directory/script).open('x', encoding='utf-8') as output: output.write(code)
                result = {'tool': name, **self.executor.run(code, selected), 'script': script,
                    'datasets': {key: self.datasets[key] for key in selected}, 'artifact': artifact,
                    'scope': 'Script output is an agent calculation, not independently verified task success.'}
                if binding is not None: result['saved_script'] = binding
            elif name == 'script_file':
                if self.scripts is None: raise ValueError('Script workspace is disabled in this profile.')
                result = {'tool': name, 'execution': 'completed', **self.scripts.execute(**arguments), 'artifact': artifact}
            else: raise ValueError('Unknown data tool')
        except (ValueError, KeyError) as exc:
            result = {'tool': name, 'execution': 'failed', 'error': str(exc), 'artifact': artifact}
        except OSError:
            result = {'tool': name, 'execution': 'failed',
                'error': 'Script/data artifact unavailable or write conflict; no automatic execution retry.', 'artifact': artifact}
        write_json(self.directory/artifact, result)
        return self.bounded_feedback(result), artifact
