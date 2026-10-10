"""Prospective actual-storage capsule. Runtime launch remains explicitly held.

No answer or reference witness writes browser storage. An absent authoritative
whole-run effect journal stays absent and cannot establish a passing state task.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from .adapter import digest
from . import catalog_cart_grading as native
from .catalog_cart_authority import AuthorityError, ReadOnlyCommitAuthority

VERSION = 'website-catalog-cart-execution-v1'


def save_new(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')


def actual_storage_binding(runtime):
    """Map every actual public SKU/offer/origin; retain aliases separately."""
    rows = {}
    for retailer in runtime.world['retailers']:
        rid = retailer['retailer_id'];keys = {}
        for page in runtime.public_catalogs[rid]['products']:
            for variant in page['variants']:
                sku, offer = variant['skuId'], variant['offerId']
                if sku in keys: raise ValueError('Ambiguous public SKU storage identity')
                keys[sku] = offer
        rows[rid] = {'origin': runtime.origins[rid],
            'storage_key': 'website-drafts.state.'+rid, 'offer_keys': keys}
    return native.storage_binding(runtime.world, rows)


class CartCapture:
    """Callbacks operate on the actual live context and write exclusive artifacts."""
    def __init__(self, runtime, task, *, authority=None, authority_approval=None):
        self.runtime, self.task = runtime, deepcopy(task)
        if authority is not None and (type(authority) is not ReadOnlyCommitAuthority or authority.runtime is not runtime):
            raise ValueError('Authority must belong to this exact runtime')
        self.authority, self.authority_approval = authority, deepcopy(authority_approval)
        self.authority_failures = []
        self.binding = actual_storage_binding(runtime)
        self.artifacts, self.requests, self.setup_requests = {}, [], []
        self.phase, self.installed, self.initialized = 'before_initial_navigation', False, False
        self.trace = None

    def install(self, context):
        if self.installed: raise ValueError('Capture context already installed')
        self.installed = True
        def request(req):
            self.requests.append({'phase': self.phase, 'url': req.url,
                'method': req.method, 'resource_type': req.resource_type,
                'is_navigation': req.is_navigation_request()})
        context.on('request', request)
        # Passive request provenance is not an authoritative commit journal.

    def snapshot(self, context, trace, name, phase):
        if name in self.artifacts: raise FileExistsError(name)
        if self.trace is not None and self.trace is not trace: raise ValueError('Capture trace changed')
        self.trace = trace
        private = trace.directory/'manual-review-private'
        path = private/('cart-'+name+'.private.json')
        record = {'phase': phase, 'storage_state': context.storage_state()}
        save_new(path, record)
        self.artifacts[name] = {'path': str(path.resolve()), 'sha256': sha256(path.read_bytes()).hexdigest()}
        return deepcopy(self.artifacts[name])

    def snapshot_environment(self, env, trace, name, phase):
        page = env.unwrapped.page
        try:
            record = self.snapshot(page.context, trace, name, phase)
        finally:
            # Playwright storage_state may visit origins in an internal page
            # and close it. Recover BrowserGym's active page through its own
            # routine, then require the original task page to remain active.
            env.unwrapped._active_page_check()
        if env.unwrapped.page is not page:
            raise ValueError('Storage capture changed the active task page')
        return record

    def initialize(self, page):
        """Ordinary same-tab home renders during setup; restore the start URL."""
        context = page.context
        if not self.installed: raise ValueError('Capture must begin before initial navigation')
        if self.initialized: raise ValueError('Baseline already initialized')
        start_url, original_pages = page.url, list(context.pages)
        self.phase = 'ordinary_baseline_initialization'
        for rid, row in self.binding['retailers'].items():
            url = row['origin']+'/#/home'
            page.goto(url, timeout=30000);page.wait_for_selector('#app main')
            # The ordinary renderer calls save() from render(). Read only.
            page.wait_for_function('(key)=>localStorage.getItem(key)!==null', arg=row['storage_key'])
            self.setup_requests.append({'retailer_id': rid, 'url': url,
                'actual_url': page.url, 'purpose': 'ordinary home render persists its own version2 baseline',
                'browser_storage_writes_by_capture': False})
        page.goto(start_url, timeout=30000)
        if page.url != start_url or list(context.pages) != original_pages:
            raise ValueError('Baseline setup changed initial page or retained tabs')
        self.initialized = True

    def before(self, env, trace):
        if not self.initialized: raise ValueError('Initialize baseline during environment setup before policy navigation boundary')
        self.phase = 'before_policy'
        record = self.snapshot_environment(env, trace, 'before', 'before_policy')
        # Missing/invalid state is retained raw and must not become an empty cart.
        save_new(trace.directory/'manual-review-private/cart-storage-binding.private.json', self.binding)
        save_new(trace.directory/'manual-review-private/cart-baseline-setup.private.json', {
            'setup_navigation': self.setup_requests, 'initial_page_retained': True,
            'effect_on_initial_environment': 'All ordinary retailer homes were loaded in the existing tab during environment setup, then the original start URL was restored; their scripts persist actual default states before policy.',
            'logical_origins': getattr(self.runtime.origin_map, 'descriptor', None),
            'preview_origins': getattr(self.runtime, 'preview_origins', self.runtime.origins),
            'runtime_source_sha256': self.runtime.sources,
            'renderer_asset_sha256': self.runtime.asset_hashes})
        self._checkpoint_authority('before_policy',trace)
        self.phase = 'policy'
        return record

    def after(self, env, trace, outcome):
        self.phase = 'after_policy_before_context_close'
        record = self.snapshot_environment(env, trace, 'after', self.phase)
        self._checkpoint_authority('after_policy_before_context_close',trace)
        save_new(trace.directory/'manual-review-private/cart-terminal-outcome.private.json', deepcopy(outcome))
        save_new(trace.directory/'manual-review-private/cart-requests.private.json', {
            'requests': self.requests, 'scope': 'Passive complete-context request observations; not commit authority',
            'effect_journal_accepted': False})
        return record

    def _checkpoint_authority(self, phase, trace):
        if self.authority is None: return
        try:
            self.authority.checkpoint(phase,trace)
        except (AuthorityError,ValueError,KeyError,TypeError,AttributeError) as e:
            failure={'phase':phase,'error':str(e)}
            self.authority_failures.append(failure)
            save_new(trace.directory/'manual-review-private'/('cart-authority-failure-'+phase+'.json'),failure)

    def seal(self, returned_trace, summary):
        path = Path(returned_trace).resolve()
        if self.trace is None or path != self.trace.directory.resolve():
            raise ValueError('Capsule requires the actual captured returned main trace')
        metadata = json.loads((path/'metadata.json').read_text())
        if metadata['episode_id'] != self.trace.episode_id: raise ValueError('Episode identity changed')
        raw = {}
        for name in ['before', 'after']:
            record = self.artifacts.get(name)
            if record is None: raise ValueError('Actual browser capture phase missing: '+name)
            captured = Path(record['path'])
            if not captured.is_relative_to(path) or sha256(captured.read_bytes()).hexdigest()!=record['sha256']:
                raise ValueError('Captured storage artifact changed')
            raw[name] = json.loads(captured.read_text())
        terminal = json.loads((path/'manual-review-private/cart-terminal-outcome.private.json').read_text())
        if any(terminal[k] != summary[k] for k in ['stop_reason','terminated','truncated']):
            raise ValueError('Returned policy outcome differs from live terminal capture')
        completed = (summary['stop_reason'] in ['agent_finished','terminated']
            and not summary.get('error') and not summary.get('execution_error')
            and not summary.get('truncated'))
        trace_hash = sha256((path/'steps.jsonl').read_bytes()).hexdigest()
        effect_journal,authority_provenance=None,None
        authority=getattr(self,'authority',None)
        if authority is not None:
            try:
                proof=authority.seal(path,episode_id=metadata['episode_id'],main_trace_sha256=trace_hash,
                    captures=self.artifacts,approval=self.authority_approval)
                effect_journal=proof['native_effect_envelope']
            except (AuthorityError,ValueError,KeyError,TypeError,AttributeError) as e:
                proof={'schema':authority.initial.get('schema','website-catalog-cart-read-only-authority-v1'),
                    'status':'failed_or_unaccepted','error':str(e),'failures':getattr(self,'authority_failures',[]),
                    'native_effect_envelope':None}
            proof_path=path/'cart-authority.private.json';save_new(proof_path,proof)
            authority_provenance={'path':str(proof_path),'sha256':sha256(proof_path.read_bytes()).hexdigest(),
                'status':proof['status'],'scope':'Generated authoritative commits only; no external-effect certification'}
        capsule = {'schema_version': native.CAPSULE_VERSION,
            'task_sha256': digest(self.task), 'binding_sha256': digest(self.binding),
            'episode_id': metadata['episode_id'], 'main_trace_sha256': trace_hash,
            'before': raw['before'], 'after': raw['after'],
            'effect_journal': deepcopy(effect_journal)}
        save_new(path/'cart-capsule.private.json', capsule)
        save_new(path/'cart-capture-provenance.private.json', {
            'captures': self.artifacts, 'policy_completed': completed,
            'main_trace_source': 'Actual returned immutable steps.jsonl, excluding later grade sidecars',
            'main_trace_sha256': trace_hash, 'runtime_source_sha256': self.runtime.sources,
            'renderer_asset_sha256': self.runtime.asset_hashes,
            'effect_authority': authority_provenance,
            'native_effect_envelope_source': 'Independent accepted read-only empty-set proof' if effect_journal else 'Missing/unaccepted; inconclusive',
            'external_effect_safety': 'unclaimed'})
        return capsule, completed


def captured_task(base_task, capture):
    """Private subclass preserves the existing logical-origin setup and task API."""
    class CapturedCartTask(type(base_task)):
        def make_env(self, video=None):
            env = super().make_env(video);base_entrypoint = env.unwrapped.task_entrypoint
            class CaptureStart(base_entrypoint):
                def setup(self, page):
                    capture.install(page.context)
                    result = super().setup(page)
                    capture.initialize(page)
                    return result
            env.unwrapped.task_entrypoint = CaptureStart
            return env
        def capture_initial(self, env, observation, info):
            initial = super().capture_initial(env, observation, info)
            return {**initial, 'actual_cart_baseline': capture.before(env, self.trace)}
        def evaluate(self, env, trace, outcome):
            capture.after(env, trace, outcome)
            return super().evaluate(env, trace, outcome)
    return CapturedCartTask(base_task.public, origins=base_task.policy_navigation_origins,
        files=base_task.files, attachments=base_task.attachments,
        headless=base_task.headless, profile_name=base_task.supported_harness_profiles[0])


def grade_saved_return(capture, returned_trace, summary, *, world, task,
                       reference, checkout_domain):
    """Prospective once-only native state grade, with no formatter reconstruction."""
    capsule, completed = capture.seal(returned_trace, summary)
    result = native.grade(world, task, reference, checkout_domain=checkout_domain,
        binding=capture.binding, capsule=capsule, episode_id=capsule['episode_id'],
        main_trace_sha256=capsule['main_trace_sha256'], policy_completed=completed)
    save_new(Path(returned_trace)/'cart-grade.private.json', result)
    return result


def run(*args, **kwargs):
    raise RuntimeError('Source-only cart capture preparation; native and whole-run effect acceptance pending')
