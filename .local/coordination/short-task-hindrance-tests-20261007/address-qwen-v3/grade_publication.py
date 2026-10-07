"""Publish bound native grades and require a verified live viewer projection."""
import fcntl
from hashlib import sha256
import json
from pathlib import Path
from urllib.request import urlopen
import uuid

ROOT = Path('/home/bjorn/code/LLM_proj_uu')
REGISTRY = ROOT/'.local/trace-viewer/sources.json'
VIEWER = 'http://localhost:8878'


def pin(path):
    path = Path(path).resolve()
    return {'path': str(path), 'sha256': sha256(path.read_bytes()).hexdigest()}


def read_view(ident):
    with urlopen(VIEWER+'/api/sessions/'+ident, timeout=30) as response:
        data = response.read()
    view = json.loads(data)
    grade = view.get('derived_evaluation') or {}
    if grade.get('binding_status') != 'verified' or grade.get('grading_scope') != 'captured_address_state':
        raise ValueError('System failure: bound automatic address grade absent from trace viewer')
    return view, sha256(data).hexdigest()


def viewer_health():
    view, _ = read_view('afb24e7ae1ea2fe1470a')
    if view['derived_evaluation']['structured_claims_correct'] is not True:
        raise ValueError('Existing accepted native grade projection changed')


def publish_grade(result, selected, output):
    trace = Path(result['trace']).resolve()
    if not trace.is_relative_to(Path(output).resolve()/selected['case_id']/'live/runs'):
        raise ValueError('Returned trace escaped its case')
    authority = json.loads((trace/'cart-authority.private.json').read_text())
    provenance = json.loads((trace/'cart-capture-provenance.private.json').read_text())
    files = {name: pin(trace/file) for name, file in {
        'grade':'atomic-address-grade.private.json', 'capsule':'cart-capsule.private.json',
        'provenance':'cart-capture-provenance.private.json', 'authority':'cart-authority.private.json',
        'steps':'steps.jsonl', 'policy_task':'policy-task.json'}.items()}
    files['task'] = pin(Path(selected['recipe'])/'atomic-address-task.private.json')
    files['approval'] = authority['independent_acceptance']
    files['before'], files['after'] = provenance['captures']['before'], provenance['captures']['after']
    for entry in files.values():
        if pin(entry['path']) != entry:
            raise ValueError('Changed native grade evidence')
    with REGISTRY.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        registry = json.loads(REGISTRY.read_text())
        key = str(trace)
        entries = registry.setdefault('address_grades', {})
        if key in entries and entries[key] != {'files':files}:
            raise ValueError('Conflicting existing grade binding')
        entries[key] = {'files':files}
        root = str(trace.parent)
        if root not in registry['roots']:
            registry['roots'].append(root)
        temporary = REGISTRY.with_suffix('.'+uuid.uuid4().hex+'.tmp')
        temporary.write_text(json.dumps(registry, indent=2)+'\n')
        temporary.replace(REGISTRY)
    ident = sha256(('browsergym:'+trace.name).encode()).hexdigest()[:20]
    view, response_hash = read_view(ident)
    expected = result['state_grading']['verdict']
    verdict = {'pass':True, 'fail':False, 'inconclusive':None}[expected]
    if view['derived_evaluation'].get('structured_claims_correct') is not verdict:
        raise ValueError('System failure: viewer/native verdict mismatch')
    return {'status':'verified_automatic_native_grade_visible', 'viewer_url':VIEWER+'/#'+ident,
            'api_url':VIEWER+'/api/sessions/'+ident, 'response_sha256':response_hash,
            'native_verdict':expected, 'evaluation_label':view['evaluation_label'], 'files':files}
