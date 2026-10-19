"""Attach the existing harness grader to a frozen native commercial instance.

Website supplies a privileged capture callback; policy text is never evidence.
This adapter neither launches a runner nor certifies effects outside the scope.
"""
from copy import deepcopy
from hashlib import sha256
import inspect
import functools
import json
from pathlib import Path

from intent_browser.automatic_grading import AutomaticGrading, file_hash
from intent_browser.connected_world_task import policy_goal, checked_files
from . import registry
from .journal import adapt, JournalError

VERSION = 'commerce-dark-pattern-automatic-v1'
CAPTURE = 'commerce-capture.private.json'


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def task_id(instance):
    registry._prepared(instance)
    return 'commerce-dark-' + _digest(instance)[:24]


def public_request(instance):
    _, native = registry._prepared(instance)
    value = native.get('user_message', native.get('task', {}).get('user_message'))
    if type(value) is not str or not value.strip():
        raise ValueError('Native instance has no public request')
    return value


def public_memories(instance):
    _, native = registry._prepared(instance)
    task = native.get('task', {})
    return deepcopy(task.get('memories', task.get('public_memory', [])))


def _delivered_answer(directory):
    """Use only actual BrowserGym delivered text, never policy draft completions."""
    path = Path(directory)/'natural-answer.json'
    if not path.is_file():
        return None, None
    value = json.loads(path.read_bytes())
    if (type(value) is not dict or value.get('schema_version') != 'connected-world-manual-v1'
            or value.get('source') != 'BrowserGym chat from executed send_msg_to_user; no extraction or repair'
            or type(value.get('assistant_messages')) is not list
            or any(type(m) is not str for m in value['assistant_messages'])
            or value.get('text') != (value['assistant_messages'][-1] if value['assistant_messages'] else None)):
        raise ValueError('Missing actual delivered-answer provenance')
    answer = value['text'] if value.get('stop_reason') == 'agent_finished' and value.get('technical_error') is None else None
    return answer, file_hash(path)


def _save_new(path, value):
    payload = json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2)
    with Path(path).open('x', encoding='utf-8') as stream:
        stream.write(payload)


class CommerceGrading:
    """Reusable callbacks, with exact inputs bound before policy dispatch.

    capture(env, trace, outcome) must return the Website host's sealed evidence.
    Its actual callback source must be in source_files, together with the complete
    released host/native dependency closure. Source pinning alone is not approval
    of a callback: actual Website capture requires independent acceptance.
    """
    def __init__(self, instance_path, *, source_files, capture):
        self.path = Path(instance_path).resolve(strict=True)
        self.instance_pin = file_hash(self.path)
        self.instance = json.loads(self.path.read_bytes())
        self.id = task_id(self.instance)
        self.request = public_request(self.instance)
        if not callable(capture) or type(source_files) is not dict or not source_files:
            raise ValueError('Require an actual capture callback and frozen source closure')
        if isinstance(capture, functools.partial):
            raise ValueError('Capture partials require an explicit source-owned wrapper')
        registry.validate_ready(self.instance)
        self.capture = capture
        self.sources = {str(Path(p).resolve(strict=True)): h for p, h in source_files.items()}
        try:
            callback_source = inspect.getsourcefile(capture)
        except TypeError:
            callback_source = inspect.getsourcefile(type(capture))
        if callback_source is None:
            callback_source = inspect.getsourcefile(type(capture))
        native_module, _ = registry._prepared(self.instance)
        from . import journal
        required = {Path(__file__).resolve(), Path(registry.__file__).resolve(), Path(journal.__file__).resolve(),
                    Path(native_module.__file__).resolve()}
        if callback_source is None:
            raise ValueError('Capture callback has no pinned source')
        required.add(Path(callback_source).resolve())
        if not required <= {Path(p) for p in self.sources}:
            raise ValueError('Native/router/capture callbacks missing from frozen sources')
        checked_files(self.sources)
        self.bound = None
        self.bound_instance = None

    def contract(self):
        # The Runtime lives outside run_episode's browser lifetime. Reuse the
        # existing external phase so its store can seal after Runtime cleanup.
        return AutomaticGrading(VERSION, self.bind, self.grade, self.project, phase='external')

    def _check(self):
        if file_hash(self.path) != self.instance_pin:
            raise ValueError('Frozen commercial instance changed')
        checked_files(self.sources)

    def bind(self, env, trace, observation):
        self._check()
        if self.bound is not None:
            raise ValueError('Commercial grader is already bound to an episode')
        public = json.loads((trace.directory/'policy-task.json').read_bytes())
        if (public['task_id'] != self.id or public['user_message'] != self.request
                or policy_goal(public) != observation['goal']):
            raise ValueError('Actual policy request differs from frozen commercial task')
        if public['memories'] != public_memories(self.instance):
            raise ValueError('Actual public preferences differ from native task memories')
        native = self.instance['prepared']
        expected_episode = native.get('binding', {}).get('episode_id')
        if expected_episode is not None and expected_episode != trace.episode_id:
            raise ValueError('Native commercial instance belongs to another episode')
        bound = {'episode_id': trace.episode_id, 'directory': str(trace.directory.resolve())}
        bound_instance = registry.bind_episode(self.instance, trace.episode_id)
        bound_path = trace.directory/'commerce-instance.private.json'
        sources = dict(self.sources)
        # The gate checks the actual shared canonical viewer source as well.
        for p in self.contract().callable_sources():
            if p in sources and sources[p] != file_hash(p):
                raise ValueError('Callback source changed')
            sources[p] = file_hash(p)
        checked_files(sources)
        _save_new(bound_path, bound_instance)
        self.bound, self.bound_instance = bound, bound_instance
        return {'task_id': self.id, 'goal_sha256': sha256(observation['goal'].encode()).hexdigest(),
                'reference_files': {str(self.path): self.instance_pin,
                    str(bound_path.resolve()): file_hash(bound_path),
                    str((trace.directory/'policy-task.json').resolve()):
                        file_hash(trace.directory/'policy-task.json')},
                'source_files': sources}

    def grade(self, env, trace, outcome):
        self._check()
        if self.bound != {'episode_id': trace.episode_id,
                          'directory': str(trace.directory.resolve())}:
            raise ValueError('Commercial capture requested for an unbound episode')
        evidence = self.capture(env, trace, outcome)
        try:
            _save_new(trace.directory/CAPTURE, {'schema_version': VERSION,
                'task_id': self.id, 'episode_id': trace.episode_id,
                'instance_sha256': self.instance_pin, 'evidence': evidence})
        except (TypeError, ValueError) as error:
            diagnostic = trace.directory/'commerce-capture-unserializable.txt'
            with diagnostic.open('x', encoding='utf-8') as stream:
                stream.write(type(error).__name__+': '+str(error)+'\n'+repr(evidence))
            raise
        answer, answer_pin = _delivered_answer(trace.directory)
        # Missing capture remains a native inconclusive verdict. Foreign evidence
        # cannot be adopted just because a callback labels it complete.
        if outcome.get('error'):
            native = {'status': 'inconclusive', 'reasons': ['episode_infrastructure_failure'],
                      'broader_effects': 'unknown'}
        elif evidence is not None and (type(evidence) is not dict
                or evidence.get('episode_id') != trace.episode_id
                or evidence.get('binding') != self.bound_instance['prepared'].get('binding')):
            native = {'status': 'inconclusive', 'reasons': ['foreign_or_unbound_host_capture'],
                      'broader_effects': 'unknown'}
        else:
            try:
                mapped = adapt(self.bound_instance, evidence)
                native = registry.grade(self.bound_instance, mapped, answer=answer)
            except JournalError as error:
                native = {'status': 'inconclusive', 'reasons': [str(error)],
                          'broader_effects': 'unknown'}
        return {'task_id': self.id, 'status': native['status'], 'native_grade': native,
                'capture_sha256': file_hash(trace.directory/CAPTURE), 'answer_sha256': answer_pin}

    def project(self, raw, binding):
        if raw['task_id'] != self.id or binding['task_id'] != self.id:
            raise ValueError('Commercial projection belongs to another task')
        value = registry.project(raw['native_grade'], binding)
        value.evidence = [CAPTURE, 'automatic-grade.json', str(self.path)]
        return value

    def finalize(self, directory):
        """After policy, browser and Runtime close, use the once-only harness gate."""
        from intent_browser.automatic_grading import finalize_external, validate_binding, digest
        from scripts.trace_grades import BOUND_FILES, FILENAME
        self._check()
        directory = Path(directory).resolve(strict=True)
        if self.bound != {'episode_id': directory.name, 'directory': str(directory)}:
            raise ValueError('Finalization requires the original bound adapter')
        metadata = json.loads((directory/'metadata.json').read_bytes())
        if type(metadata) is not dict or type(metadata.get('browsergym_version')) is not str:
            raise ValueError('Missing actual BrowserGym viewer metadata')
        summary = json.loads((directory/'episode.json').read_bytes())
        if summary.get('trace_complete') is not True:
            raise ValueError('Commercial finalization requires a complete browser trace')
        for name in (*BOUND_FILES, 'task.json'):
            if not (directory/name).is_file() or (directory/name).is_symlink():
                raise ValueError('Missing finalization/viewer artifact: '+name)
        _delivered_answer(directory)
        declaration = json.loads((directory/'automatic-grading.json').read_bytes())
        binding = validate_binding(declaration['binding'], self.contract())
        if (declaration['status'] != 'pending_external' or declaration['contract_id'] != VERSION
                or declaration['binding_sha256'] != digest(binding) or binding['task_id'] != self.id):
            raise ValueError('No exact pending commercial grading binding')
        if (directory/CAPTURE).exists() or (directory/FILENAME).exists():
            raise ValueError('Commercial capture or viewer result already exists')
        summary = finalize_external(directory, self.contract())
        if summary.get('grading_error') or summary.get('grading', {}).get('status') != 'graded':
            raise ValueError('Commercial automatic grading did not finalize: '+str(
                summary.get('grading_error') or summary.get('error')))
        try:
            viewer = self.publish_view(directory)
        except Exception as error:
            # The native/canonical results remain intact; publication is a
            # distinct prospective infrastructure failure, not a task verdict.
            message = 'Commercial viewer publication failed: '+type(error).__name__+': '+str(error)
            summary.update(infrastructure_completed=False, grading_error=message, error=message, success=None)
            canonical = json.loads((directory/'evaluation.json').read_bytes())
            canonical.update(technical_error=message, safe_success=None)
            (directory/'evaluation.json').write_text(json.dumps(canonical, ensure_ascii=False, indent=2))
            summary['evaluation'] = canonical
            record = json.loads((directory/'automatic-grading.json').read_bytes())
            record.update(status='publication_failed', infrastructure_complete=False, viewer_error=message)
            summary['grading'] = record
            (directory/'automatic-grading.json').write_text(json.dumps(record, ensure_ascii=False, indent=2))
            (directory/'episode.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
            raise
        return {'summary': summary, 'viewer_grade': viewer}

    def publish_view(self, directory):
        """Publish existing viewer sidecar after the runner finalizes its artifacts.

        Call once, after runner completion, using the same bound adapter. It does
        not rerun the grader or rewrite its automatic/canonical results.
        """
        from scripts.trace_grades import BOUND_FILES, FILENAME, SCHEMA, read_grade
        self._check()
        directory = Path(directory).resolve(strict=True)
        if self.bound != {'episode_id': directory.name, 'directory': str(directory)}:
            raise ValueError('Viewer projection belongs to an unbound episode')
        declaration = json.loads((directory/'automatic-grading.json').read_bytes())
        raw = json.loads((directory/'automatic-grade.json').read_bytes())
        canonical = json.loads((directory/'evaluation.json').read_bytes())
        value = raw['raw_grade']
        expected = self.project(value, declaration['binding']).to_dict()
        summary = json.loads((directory/'episode.json').read_bytes())
        # Match GradingGate.publish: a policy/cleanup error does not erase a
        # completed native grade, and must still prevent a safe-success claim.
        if summary.get('error'):
            expected.update(technical_error=summary['error'], safe_success=None)
        if (declaration['status'] != 'graded' or declaration['contract_id'] != VERSION
                or raw['contract_id'] != VERSION or raw['episode_id'] != directory.name
                or raw['binding_sha256'] != declaration['binding_sha256']
                or declaration['grade_sha256'] != file_hash(directory/'automatic-grade.json')
                or value['capture_sha256'] != file_hash(directory/CAPTURE)
                or value['answer_sha256'] != _delivered_answer(directory)[1]
                or canonical != expected):
            raise ValueError('No exact completed automatic commercial grade to publish')
        completed = {'pass': True, 'fail': False, 'inconclusive': None}[value['status']]
        sidecar = {'schema': SCHEMA, 'episode_id': directory.name,
            'episode_artifact_sha256': {n: file_hash(directory/n) for n in BOUND_FILES},
            'grading_version': VERSION, 'structured_claims_correct': completed if value['native_grade'].get('task_completion_assessed', True) else None,
            'requirements': {'scoped_commercial_outcome': completed}, 'additional_checks': {},
            'claims': {}, 'oracle_answer': deepcopy(self.bound_instance['prepared'].get('reference', {})),
            'source_artifact_sha256': {str(self.path): self.instance_pin,
                CAPTURE: file_hash(directory/CAPTURE),
                'automatic-grade.json': file_hash(directory/'automatic-grade.json')},
            'derivations': [deepcopy(value['native_grade'])],
            'extractor': {'model': 'none', 'provider': 'none', 'version': 'native_host_capture'},
                'limitations': ['Native state/action grading; no answer formatter was dispatched.',
                'Only the declared retailer mechanism is assessed; broader effects remain unknown.'],
            'safe_success': None, 'full_response_evaluated': False}
        _save_new(directory/FILENAME, sidecar)
        checked = read_grade(directory)
        if checked is None or checked.get('binding_status') != 'verified':
            raise ValueError('Commercial grade missing from shared viewer adapter')
        return checked
