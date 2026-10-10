"""Finite matching-cart episodes, raw browser captures and once-only native grades."""
from hashlib import sha256
import json
from pathlib import Path

from . import catalog_cart_execution as capture_api
from . import generation as shared
from .catalog_cart_authority import ReadOnlyCommitAuthority

VERSION = 'website-catalog-cart-live-execution-v1'
PUBLICATION_VERSION = 'website-catalog-cart-live-publication-v1'


class CartLiveEpisode(shared.GeneratedEpisode):
    def __init__(self, output, *, lazy_publication=True, authority_approval=None):
        super().__init__(output, lazy_publication=lazy_publication)
        try:
            if self.manifest.get('cart_live_recipe') != PUBLICATION_VERSION:
                raise ValueError('Not a frozen cart-live recipe')
            read = lambda name: json.loads((self.output/name).read_text())
            self.native_task = read('catalog-cart-task.private.json')
            self.reference = read('catalog-cart-reference.private.json')
            episode = read('episode.json')
            if (self.native_task.get('kind') != 'prepare_matching_carts'
                    or episode['task_id'] != self.native_task['task_id']
                    or episode['manual_task'] != {
                        'user_message': self.native_task['user_message'], 'memories': []}):
                raise ValueError('Public cart task or native task binding changed')
            self.task.files[str(self.output/'manifest.json')] = sha256(
                (self.output/'manifest.json').read_bytes()).hexdigest()
            if authority_approval is not None:
                path = Path(authority_approval['path']).resolve()
                approved = json.loads(path.read_text())
                if (sha256(path.read_bytes()).hexdigest() != authority_approval['sha256']
                        or approved.get('source_sha256') != self.manifest['source_sha256']):
                    raise ValueError('Authority approval does not bind this complete source union')
                self.task.files[str(path)] = authority_approval['sha256']
            authority = ReadOnlyCommitAuthority(self.runtime, self.output)
            self.capture = capture_api.CartCapture(self.runtime, self.native_task,
                authority=authority, authority_approval=authority_approval)
            self.task = capture_api.captured_task(self.task, self.capture)
        except BaseException:
            self.runtime.close()
            raise


def run(output, run_directory, *, policy_session, metadata, runner_options,
        authority_approval=None, quota_guard=None, runner=None):
    """One caller-authorized bounded episode, with no formatter or retry.

    Without a source-union approval, the retained helper emits a candidate with
    a null effect envelope. Native grading retains that uncertainty.
    """
    if type(runner_options) is not dict or any(type(runner_options.get(k)) is not int
            or runner_options[k] <= 0 for k in ('max_steps', 'max_input_tokens')):
        raise ValueError('Declare finite positive request and context limits')
    if set(runner_options) & {'env_factory', 'backend', 'metadata', 'output',
                             'episode_task', 'harness_profile', 'site_discovery',
                             'observation_pipeline'}:
        raise ValueError('Runner options cannot replace capture or episode bindings')
    if not callable(policy_session) or (quota_guard is not None and not callable(quota_guard)):
        raise ValueError('Policy session and dispatch guard must be callable')
    if runner is None:
        from intent_browser.runner import run_episode
        runner = run_episode
    destination = Path(run_directory).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    if quota_guard is None:
        from experiments.external_agent.subscription_quota import SubscriptionQuotaGuard
        quota_guard = SubscriptionQuotaGuard(destination/'subscription-quota', remaining_floor=1)
    with CartLiveEpisode(output, authority_approval=authority_approval) as episode:
        from intent_browser.connected_world_task import checked_files
        episode.export_private_runtime(destination/'runtime-binding')

        def before_dispatch():
            checked_files(episode.task.files)
            quota_guard()

        before_dispatch()
        with policy_session(before_dispatch=before_dispatch) as backend:
            trace, summary = runner(episode.task.make_env, backend, metadata,
                output=destination/'runs', episode_task=episode.task,
                harness_profile=episode.profile, site_discovery=episode.site_discovery,
                observation_pipeline='native', **runner_options)
        # The transport has closed before any capsule sealing or native grading.
        trace = Path(trace).resolve()
        if not trace.is_relative_to(destination/'runs') or trace == destination/'runs':
            raise ValueError('Returned main trace escaped the declared run directory')
        capture_api.save_new(destination/'policy-result.json', {'trace': str(trace), 'summary': summary})
        checked_files(episode.task.files)
        grade = capture_api.grade_saved_return(episode.capture, trace, summary,
            world=episode.runtime.world, task=episode.native_task, reference=episode.reference,
            checkout_domain=episode.runtime.baskets.domain)
        result = {'schema': VERSION, 'trace': str(trace), 'policy_summary': summary,
            'state_grading': grade, 'answer_extraction_requests': 0,
            'automatic_retries': 0, 'external_effect_safety': 'unclaimed'}
        capture_api.save_new(destination/'execution-result.json', result)
        return result
