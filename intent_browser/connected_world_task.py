"""Manual-review connected-world episodes; no oracle, formatter or inference here.

Only the explicit public projection enters the policy goal. Private references are
copied byte-for-byte into trace attachments for human review, never served as pages.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from .evaluation import Evaluation
from .navigation import origin
from .trace import write_json

VERSION = 'connected-world-manual-v1'
PUBLIC_FIELDS = ('schema_version', 'task_id', 'user_message', 'memories',
                 'environment_context', 'start_url')
TERMINAL_INSTRUCTION = (
    'When finished, use send_msg_to_user to give a clear, self-contained natural answer '
    'to the user, with the requested details and relevant source links. Explain missing '
    'information honestly. No JSON or grading envelope is required. Research does not '
    'authorize purchases, account creation or other persistent account changes.'
)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def public_projection(value):
    """Allowlist at the task boundary. Nested memories/context are authored public data."""
    result = {k: deepcopy(value[k]) for k in PUBLIC_FIELDS if k in value}
    for k in ('schema_version', 'task_id', 'user_message', 'start_url'):
        if not isinstance(result.get(k), str) or not result[k].strip():
            raise ValueError('Missing public task field: ' + k)
    if not isinstance(result.get('memories'), (dict, list)):
        raise ValueError('memories must be a public object or list')
    if not isinstance(result.get('environment_context'), dict):
        raise ValueError('environment_context must be a public object')
    origin(result['start_url'])
    # Refuse accidental private payloads nested in otherwise public containers.
    forbidden = {'resolved_task', 'hidden_user_specifications', 'allowed_clarification_facts',
                 'manual_reference', 'reference_answer', 'answer_contract', 'candidate_assessments',
                 'best_candidate_ids', 'private_provenance'}
    def inspect(obj):
        if isinstance(obj, dict):
            if forbidden.intersection(obj): raise ValueError('Private/answer field in public task')
            for v in obj.values(): inspect(v)
        elif isinstance(obj, list):
            for v in obj: inspect(v)
    inspect(result)
    json.dumps(result, allow_nan=False)
    return result


def policy_goal(public):
    p = public_projection(public)
    return (p['user_message'] + '\n\nSAVED USER MEMORIES:\n' +
            json.dumps(p['memories'], ensure_ascii=False, sort_keys=True) +
            '\n\nENVIRONMENT CONTEXT:\n' +
            json.dumps(p['environment_context'], ensure_ascii=False, sort_keys=True))


def checked_files(files):
    for name, expected in files.items():
        if sha(name) != expected: raise ValueError('Pinned artifact changed: ' + name)


class ConnectedWorldTask:
    """Fresh browser/storage against a frozen publication, with unknown outcome labels."""
    def __init__(self, public, *, origins, files=None, attachments=None, headless=True,
                 profile_name='core-tools-v12-ax-reuse'):
        self.public = public_projection(public)
        self.policy_goal = policy_goal(self.public)
        self.policy_navigation_origins = tuple(dict.fromkeys(origin(v) for v in origins))
        if origin(self.public['start_url']) not in self.policy_navigation_origins:
            raise ValueError('Start URL outside declared world')
        self.files = dict(files or {})
        self.attachments = dict(attachments or {})
        for name, path in self.attachments.items():
            if Path(name).name != name or name in ('.', '..'):
                raise ValueError('Attachment must be a basename')
            if str(path) not in self.files:
                raise ValueError('Every private attachment requires a pinned hash')
        self.headless = headless
        self.supported_harness_profiles = (profile_name,)
        self.trace = None
        self.initial_chat_messages = []

    def prepare(self, trace):
        checked_files(self.files)
        self.trace = trace
        private = trace.directory / 'manual-review-private'
        private.mkdir()
        attached = {}
        for name, path in self.attachments.items():
            payload = Path(path).read_bytes()
            if hashlib.sha256(payload).hexdigest() != self.files[str(path)]:
                raise ValueError('Attachment changed while copying')
            with (private / name).open('xb') as stream: stream.write(payload)
            attached[name] = self.files[str(path)]
        write_json(trace.directory / 'policy-task.json', self.public)
        return {'source': VERSION, 'task_id': self.public['task_id'],
                'start_url': self.public['start_url'], 'grading': 'manual_only',
                'training_eligible': False, 'artifact_sha256': self.files,
                'private_attachment_sha256': attached,
                'isolation': 'fresh nonpersistent browser context; immutable content shared',
                'state_scope': 'Browser cookies/storage isolated; no server-state clone claim',
                'policy_artifact': 'policy-task.json'}

    def make_env(self, video=None):
        from browsergym.core.env import BrowserEnv
        from browsergym.core.task import OpenEndedTask
        from .actions import make_action_set
        return BrowserEnv(task_entrypoint=OpenEndedTask,
            task_kwargs={'start_url': self.public['start_url'], 'goal': self.policy_goal},
            headless=self.headless, wait_for_user_message=False,
            action_mapping=make_action_set().to_python_code, record_video_dir=video,
            pw_context_kwargs={'accept_downloads': False, 'permissions': [], 'service_workers': 'block'})

    def capture_initial(self, env, observation, info):
        if observation['goal'] != self.policy_goal:
            raise ValueError('Initial policy goal differs from public task projection')
        self.initial_chat_messages = deepcopy(env.unwrapped.chat.messages)
        return {'url': observation['url'], 'goal_sha256': hashlib.sha256(
            self.policy_goal.encode()).hexdigest(), 'browser_context_fresh': True}

    def evaluate(self, env, trace, outcome):
        # BrowserGym records only executed sends here, not skipped batch requests.
        messages = deepcopy(env.unwrapped.chat.messages)
        initial_count = len(self.initial_chat_messages)
        if messages[:initial_count] != self.initial_chat_messages:
            raise ValueError('Initial BrowserGym chat changed unexpectedly')
        answers = [m['message'] for m in messages[initial_count:] if m['role'] == 'assistant']
        write_json(trace.directory / 'natural-answer.json', {
            'schema_version': VERSION, 'text': answers[-1] if answers else None,
            'assistant_messages': answers, 'stop_reason': outcome['stop_reason'],
            'initial_chat_messages_excluded': initial_count,
            'technical_error': outcome.get('error'), 'correctness': None,
            'source': 'BrowserGym chat from executed send_msg_to_user; no extraction or repair'})
        return Evaluation('manual-review', VERSION, trust='ungraded',
            evidence=['natural-answer.json', 'policy-task.json', 'manual-review-private/'],
            limitations=['Natural answer and procedure require manual review; all outcome labels remain unknown.',
                         'No automatic answer extraction, factual scoring or side-effect certification.'])


class PrivateClarificationAdapter:
    """Project a trusted Product responder result to text; retain its audit privately."""
    def __init__(self, responder, task):
        self.responder, self.task = responder, task
        self.count = 0

    def __call__(self, question):
        if self.task.trace is None: raise ValueError('Task must be prepared before clarification')
        result = self.responder(question)
        if not isinstance(result, dict) or not isinstance(result.get('reply'), str):
            raise ValueError('Private responder must return a reply object')
        # Audit fields remain exclusively in private attachments, not tool feedback.
        record = {'question': question, 'result': deepcopy(result)}
        path = self.task.trace.directory/'manual-review-private'/f'responder-{self.count:03d}.json'
        with path.open('x', encoding='utf-8') as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2, allow_nan=False)
        self.count += 1
        return result['reply']


def load_prepared(directory, *, clarification=False, headless=True):
    """Load one prepared case without constructing a model client or running a grader."""
    directory = Path(directory)
    public_path = directory/'public/task.json'
    binding_path = directory/'private/binding.json'
    binding = json.loads(binding_path.read_text())
    if sha(public_path) != binding['public_sha256']:
        raise ValueError('Prepared public task hash mismatch')
    files = {**binding['source_sha256'], str(public_path):sha(public_path),
             str(binding_path):sha(binding_path)}
    from .standard_profile import standard_profile
    profile = standard_profile(navigation_origins=binding['origins'], helpers=False)
    if clarification:
        from .harness import with_clarification
        profile = with_clarification(profile)
    task = ConnectedWorldTask(json.loads(public_path.read_text()), origins=binding['origins'],
        files=files, attachments=binding['attachments'], headless=headless, profile_name=profile.name)
    callback = None
    if clarification:
        from environments.product_world.manual_clarification import FrozenClarificationResponder
        spec = binding.get('clarification')
        if spec is None:
            from environments.product_world.manual_clarification import FALLBACK
            responder = lambda question: {'reply': FALLBACK, 'matched': False, 'audit_id': 'no-additional-facts'}
        else:
            responder = FrozenClarificationResponder(spec)
        callback = PrivateClarificationAdapter(responder, task)
    return task, profile, callback
