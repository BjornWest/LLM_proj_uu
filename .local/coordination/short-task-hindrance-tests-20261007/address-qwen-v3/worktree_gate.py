"""No project imports or provider calls until the exact Git build is accepted."""
from hashlib import sha256
import importlib.util
import importlib.metadata
import json
from pathlib import Path
import subprocess


def require_pin(record):
    path = Path(record['path'])
    if sha256(path.read_bytes()).hexdigest() != record['sha256']:
        raise ValueError('Changed build evidence: ' + str(path))
    return path


def require_promoted_worktree(plan):
    release = plan['release']
    if not release.get('certificate') or not release.get('promotion'):
        raise ValueError('Evaluation build is not promoted; actual worktree smoke is pending')
    tooling = require_pin(release['tooling'])
    certificate = require_pin(release['certificate'])
    promotion = require_pin(release['promotion'])
    module_spec = importlib.util.spec_from_file_location('pinned_evaluation_release', tooling)
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    ready = module.require_ready(release['worktree'], certificate)
    approved = json.loads(promotion.read_bytes())
    if (approved.get('owner') != 'Evaluation' or approved.get('status') != 'accepted'
            or approved.get('certificate') != release['certificate']
            or approved.get('commit') != release['commit']
            or ready['commit'] != release['commit']
            or Path(plan['source_archive']).resolve() != Path(release['worktree']).resolve()):
        raise ValueError('Candidate/promotion/certificate source bindings differ')
    environment = json.loads(Path(ready['environment']['path']).read_bytes())
    # Same external interpreter/dependency versions; editable project imports are
    # separately rejected by the dispatcher before each provider request.
    import sys
    actual = sorted([{'name': d.metadata['Name'], 'version': d.version}
                     for d in importlib.metadata.distributions()],
                    key=lambda d: (d['name'].lower(), d['version']))
    if (environment.get('installed_distributions') != actual
            or environment.get('python') != sys.version
            or environment.get('prefix') != sys.prefix):
        raise ValueError('External Python environment differs from smoke inventory')
    return ready
