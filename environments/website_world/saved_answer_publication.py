"""Fresh saved-answer containers; no manufacture or edits to the saved recipe."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath

from experiments.accepted_catalog_commerce.execution import Execution, _bind
from . import generation as shared
from .adapter import ROOT

VERSION = 'website-saved-answer-publication-v1'


def file_hash(path):
    h = sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read_recipe(saved, *, expected_manifest_sha256):
    saved = Path(saved).resolve()
    payload = (saved/'manifest.json').read_bytes()
    if sha256(payload).hexdigest() != expected_manifest_sha256:
        raise ValueError('Saved recipe manifest changed')
    manifest = json.loads(payload)
    if type(manifest.get('files')) is not dict or not manifest['files']:
        raise ValueError('Saved recipe lacks file bindings')
    buffers = {}
    for name, expected in manifest['files'].items():
        relative = PurePosixPath(name)
        path = saved/name
        if (relative.is_absolute() or str(relative) != name or '..' in relative.parts
                or '\\' in name or path.is_symlink()
                or not path.resolve().is_relative_to(saved)):
            raise ValueError('Saved recipe file changed or escaped: '+name)
        payload = path.read_bytes()
        if sha256(payload).hexdigest() != expected:
            raise ValueError('Saved recipe file changed: '+name)
        buffers[name] = payload
    return saved, manifest, buffers


def declared_sources(*records):
    """Collect every native dependency map, including nested task/reference rows."""
    result = {}
    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key in ('source_sha256', 'field_source_sha256'):
                    if type(child) is not dict:
                        raise ValueError('Saved native input dependency map changed: '+key)
                    for name, expected in child.items():
                        if type(name) is not str or type(expected) is not str:
                            raise ValueError('Malformed saved native dependency')
                        relative = PurePosixPath(name)
                        path = (ROOT/name).resolve()
                        if (relative.is_absolute() or str(relative) != name or '..' in relative.parts
                                or '\\' in name or not path.is_relative_to(ROOT)
                                or len(expected) != 64 or any(c not in '0123456789abcdef' for c in expected)):
                            raise ValueError('Saved native dependency escaped or malformed: '+name)
                        if name in result and result[name] != expected:
                            raise ValueError('Saved native input dependency changed: Conflicting '+name)
                        result[name] = expected
                else:
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    for record in records:
        visit(record)
    return result


def prepare_saved(snapshot, output, *, expected_manifest_sha256, setup,
                  task_filename, adapter_file, dependency_records=()):
    """Rebind current reviewed code while preserving native data and every site.

    The adapter validates the native task/reference first. Setup is a separate
    public-prose/start record; the original native episode is copied unchanged.
    """
    saved, original, buffers = snapshot
    output = Path(output).resolve()
    if output == saved or output.is_relative_to(saved) or saved.is_relative_to(output):
        raise ValueError('Use a fresh output separate from the saved recipe')
    task = json.loads(buffers[task_filename])
    if (setup.get('schema') != VERSION or setup.get('task_id') != task['task_id']
            or setup.get('memories') != task['memories']
            or type(setup.get('user_message')) is not str
            or not setup['user_message'].strip()):
        raise ValueError('Saved public setup identity/memories/request changed')
    sources = _bind(shared.source_files, __file__=str(adapter_file))()
    sources['scripts/trace_grades.py'] = file_hash(ROOT/'scripts/trace_grades.py')
    if (ROOT/'scripts/__init__.py').is_file():
        sources['scripts/__init__.py'] = file_hash(ROOT/'scripts/__init__.py')
    # Native semantics often embed feature declarations in task/reference rows.
    # Replay alone is insufficient: retain their data bytes in the source union.
    for name, expected in declared_sources(task, *dependency_records).items():
        if file_hash(ROOT/name) != expected or (name in sources and sources[name] != expected):
            raise ValueError('Saved native input dependency changed: '+name)
        sources[name] = expected
    world_bytes = buffers['pin/world.private.json']
    world = json.loads(world_bytes)
    execution = Execution(validation='off')
    output.mkdir(parents=True, exist_ok=False)
    producer = execution.freeze(world, output/'pin')
    (output/'pin/world.private.json').write_bytes(world_bytes)
    producer['files']['world.private.json'] = sha256(world_bytes).hexdigest()
    (output/'pin/manifest.json').write_text(json.dumps(producer, indent=2, ensure_ascii=False)+'\n')
    for name, expected in producer['source_sha256'].items():
        if name in sources and sources[name] != expected:
            raise ValueError('Producer/saved-answer source conflict: '+name)
        sources[name] = expected
    for name, expected in sources.items():
        source = (ROOT/name).resolve()
        if not source.is_relative_to(ROOT):
            raise ValueError('Saved-answer source escaped: '+name)
        payload = source.read_bytes()
        if sha256(payload).hexdigest() != expected:
            raise ValueError('Saved-answer source changed: '+name)
        archive = output/'pin/source-snapshot'/name
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_bytes(payload)
    for name in original['files']:
        # Saved records retain their exact bytes. Producer/source archives are
        # regenerated once, and the one execution overlay is created separately.
        if not name.startswith('pin/') and name != 'execution.private.json':
            target = output/name
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(buffers[name])
    shared.save(output/'saved-answer-setup.private.json', setup)
    previous = json.loads(buffers['execution.private.json'])
    shared.save(output/'execution.private.json', {**previous, 'source_sha256': sources,
        'answer_grading': {'mode': 'external_required', 'native_kind': task['kind']},
        'runtime_options': {**previous.get('runtime_options', {}), 'lazy_publication': True}})
    read_recipe(saved, expected_manifest_sha256=expected_manifest_sha256)
    for name, expected in sources.items():
        if file_hash(ROOT/name) != expected or file_hash(output/'pin/source-snapshot'/name) != expected:
            raise ValueError('Source changed before saved-answer publication: '+name)
    manifest = {**deepcopy(original), 'saved_answer_recipe': VERSION,
        'source_sha256': sources,
        'files': {str(p.relative_to(output)): file_hash(p) for p in output.rglob('*')
                  if p.is_file() and 'source-snapshot' not in p.relative_to(output).parts},
        'original_recipe': {'path': str(saved), 'manifest_sha256': expected_manifest_sha256},
        'automatic_grader_supported': True, 'automatic_grading_attached': False,
        'world_draws': 0, 'model_runs': 0, 'effects': 'unknown'}
    shared.save(output/'manifest.json', manifest)
    return manifest
