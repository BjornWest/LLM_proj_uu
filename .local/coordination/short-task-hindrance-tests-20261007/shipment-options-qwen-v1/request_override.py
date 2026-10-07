"""Explicit new policy wording over an unchanged saved native fixture.

This is presentation preparation, not shipment-answer grader certification or
authorization to dispatch a model. Native address outcomes remain components.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path


def request_task(original, declaration_path):
    path = Path(declaration_path).resolve()
    payload = path.read_bytes()
    declaration = json.loads(payload)
    public = deepcopy(original.public)
    if public['task_id'] != declaration['native_task_id']:
        raise ValueError('Wording override belongs to another native task')
    if public['memories'] != declaration['memories']:
        raise ValueError('Wording override must preserve original memories')
    for field in ('native_task', 'recipe_manifest'):
        record = declaration[field]
        if sha256(Path(record['path']).read_bytes()).hexdigest() != record['sha256']:
            raise ValueError('Original fixture binding changed')
    message = declaration['user_message']
    if not isinstance(message, str) or not message.strip():
        raise ValueError('Explicit nonempty user request required')
    binding = {'native_task_id': declaration['native_task_id'], 'user_message': message}
    identity = 'shipment-options-wording-' + sha256(
        json.dumps(binding, sort_keys=True).encode()).hexdigest()[:24]
    if (declaration['task_id'] != identity or declaration['request_variant_id'] != identity
            or declaration['formal_outcome_task_id'] != declaration['native_task_id']):
        raise ValueError('Changed wording/task identity binding')
    public.update(user_message=message)  # Same formal address outcome; separate request variant ID.
    files = dict(original.files)
    files[str(path)] = sha256(payload).hexdigest()
    revised = type(original)(public, origins=original.policy_navigation_origins,
        files=files, attachments=original.attachments, headless=original.headless,
        profile_name=original.supported_harness_profiles[0])
    return revised


def wording_runner(runner, declaration_path):
    """Supported supplied-runner hook; no private fixture checks are disabled."""
    def call(env_factory, backend, metadata, **options):
        original = options['episode_task']
        if getattr(env_factory, '__self__', None) is not original:
            raise ValueError('Runner environment is not bound to the original task')
        revised = request_task(original, declaration_path)
        options = {**options, 'episode_task': revised}
        metadata = {**metadata, 'wording_native_task_id': original.public['task_id'],
                    'wording_variant_id': json.loads(Path(declaration_path).read_bytes())['task_id'],
                    'grading_scope': 'captured_address_state',
                    'shipment_answer_grading_ready': False}
        return runner(revised.make_env, backend, metadata, **options)
    return call
