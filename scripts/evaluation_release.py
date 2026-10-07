"""Git-backed evaluation candidates. Never modify the development index or HEAD.

Source candidates are deliberately NOT runnable releases until an actual browser
and automatic-grading smoke is certified. Credentials/results remain external.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import tempfile


MANIFEST = '.evaluation-release.json'
REQUIRED_ASSETS = ('intent_browser/assets/chat/chat.html',
                   'intent_browser/assets/chat/LICENSE.browsergym.txt')
STAGES = ('import_isolation', 'browser_reset', 'initial_observation', 'task_setup',
          'capture', 'automatic_grade', 'viewer_projection', 'positive_negative_controls')


def digest(path):
    h = sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def pin(path):
    return {'path': str(Path(path).resolve()), 'sha256': digest(path)}


def verify_pin(record):
    if pin(record['path']) != record:
        raise ValueError('Changed evidence: ' + record['path'])


def encode(value):
    return (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()


def save_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(encode(value))


def relative_name(name):
    p = PurePosixPath(name)
    if (not name or p.is_absolute() or str(p) != name or '..' in p.parts
            or any(part in ('.git', '.env', '.venv', '__pycache__') for part in p.parts)
            or any(part.startswith('.env.') for part in p.parts)
            or '\n' in name or '\t' in name or '\\' in name):
        raise ValueError('Unsafe source path: ' + name)
    return name


def git(repo, *args, data=None, env=None):
    return subprocess.run(['git', '-C', str(repo), *args], input=data,
                          capture_output=True, check=True, env=env).stdout


def commit_id(repo, revision):
    return git(repo, 'rev-parse', '--verify', revision + '^{commit}').decode().strip()


@contextmanager
def temporary_index(repo, base=None):
    # Separate file and environment, including when the caller has a staged index.
    with tempfile.TemporaryDirectory(prefix='evaluation-git-index-') as directory:
        env = dict(os.environ, GIT_INDEX_FILE=str(Path(directory) / 'index'))
        if base:
            git(repo, 'read-tree', commit_id(repo, base), env=env)
        else:
            git(repo, 'read-tree', '--empty', env=env)
        yield env


def source_blob(repo, name, record):
    relative_name(name)
    path = Path(record['source'])
    if path.is_symlink() or not path.is_file() or digest(path) != record['sha256']:
        raise ValueError('Missing/changed/nonregular source: ' + name)
    blob = git(repo, 'hash-object', '-w', '--no-filters', '--', str(path.resolve())).decode().strip()
    # Check the bytes Git stored, not a second independent file-read assumption.
    if sha256(git(repo, 'cat-file', 'blob', blob)).hexdigest() != record['sha256']:
        raise ValueError('Source changed while capturing: ' + name)
    return '100755' if path.stat().st_mode & 0o111 else '100644', blob


def write_candidate(repo, *, files, metadata, ref, worktree, receipt, base=None):
    if not ref.startswith(('refs/heads/eval-candidates/', 'refs/heads/dev/')):
        raise ValueError('Use an owned eval-candidates/ or dev/ branch')
    git(repo, 'check-ref-format', ref)
    if Path(worktree).exists() or Path(receipt).exists():
        raise ValueError('Worktree and receipt must be new paths')
    if not base:
        for name in REQUIRED_ASSETS:
            if name not in files or files[name] is None:
                raise ValueError('Required browser asset omitted: ' + name)
    with temporary_index(repo, base) as env:
        hashes = {}
        if base:
            old = json.loads(git(repo, 'show', commit_id(repo, base) + ':' + MANIFEST))
            hashes.update(old['source_sha256'])
            # Inherit exact Git blobs, never reload undeclared files from a mutable
            # or intentionally partial development root. Verify required base assets.
            for name in REQUIRED_ASSETS:
                content = git(repo, 'show', commit_id(repo, base) + ':' + name)
                if not content or sha256(content).hexdigest() != hashes.get(name):
                    raise ValueError('Invalid inherited browser asset: ' + name)
        updates = []
        for name, record in sorted(files.items()):
            relative_name(name)
            if name == MANIFEST:
                raise ValueError('Release manifest is generated, not an input source')
            if record is None:
                updates.append('0 ' + '0' * 40 + '\t' + name + '\n')
                hashes.pop(name, None)
                continue
            mode, blob = source_blob(repo, name, record)
            updates.append(f'{mode} {blob}\t{name}\n')
            hashes[name] = record['sha256']
        for name in REQUIRED_ASSETS:
            if name not in hashes:
                raise ValueError('Required browser asset absent')
        manifest = {'schema': 1, 'state': 'candidate_requires_runtime_smoke',
                    'source_sha256': hashes, 'required_assets': list(REQUIRED_ASSETS),
                    'metadata': metadata,
                    'base_commit': commit_id(repo, base) if base else None}
        blob = git(repo, 'hash-object', '-w', '--stdin', data=encode(manifest)).decode().strip()
        updates.append(f'100644 {blob}\t{MANIFEST}\n')
        git(repo, 'update-index', '--index-info', data=''.join(updates).encode(), env=env)
        tree = git(repo, 'write-tree', env=env).decode().strip()
        parents = ['-p', commit_id(repo, base)] if base else []
        commit = git(repo, 'commit-tree', tree, *parents,
                     data=b'Create isolated evaluation candidate; runtime readiness is separate\n').decode().strip()
    # Compare-and-create: no moving somebody else's existing branch.
    git(repo, 'update-ref', ref, commit, '0' * 40)
    Path(worktree).parent.mkdir(parents=True, exist_ok=True)
    git(repo, 'worktree', 'add', '--detach', str(Path(worktree).resolve()), commit)
    result = {'schema': 1, 'state': 'candidate_requires_runtime_smoke', 'commit': commit,
              'ref': ref, 'worktree': str(Path(worktree).resolve()),
              'manifest': pin(Path(worktree) / MANIFEST), 'source_count': len(hashes),
              'metadata': metadata, 'model_dispatch_released': False}
    verify_worktree(worktree, commit)
    save_new(receipt, result)
    return result


def verify_worktree(worktree, expected_commit=None):
    root = Path(worktree).resolve()
    actual = commit_id(root, 'HEAD')
    if expected_commit is not None and actual != expected_commit:
        raise ValueError('Unexpected evaluation commit')
    if git(root, 'status', '--porcelain', '--untracked-files=all').strip():
        raise ValueError('Evaluation worktree has modified/untracked files')
    manifest = json.loads((root / MANIFEST).read_bytes())
    tracked = set(git(root, 'ls-files', '-z').decode().rstrip('\0').split('\0'))
    if tracked != set(manifest['source_sha256']) | {MANIFEST}:
        raise ValueError('Tracked source inventory differs from release manifest')
    for name, expected in manifest['source_sha256'].items():
        path = root / relative_name(name)
        if path.is_symlink() or not path.resolve().is_relative_to(root) or digest(path) != expected:
            raise ValueError('Changed release source: ' + name)
    for name in REQUIRED_ASSETS:
        if name not in manifest['source_sha256'] or not (root / name).stat().st_size:
            raise ValueError('Required browser asset absent/empty: ' + name)
    return actual, manifest


def certify(worktree, evidence, certificate):
    commit, manifest = verify_worktree(worktree)
    proof = json.loads(Path(evidence).read_bytes())
    if (proof.get('schema') != 1 or proof.get('commit') != commit
            or proof.get('worktree') != str(Path(worktree).resolve())
            or type(proof.get('model_requests')) is not int or proof['model_requests'] != 0):
        raise ValueError('Smoke must bind this exact worktree/commit and use zero model requests')
    if not proof.get('cases') or not proof.get('environment'):
        raise ValueError('Smoke needs task cases and external environment inventory')
    verify_pin(proof['environment'])
    names = set()
    artifacts = []
    for case in proof['cases']:
        if not isinstance(case.get('task_id'), str) or not case['task_id'] or case['task_id'] in names:
            raise ValueError('Missing/duplicate smoke task')
        names.add(case['task_id'])
        verify_pin(case['recipe'])
        verify_pin(case['authority'])
        artifacts.extend([case['recipe'], case['authority']])
        for stage in STAGES:
            item = case.get('checks', {}).get(stage, {})
            if item.get('status') != 'pass' or not item.get('artifact'):
                raise ValueError('Missing actual smoke stage: ' + stage)
            verify_pin(item['artifact'])
            artifacts.append(item['artifact'])
    result = {'schema': 1, 'state': 'runtime_smoke_passed_pending_promotion',
              'commit': commit, 'worktree': str(Path(worktree).resolve()),
              'manifest': pin(Path(worktree) / MANIFEST), 'evidence': pin(evidence),
              'environment': proof['environment'], 'artifacts': artifacts,
              'tasks': sorted(names), 'model_dispatch_released': False}
    save_new(certificate, result)
    return result


def require_ready(worktree, certificate):
    """Call before suite preparation/dispatch; suite spending authorization is separate."""
    result = json.loads(Path(certificate).read_bytes())
    if result.get('state') != 'runtime_smoke_passed_pending_promotion':
        raise ValueError('Missing runtime readiness certificate')
    if str(Path(worktree).resolve()) != result['worktree']:
        raise ValueError('Readiness belongs to another worktree')
    verify_worktree(worktree, result['commit'])
    for record in [result['manifest'], result['evidence'], result['environment'], *result['artifacts']]:
        verify_pin(record)
    return result


def promote(worktree, certificate, approval, registry, label):
    result = require_ready(worktree, certificate)
    decision = json.loads(Path(approval).read_bytes())
    if (decision.get('status') != 'accepted'
            or decision.get('certificate') != pin(certificate)
            or decision.get('commit') != result['commit']
            or decision.get('owner') != 'Evaluation'):
        raise ValueError('Missing exact Evaluation promotion acceptance')
    ref = 'refs/tags/eval/' + label
    git(worktree, 'check-ref-format', ref)
    registry = Path(registry).resolve()
    registry.parent.mkdir(parents=True, exist_ok=True)
    # One publisher; retain immutable approval/evidence, atomically replace discovery only.
    with (registry.parent / (registry.name + '.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        git(worktree, 'update-ref', ref, result['commit'], '0' * 40)
        current = {'schema': 1, 'state': 'accepted', 'commit': result['commit'],
                   'worktree': result['worktree'], 'tag': ref, 'certificate': pin(certificate),
                   'approval': pin(approval), 'tasks': result['tasks'],
                   'model_dispatch_released': False}
        with tempfile.NamedTemporaryFile(dir=registry.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(encode(current))
        os.replace(temporary, registry)
    return current


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    snap = sub.add_parser('snapshot')
    for flag in ('repo', 'spec', 'ref', 'worktree', 'receipt'):
        snap.add_argument('--' + flag, required=True)
    candidate = sub.add_parser('candidate')
    for flag in ('repo', 'base', 'source-root', 'paths', 'ref', 'worktree', 'receipt'):
        candidate.add_argument('--' + flag, required=True)
    check = sub.add_parser('check')
    check.add_argument('--worktree', required=True)
    check.add_argument('--certificate')
    cert = sub.add_parser('certify')
    for flag in ('worktree', 'evidence', 'certificate'):
        cert.add_argument('--' + flag, required=True)
    promotion = sub.add_parser('promote')
    for flag in ('worktree', 'certificate', 'approval', 'registry', 'label'):
        promotion.add_argument('--' + flag, required=True)
    args = parser.parse_args()
    if args.command == 'snapshot':
        spec = json.loads(Path(args.spec).read_bytes())
        result = write_candidate(args.repo, files=spec['files'], metadata=spec['metadata'],
                                 ref=args.ref, worktree=args.worktree, receipt=args.receipt)
    elif args.command == 'candidate':
        base = commit_id(args.repo, args.base)
        old = json.loads(git(args.repo, 'show', base + ':' + MANIFEST))
        # JSON paths list avoids shell globs and accidental inclusion of others' edits.
        paths = json.loads(Path(args.paths).read_bytes())
        if not isinstance(paths, list) or not paths or len(set(paths)) != len(paths):
            raise ValueError('Paths must be a nonempty unique JSON list')
        files = {}
        for name in paths:
            source = Path(args.source_root).resolve() / relative_name(name)
            if not source.resolve().is_relative_to(Path(args.source_root).resolve()):
                raise ValueError('Source escaped the declared development root')
            if source.exists():
                if source.is_symlink():
                    raise ValueError('Source symlink not allowed')
                files[name] = {'source': str(source), 'sha256': digest(source)}
            elif name in old['source_sha256']:
                files[name] = None
            else:
                raise ValueError('Missing declared source path: ' + name)
        result = write_candidate(args.repo, files=files,
                                 metadata={'parent': old['metadata'], 'changed_paths': paths},
                                 ref=args.ref, worktree=args.worktree, receipt=args.receipt, base=base)
    elif args.command == 'certify':
        result = certify(args.worktree, args.evidence, args.certificate)
    elif args.command == 'promote':
        result = promote(args.worktree, args.certificate, args.approval, args.registry, args.label)
    elif args.certificate:
        result = require_ready(args.worktree, args.certificate)
    else:
        commit, manifest = verify_worktree(args.worktree)
        result = {'commit': commit, 'source_count': len(manifest['source_sha256']),
                  'state': 'source_only_not_runtime_ready', 'model_dispatch_released': False}
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
