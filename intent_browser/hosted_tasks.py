"""Private, fixed task dispatch for the team worker. Never a policy observation."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT/'config/team_tasks.json'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def registry():
    value = json.loads(REGISTRY.read_text())
    if value.get('schema_version') != 1 or len(value['tasks']) != 14:
        raise ValueError('Unsupported team task registry')
    for task in value['tasks']:
        content = {k: v for k, v in task.items() if k != 'revision'}
        if hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest() != task['revision']:
            raise ValueError('Task registry row differs from its revision')
    return value


def entry(task_id):
    matches = [task for task in registry()['tasks'] if task['id'] == task_id]
    if len(matches) != 1:
        raise ValueError('Unsupported team task selector')
    return matches[0]


def check_sources(task):
    if any(digest(ROOT/name) != expected for name, expected in task['source_sha256'].items()):
        raise ValueError('Task verifier source changed since registry review')


def check_package(directory):
    directory = Path(directory).resolve(strict=True)
    package = json.loads((directory/'package.json').read_text())
    if package['registry_sha256'] != digest(REGISTRY):
        raise ValueError('Fixture package belongs to a different task registry')
    for name, expected in package['files_sha256'].items():
        path = directory/name
        if path.is_symlink() or not path.resolve().is_relative_to(directory) or digest(path) != expected:
            raise ValueError('Fixture package path/hash changed')
    config = registry()
    for file, expected in [('pilot_manifest.json', config['pilot_manifest_sha256']),
                           ('authorized_warranty_contract.json', config['authorized_contract_sha256'])]:
        if digest(directory/file) != expected:
            raise ValueError('Private task input changed')
    for task in config['tasks']:
        if task['build'] and digest(directory/task['build']/'build.json') != task['build_sha256']:
            raise ValueError('Task build manifest changed')
    return directory


def capabilities(mode, fixture_dir=None, chaos_url=None):
    # New fixtures require live mode; scripted acceptance uses an explicit local
    # test backend and is never advertised as general autonomous inference.
    ready = []
    fixtures = None
    if fixture_dir:
        fixtures = check_package(fixture_dir)
    if chaos_url:
        from .chaos_verifier import fingerprint_server, certification
        provenance = fingerprint_server(chaos_url)
    for task in registry()['tasks']:
        if mode != 'live' and task['id'] != 'chaos-confirmshaming':
            continue
        check_sources(task)
        if task['kind'] == 'chaos':
            if chaos_url and certification(provenance, task['selector']):
                ready.append(task['id'])
        elif fixtures:
            ready.append(task['id'])
    return ready


def make_task(task_id, *, fixture_dir=None, chaos_url=None, revision=None):
    task = entry(task_id)
    if revision is not None and revision != task['revision']:
        raise ValueError('Queued task revision differs from worker registry')
    check_sources(task)
    if task['kind'] == 'chaos':
        if not chaos_url:
            raise ValueError('Reviewed Chaos server is unavailable')
        from .chaos import ChaosClient, ChaosTask
        return ChaosTask(ChaosClient(chaos_url), task['selector'])
    if not fixture_dir:
        raise ValueError('Reviewed task fixtures are unavailable')
    directory = check_package(fixture_dir)
    kwargs = {'build_dir': directory/task['build']}
    if task['kind'] == 'authorized':
        from .tricky_authorized import AuthorizedWarrantyTask
        result = AuthorizedWarrantyTask(contract=directory/'authorized_warranty_contract.json', **kwargs)
    else:
        from .tricky import TrickyTask
        from .tricky_privacy import PrivacyTask
        from .tricky_membership import MembershipTask
        cls = {'tricky': TrickyTask, 'privacy': PrivacyTask, 'membership': MembershipTask}[task['kind']]
        result = cls(condition=task['selector'], manifest=directory/'pilot_manifest.json', **kwargs)
    if result.policy_goal != task['goal']:
        raise ValueError('Adapter goal differs from reviewed task registry')
    return result
