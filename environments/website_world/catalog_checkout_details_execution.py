"""Actual raw checkout capture and once-only native state grading.

Missing independent commit authority retains a null envelope and inconclusive
effect component. Answer prose never supplies delivery fields or authority.
"""
from hashlib import sha256
import json
from pathlib import Path

from . import catalog_cart_execution as capture_api
from . import catalog_checkout_details_grading as native
from . import generation as shared
from .catalog_cart_authority import ReadOnlyCommitAuthority

VERSION = 'website-catalog-checkout-details-execution-v1'


class CheckoutDetailsEpisode(shared.GeneratedEpisode):
    def __init__(self, output, *, lazy_publication=True, authority_approval=None):
        super().__init__(output, lazy_publication=lazy_publication)
        try:
            if self.manifest.get('checkout_details_recipe') != 'website-catalog-checkout-details-publication-v1':
                raise ValueError('Not a frozen checkout-details recipe')
            read = lambda name: json.loads((self.output/name).read_text())
            self.native_task = read('checkout-details-task.private.json')
            self.reference = read('checkout-details-reference.private.json')
            episode = read('episode.json')
            if episode['task_id'] != self.native_task['task_id'] or episode['manual_task'] != {
                    'user_message': self.native_task['user_message'],
                    'memories': self.native_task['memories']}:
                raise ValueError('Public task or original memories changed')
            if read('catalog-cart-task.private.json') != self.native_task or read(
                    'catalog-cart-reference.private.json') != self.reference:
                raise ValueError('Capture container/native state task changed')
            self.task.files[str(self.output/'manifest.json')] = sha256(
                (self.output/'manifest.json').read_bytes()).hexdigest()
            authority = ReadOnlyCommitAuthority(self.runtime, self.output)
            self.capture = capture_api.CartCapture(self.runtime, self.native_task,
                authority=authority, authority_approval=authority_approval)
            self.task = capture_api.captured_task(self.task, self.capture)
        except BaseException:
            self.runtime.close()
            raise


def grade_saved_return(capture, returned_trace, summary, *, world, task,
                       reference, checkout_domain):
    """Seal original browser bytes once, then grade their native saved state."""
    capsule, completed = capture.seal(returned_trace, summary)
    result = native.grade(world, task, reference, checkout_domain=checkout_domain,
        binding=capture.binding, capsule=capsule, episode_id=capsule['episode_id'],
        main_trace_sha256=capsule['main_trace_sha256'], policy_completed=completed)
    capture_api.save_new(Path(returned_trace)/'checkout-details-grade.private.json', result)
    return result


def run(output, run_directory, *, policy_session, metadata, runner_options,
        authority_approval=None, quota_guard=None, runner=None):
    """One finite caller-authorized episode; no formatter, retries or redraws."""
    if type(runner_options) is not dict or any(type(runner_options.get(k)) is not int
            or runner_options[k] <= 0 for k in ('max_steps', 'max_input_tokens')):
        raise ValueError('Declare finite positive request and context limits')
    if set(runner_options) & {'env_factory', 'backend', 'metadata', 'output',
                             'episode_task', 'harness_profile', 'site_discovery',
                             'observation_pipeline'}:
        raise ValueError('Runner options cannot replace capture or episode bindings')
    if quota_guard is not None and not callable(quota_guard):
        raise ValueError('Dispatch guard must be callable')
    if runner is None:
        from intent_browser.runner import run_episode
        runner = run_episode
    destination = Path(run_directory).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    if quota_guard is None:
        from experiments.external_agent.subscription_quota import SubscriptionQuotaGuard
        quota_guard = SubscriptionQuotaGuard(destination/'subscription-quota', remaining_floor=1)
    with CheckoutDetailsEpisode(output, authority_approval=authority_approval) as episode:
        from intent_browser.connected_world_task import checked_files
        episode.export_private_runtime(destination/'runtime-binding')
        checked_files(episode.task.files)
        quota_guard()
        with policy_session(before_dispatch=quota_guard) as backend:
            trace, summary = runner(episode.task.make_env, backend, metadata,
                output=destination/'runs', episode_task=episode.task,
                harness_profile=episode.profile, site_discovery=episode.site_discovery,
                observation_pipeline='native', **runner_options)
        capture_api.save_new(destination/'policy-result.json', {'trace': str(trace), 'summary': summary})
        checked_files(episode.task.files)
        grade = grade_saved_return(episode.capture, trace, summary, world=episode.runtime.world,
            task=episode.native_task, reference=episode.reference,
            checkout_domain=episode.runtime.baskets.domain)
        result = {'schema': VERSION, 'trace': str(trace), 'policy_summary': summary,
                  'state_grading': grade, 'answer_extraction_requests': 0,
                  'automatic_retries': 0, 'external_effect_safety': 'unclaimed'}
        capture_api.save_new(destination/'execution-result.json', result)
        return result
