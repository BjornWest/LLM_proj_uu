"""Portable immutable environment snapshots. No installers, downloads or secrets.

An environment package is private harness input, never a static web root.
Run its copied runtime in a separate process; do not mix adapter revisions.
"""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
FORMAT = 'intent-browser-environments-v1'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def safe_name(name):
    p = PurePosixPath(name)
    if (not isinstance(name, str) or not name or '\\' in name or p.is_absolute()
            or '..' in p.parts or str(p) != name):
        raise ValueError('Invalid package member path')
    return name


def inventory(directory):
    directory = Path(directory)
    result = {}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink():
            raise ValueError('Package symlinks are not permitted')
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError('Package contains a special file')
        name = path.relative_to(directory).as_posix()
        result[safe_name(name)] = {'sha256': digest(path), 'bytes': path.stat().st_size}
    return result


def verify(directory):
    directory = Path(directory).resolve(strict=True)
    manifest = json.loads((directory/'manifest.json').read_text())
    if manifest.get('format') != FORMAT or manifest.get('schema_version') != 1:
        raise ValueError('Unsupported environment package')
    actual = inventory(directory)
    actual.pop('manifest.json')
    if not manifest.get('files') or actual != manifest['files']:
        raise ValueError('Package file set, size or hash differs from manifest')
    for name in manifest['files']:
        safe_name(name)
    return manifest


def copy_file(source, target):
    source = Path(source)
    if source.is_symlink() or not source.is_file():
        raise ValueError('Expected a regular source file: '+str(source))
    data = source.read_bytes()
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('xb') as out:
        out.write(data)
    if source.read_bytes() != data:
        raise ValueError('Source changed while packaging')


def copy_tree(source, target, *, python_only=False):
    for path in sorted(Path(source).rglob('*')):
        if '__pycache__' in path.parts:
            continue
        if path.is_symlink():
            raise ValueError('Source tree contains a symlink: '+str(path))
        if path.is_file() and (not python_only or path.suffix == '.py'):
            copy_file(path, target/path.relative_to(source))


def export(output, *, fixtures, chaos, miniwob, resources=None, source=ROOT):
    output = Path(os.path.abspath(output))
    if os.path.lexists(output):
        raise FileExistsError('Choose a new output directory; packages are immutable')
    source = Path(source).resolve(strict=True)
    resources = Path(resources or source/'.research/environment-fonts-v1').resolve(strict=True)
    resource_record = source/'environments/portable-resources/inter.json'
    pinned_resources = json.loads(resource_record.read_text())['resources']
    for row in pinned_resources.values():
        if digest(resources/safe_name(row['file'])) != row['sha256']:
            raise ValueError('Cached external resource hash changed')
    # Reuse existing reviewed fixture validation and materialized Chaos export.
    from .hosted_tasks import check_package, registry, check_sources
    fixtures = check_package(fixtures)
    fixture_manifest = json.loads((fixtures/'package.json').read_text())
    if set(inventory(fixtures)) != {'package.json', *fixture_manifest['files_sha256']}:
        raise ValueError('Fixture directory contains unreviewed files; refusing to copy them')
    tasks = registry()['tasks']
    for task in tasks:
        check_sources(task)
    for root in (source/'intent_browser', fixtures, Path(chaos).resolve(), Path(miniwob).resolve()):
        if output.resolve().is_relative_to(root):
            raise ValueError('Output cannot be inside a copied source tree')
    import browsergym.miniwob as mini
    mini_source = Path(mini.__file__).parent
    miniwob = Path(miniwob).resolve(strict=True)
    if not (miniwob/'miniwob/html/core/core.js').is_file():
        raise ValueError('MiniWoB checkout lacks its local web assets')
    revision = subprocess.check_output(['git', '-C', str(miniwob), 'rev-parse', 'HEAD'], text=True).strip()
    output.mkdir(parents=True, exist_ok=False)
    runtime = output/'runtime'
    copy_tree(source/'intent_browser', runtime/'intent_browser', python_only=True)
    copy_tree(source/'intent_browser/assets/chat', runtime/'intent_browser/assets/chat')
    copy_tree(source/'environments/demo', runtime/'environments/demo')
    copy_tree(source/'environments/susbench_ikea', runtime/'environments/susbench_ikea')
    # Include the fixture/verifier runtime's exact private inputs, not .env/runs.
    for name in ('config/team_tasks.json', 'config/chaos_verifier.json',
                 'scripts/inspect_chaos.mjs', 'pyproject.toml'):
        copy_file(source/name, runtime/name)
    for name in ('verify_chaos.py', 'verify_tricky.py', 'verify_tricky_privacy.py',
                 'verify_tricky_membership.py', 'verify_authorized_warranty.py',
                 'verify_hosted_worker.py', 'verify_environment_package.py'):
        copy_file(source/'scripts'/name, runtime/'scripts'/name)
    copy_tree(fixtures, output/'fixtures')
    copy_file(resource_record, output/'resources/inter.json')
    for row in pinned_resources.values():
        copy_file(resources/row['file'], output/'resources'/row['file'])
    copy_tree(miniwob/'miniwob/html', output/'miniwob/html')
    copy_file(miniwob/'LICENSE', output/'licenses/miniwob.txt')
    copy_tree(mini_source, output/'vendor/browsergym/miniwob', python_only=True)
    from deploy.worker.export_chaos import export as export_chaos
    export_chaos(chaos, output/'chaos')
    # Export metadata identifies original paths but contains no server state.
    mini_tasks = sorted(t.get_task_id() for t in mini.ALL_MINIWOB_TASKS)
    datasets = [
        {'id': 'campus', 'status': 'runnable', 'tasks': ['campus.booking', 'campus.shop', 'campus.preferences'],
         'scope': 'Synthetic local server state and existing demo verifier.'},
        {'id': 'browser-agent-chaos', 'status': 'runnable', 'tasks': [t['id'] for t in tasks if t['kind']=='chaos'],
         'scope': 'Seven reviewed contracts; copied FIFO/xorshift build. Certification checked again on prepared session.'},
        {'id': 'trickyarena', 'status': 'runnable', 'tasks': [t['id'] for t in tasks if t['kind'] in ('tricky','privacy','membership')],
         'scope': 'Derived P07/P10/P11 clean and injected fixtures; not complete upstream websites.'},
        {'id': 'synthetic-development', 'status': 'runnable', 'tasks': ['synthetic-dev-w01'],
         'scope': 'Separate authorized warranty contract; not the original P07 goal.'},
        {'id': 'miniwob', 'status': 'runnable', 'tasks': mini_tasks, 'source_revision': revision,
         'scope': 'Bundled HTML and BrowserGym adapter; native rewards only. Individual tasks need offline validation.'},
        {'id': 'susbench', 'status': 'diagnostic_only', 'tasks': ['susbench.ikea-preselect'],
         'scope': 'Pinned radio/callback diagnostic only; no purchase/auth/avoidance verifier. Full benchmark not integrated; reuse license unresolved.'},
        {'id': 'doomarena', 'status': 'not_integrated', 'tasks': [],
         'scope': 'Attack framework, not a standalone website. No configured attack/task adapter or certificate in this repository.'},
    ]
    manifest = {'format': FORMAT, 'schema_version': 1, 'datasets': datasets,
                'files': inventory(output), 'requires': {'python': '3.12', 'node': '22',
                    'browsergym-core': importlib.metadata.version('browsergym-core'),
                    'browsergym-miniwob': importlib.metadata.version('browsergym-miniwob'),
                    'chromium': 'Install with the pinned BrowserGym/Playwright runtime during image preparation.'},
                'network': 'Loopback only during offline execution. Package creation uses existing local caches.',
                'access': 'Private control-plane input, includes privileged contracts; never serve this directory as a web root.',
                'training_readiness_changed': False, 'downloads': 0}
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    verify(output)
    return manifest


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    build = sub.add_parser('export')
    build.add_argument('--output', type=Path, required=True)
    build.add_argument('--fixtures', type=Path, required=True)
    build.add_argument('--chaos', type=Path, required=True)
    build.add_argument('--miniwob', type=Path, required=True)
    build.add_argument('--resources', type=Path, help='Previously prepared pinned font cache')
    check = sub.add_parser('verify');check.add_argument('package', type=Path)
    args = p.parse_args()
    value = export(args.output, fixtures=args.fixtures, chaos=args.chaos, miniwob=args.miniwob,resources=args.resources) if args.command=='export' else verify(args.package)
    print(json.dumps({'format': value['format'], 'files': len(value['files']),
                      'bytes': sum(f['bytes'] for f in value['files'].values()), 'datasets': value['datasets']}, indent=2))


if __name__ == '__main__':
    main()
