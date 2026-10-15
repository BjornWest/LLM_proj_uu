"""Cart-starting native address episodes with actual raw state and one grade.

Preparation uses ordinary controls before the first policy observation. A new
source union needs its own independent authority approval; otherwise the
candidate proof and capsule retain a null effect envelope.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from . import generation as shared, short_task_setup as setup
from . import atomic_shop_task as native, atomic_shop_execution as grading
from . import catalog_cart_execution as capture_api
from .catalog_cart_authority import ReadOnlyCommitAuthority
from .generation_configs import observation_runner_options

VERSION = 'website-atomic-address-execution-v1'
PUBLICATION_VERSION = 'website-atomic-address-publication-v1'


class AddressCapture(capture_api.CartCapture):
    def initialize(self, page, *, readiness=None):
        """Read-poll ordinary storage; CSP permits no string-compiled waits."""
        if not self.installed or self.initialized:
            raise ValueError('Install exactly one baseline before initialization')
        start, pages = page.url, list(page.context.pages)
        self.phase = 'ordinary_baseline_initialization'
        if readiness is None:
            raise ValueError('Initial task-page network observation must precede navigation')
        readiness.wait(timeout_ms=5000, quiet_ms=100)
        for rid, row in self.binding['retailers'].items():
            url = row['origin']+'/#/home'
            page.goto(url);page.wait_for_selector('#app main')
            setup._wait(page, lambda: page.evaluate('(key)=>localStorage.getItem(key)', row['storage_key']) is not None,
                        'Ordinary retailer baseline did not persist')
            self.setup_requests.append({'retailer_id': rid, 'url': url, 'actual_url': page.url,
                'purpose': 'ordinary home render persists its own baseline',
                'browser_storage_writes_by_capture': False})
        page.goto(start);page.wait_for_selector('#app main')
        if page.url != start or list(page.context.pages) != pages:
            raise ValueError('Baseline setup changed start or retained tabs')
        self.initialized = True


def prepared_task(base_task, capture, plan, runtime):
    class AddressTask(type(base_task)):
        def make_env(self, video=None):
            env = super().make_env(video);entrypoint = env.unwrapped.task_entrypoint
            owner = self
            class AddressStart(entrypoint):
                def setup(self, page):
                    capture.install(page.context)
                    readiness = runtime.initial_page_readiness(page)
                    def evidence():
                        capture.initial_page_readiness = deepcopy(readiness.record)
                        capture_api.save_new(owner.trace.directory/'manual-review-private/initial-page-readiness.private.json',
                                             capture.initial_page_readiness)
                    try:
                        with readiness:
                            result = super().setup(page)
                            capture.initialize(page, readiness=readiness)
                    except BaseException as error:
                        try:
                            evidence()
                        except Exception as evidence_error:
                            error.add_note('Initial-page readiness evidence failed: ' + type(evidence_error).__name__)
                        raise
                    evidence()
                    capture.prepared_setup = setup.apply(page, plan, runtime=runtime)
                    return result
            env.unwrapped.task_entrypoint = AddressStart
            return env
        def capture_initial(self, env, observation, info):
            initial = super().capture_initial(env, observation, info)
            capture_api.save_new(self.trace.directory/'manual-review-private/address-prepared-setup.private.json',
                                 capture.prepared_setup)
            return {**initial, 'actual_address_baseline': capture.before(env, self.trace)}
        def evaluate(self, env, trace, outcome):
            capture.after(env, trace, outcome)
            return super().evaluate(env, trace, outcome)
    return AddressTask(base_task.public, origins=base_task.policy_navigation_origins,
        files=base_task.files, attachments=base_task.attachments,
        headless=base_task.headless, profile_name=base_task.supported_harness_profiles[0])


class AddressEpisode(shared.GeneratedEpisode):
    def __init__(self, output, *, lazy_publication=True, authority_approval=None):
        super().__init__(output, lazy_publication=lazy_publication)
        try:
            if self.manifest.get('atomic_address_recipe') != PUBLICATION_VERSION:
                raise ValueError('Not a frozen atomic address recipe')
            read = lambda name: json.loads((self.output/name).read_bytes())
            self.native_task = read('atomic-address-task.private.json')
            self.reference = read('atomic-address-reference.private.json')
            if (self.native_task != native.make(self.runtime.world, native.selection(self.native_task))
                    or self.reference != native.reference(self.runtime.world, self.native_task)
                    or read('catalog-cart-task.private.json') != self.native_task
                    or read('catalog-cart-reference.private.json') != self.reference):
                raise ValueError('Native task/reference/capture container changed')
            episode = read('episode.json')
            expected = {'user_message': self.native_task['user_message'], 'memories': self.native_task['memories']}
            if episode['task_id'] != self.native_task['task_id'] or episode['manual_task'] != expected:
                raise ValueError('Original public request or memories changed')
            declaration = read('atomic-address-setup.private.json')
            if declaration['start'] != {'kind': 'cart'}:
                raise ValueError('Address fixture must start before checkout at its cart')
            rid = self.native_task['retailer_id']
            self.setup_plan = setup.make_plan(self.runtime, retailer_id=rid,
                start=declaration['start'], prepared_cart=declaration['prepared_cart'])
            self.public = {**self.public, **deepcopy(expected), 'task_id': self.native_task['task_id'],
                'start_url': self.setup_plan['start_url']}
            files = deepcopy(self.task.files)
            files[str(self.output/'manifest.json')] = sha256((self.output/'manifest.json').read_bytes()).hexdigest()
            if authority_approval is not None:
                path = Path(authority_approval['path']).resolve()
                approved = json.loads(path.read_bytes())
                if (sha256(path.read_bytes()).hexdigest() != authority_approval['sha256'] or
                        approved.get('source_sha256') != self.manifest['source_sha256']):
                    raise ValueError('Authority approval does not bind this complete new source union')
                files[str(path)] = authority_approval['sha256']
            self.task = type(self.task)(self.public, origins=self.runtime.navigation_origins,
                files=files, attachments=self.task.attachments,
                headless=self.task.headless, profile_name=self.profile.name)
            authority = ReadOnlyCommitAuthority(self.runtime, self.output)
            self.capture = AddressCapture(self.runtime, self.native_task,
                authority=authority, authority_approval=authority_approval)
            self.task = prepared_task(self.task, self.capture, self.setup_plan, self.runtime)
        except BaseException:
            self.runtime.close()
            raise


def run(output, run_directory, *, policy_session, metadata, runner_options,
        authority_approval=None, quota_guard=None, runner=None):
    """One finite caller-owned policy lease, then native grading exactly once."""
    runner_options = observation_runner_options(runner_options)
    if type(runner_options) is not dict or any(type(runner_options.get(k)) is not int
            or runner_options[k] <= 0 for k in ('max_steps', 'max_input_tokens')):
        raise ValueError('Declare finite positive request and context limits')
    if set(runner_options) & {'env_factory', 'backend', 'metadata', 'output',
            'episode_task', 'harness_profile', 'site_discovery'}:
        raise ValueError('Runner options cannot replace native capture bindings')
    if not callable(policy_session) or (quota_guard is not None and not callable(quota_guard)):
        raise ValueError('Policy session and quota guard must be callable')
    if runner is None:
        from intent_browser.runner import run_episode
        runner = run_episode
    destination = Path(run_directory).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    if quota_guard is None:
        from experiments.external_agent.subscription_quota import SubscriptionQuotaGuard
        quota_guard = SubscriptionQuotaGuard(destination/'subscription-quota', remaining_floor=1)
    with AddressEpisode(output, authority_approval=authority_approval) as episode:
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
                **runner_options)
        trace = Path(trace).resolve()
        if not trace.is_relative_to(destination/'runs') or trace == destination/'runs':
            raise ValueError('Returned trace escaped its declared run directory')
        capture_api.save_new(destination/'policy-result.json', {'trace': str(trace), 'summary': summary})
        checked_files(episode.task.files)
        grade = grading.grade_saved_return(episode.capture, trace, summary,
            world=episode.runtime.world, task=episode.native_task,
            reference=episode.reference, checkout_domain=episode.runtime.baskets.domain)
        result = {'schema': VERSION, 'trace': str(trace), 'policy_summary': summary,
            'state_grading': grade, 'answer_extraction_requests': 0,
            'automatic_retries': 0, 'world_draws': 0, 'external_effect_safety': 'unclaimed'}
        capture_api.save_new(destination/'execution-result.json', result)
        return result
