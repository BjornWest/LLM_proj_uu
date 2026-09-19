"""Build a private, hash-inventoried runtime directory without historical runs.

Copies an explicit runtime/import/contract closure. It is never a Vercel asset
bundle. Site assets remain in the existing separately verified fixture mount.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from data.curation.worker_integration.bindings import checked_path, load_registry


def dependencies(seeds):
    paths = set(); pending = list(seeds)
    while pending:
        path = pending.pop().resolve()
        if path in paths: continue
        if not path.is_relative_to(ROOT) or not path.is_file() or path.is_symlink():
            raise ValueError('Invalid package source')
        paths.add(path)
        if path.suffix != '.py': continue
        parent = path.relative_to(ROOT).parent.parts
        for node in ast.walk(ast.parse(path.read_text())):
            names = []
            if isinstance(node, ast.Import): names = [n.name for n in node.names]
            elif isinstance(node, ast.ImportFrom):
                prefix = list(parent[:len(parent) - node.level + 1]) if node.level else []
                base = '.'.join(prefix + ([node.module] if node.module else []))
                names = [base] + [base + '.' + n.name for n in node.names]
            for name in names:
                for candidate in [ROOT.joinpath(*name.split('.')).with_suffix('.py'), ROOT.joinpath(*name.split('.')) / '__init__.py']:
                    if candidate.is_file(): pending.append(candidate)
    return paths


def package(registry_path, output):
    output.mkdir(parents=True, exist_ok=False)
    registry = load_registry(registry_path)
    seeds = list((ROOT / 'intent_browser').glob('*.py'))
    bridge = ROOT / 'data/curation/worker_integration'
    seeds += [bridge / name for name in ['__init__.py', 'bindings.py', 'context.py', 'tasks.py', 'tricky.py',
                                        'webarena.py', 'private_http.py', 'provenance.py', 'native_grader.py']]
    # Runtime dynamic factory choices; AST adds their ordinary imports/checkers.
    seeds += [ROOT / 'data/curation/expansion' / path for path in [
        'tricky/lookup_tasks.py', 'tricky/batch02/tasks.py', 'tricky_original_remaining/tasks.py',
        'tricky/authored/native.py', 'tricky/authored02/native_v2.py', 'tricky/authored03/native.py',
        'tricky/authored03/native_v2.py', 'tricky/authored04/native.py']]
    sources = dependencies(seeds)
    for row in registry['tasks']: sources.add(checked_path(ROOT, row['contract']))
    sources |= set((ROOT / 'environments/demo').glob('*.html')) | set((ROOT / 'environments/demo').glob('*.js')) | set((ROOT / 'environments/demo').glob('*.css'))
    sources |= {ROOT / 'config' / name for name in ['team_tasks.json', 'team_sites.json', 'expanded_team_tasks.json', 'chaos_verifier.json']}
    for path in sorted(sources):
        if path.suffix not in ('.py', '.json', '.html', '.css', '.js') or path.is_symlink():
            raise ValueError('Unexpected runtime source type')
        destination = output / 'runtime' / path.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, destination)
    # Overlay only dispatcher/helpers in the legacy image. Its certified runner,
    # adapters, fixtures and graders are retained; expanded jobs run separately.
    for name in ['team_worker.py', 'expanded_tasks.py', 'worker_sites.py']:
        destination = output / 'overlay/intent_browser' / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / 'intent_browser' / name, destination)
    shutil.copyfile(registry_path, output / 'registry.json')
    files = {str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest() for p in output.rglob('*') if p.is_file()}
    manifest = {'schema': 'expanded-worker-package-v1', 'registry_sha256': hashlib.sha256(registry_path.read_bytes()).hexdigest(),
                'tasks': len(registry['tasks']), 'files': files, 'bytes': sum(p.stat().st_size for p in output.rglob('*') if p.is_file()),
                'scope': 'Private source and contract closure; not certification or policy input', 'model_calls': 0}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--registry', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args(); value = package(args.registry, args.output)
    print(json.dumps({'tasks': value['tasks'], 'files': len(value['files']), 'bytes': value['bytes']}))


if __name__ == '__main__': main()
