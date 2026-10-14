"""Optional suite recording on original assets and original capture operations.

No native imports, Website changes, model-specific transport or mutable overlays.
The caller loads this module from an immutable checked inspection package.
"""
from copy import deepcopy
from hashlib import sha256
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

from collections import OrderedDict

from .fact_exposure import object_digest
from .fact_render_capture import capture_from_snapshot, harness_source_packet
from .fact_source_provider import FactSourceProvider

ASSETS = Path(__file__).parent / 'assets'


def checked_asset(name, expected_sources):
    path = (ASSETS / name).resolve()
    raw = path.read_bytes()
    if expected_sources.get(str(path)) != sha256(raw).hexdigest():
        raise ValueError('Changed evaluated inspection asset: ' + name)
    return raw.decode()


def probe_script(expected_sources):
    recorder = checked_asset('native_fact_recorder.js', expected_sources)
    probe = checked_asset('native_fact_probe.js', expected_sources)
    attestation = 'function renderAttestation(root) {' + recorder.split(
        'export function renderAttestation(root) {', 1)[1].split(
        '\nexport function createFactRecorder', 1)[0]
    return ('(async config=>{' + recorder.replace('export function ', 'function ') +
            '\n' + probe + '\nreturn nativeFactProbe(config);})', attestation)


def recording_env_factory(task, provider):
    """Optional class seam: keep the original env if it cannot be instrumented."""
    original = task.make_env

    def make_env(video=None):
        env = original(video)  # Native construction errors retain their outcome.
        base = getattr(env, 'unwrapped', env)
        entrypoint = getattr(base, 'task_entrypoint', None)
        if not isinstance(entrypoint, type):
            provider._unknown(ValueError('Native task entrypoint is not a class'))
            provider.enabled = False
            return env

        original_close = env.close
        def close():
            provider.close()  # Optional cleanup reports its own errors.
            return original_close()
        try:
            class RecordingStart(entrypoint):
                def setup(self, page):
                    provider.page = page
                    provider.install()
                    return super().setup(page)

            base.task_entrypoint = RecordingStart
            env.close = close
        except Exception as error:
            provider._unknown(error)
            provider.enabled = False
            if getattr(base, 'task_entrypoint', None) is not entrypoint:
                base.task_entrypoint = entrypoint
        return env

    return make_env


def validate_native_options(options, *, capture='native'):
    profile = options.get('harness_profile')
    ax = getattr(profile, 'ax_config', None)
    tools = getattr(profile, 'tools', None)
    if not (getattr(ax, 'incremental', False) and getattr(profile, 'delivery_tracking', False)):
        raise ValueError('Recording requires incremental AX and policy delivery tracking')
    if options.get('checkpoint_control') is not None:
        raise ValueError('Recording has no checkpoint-restoration qualification')
    if (getattr(tools, 'human_handover_tools', False) or getattr(profile, 'agent_limits', None)
            or options.get('agent_runtime') is not None or options.get('human_handover') is not None):
        raise ValueError('Recording is qualified for ordinary native episodes only')
    allowed = (None, 'native', 'auto') if capture == 'pipeline' else (None, 'native')
    if options.get('observation_pipeline') not in allowed:
        raise ValueError('Recording cannot replace a progressive observation pipeline')


class NativeSuiteProvider(FactSourceProvider):
    """Private exact-DOM registrations from already loaded public producer data."""
    def __init__(self, *, enabled=False, site_id=None, expected_sources=None):
        super().__init__(enabled=enabled)
        self.site_id = site_id
        self.failures = []
        self.capture_count = 0
        self.script = None
        self.attestation_function = None
        if enabled:
            self.script, self.attestation_function = probe_script(expected_sources or package_pins())

    def install(self):
        try:
            if self.enabled:
                if self.page is None:
                    raise ValueError('Recording requires a page')
                # The private evaluated probe has no renderer callback/global.
                self.cdp = self.page.context.new_cdp_session(self.page)
        except Exception as error:
            self._unknown(error)
            self.enabled = False

    def close(self):
        try:
            super().close()
        except Exception as error:
            self._unknown(error)

    def observe(self, operation):
        if not self.enabled:
            return operation()
        self.capture_count += 1
        self.latest = None
        try:
            self.latest = self.page.evaluate(self.script, {'site_id': self.site_id,
                                                         'revision': self.capture_count})
        except Exception as error:
            self._unknown(error)
        return super().observe(operation)

    def _unknown(self, error):
        super()._unknown(error)
        self.failures.append(dict(capture=self.capture_count, url=getattr(self.page, 'url', None),
            reason='native_capture_pair_unavailable', error_type=type(error).__name__, detail=str(error)))


class PipelineSuiteProvider(NativeSuiteProvider):
    """Same probe, bound to the harness's own background capture.

    For agent-custody fast capture the harness calls ``before_capture`` (one
    private probe evaluation) and ``after_capture`` around its unmarked capture,
    whose public revision bracket proves the probe, DOM snapshot and AX tree saw
    the same page. Normalization uses that capture's DOMSnapshot and AX: no
    render attestations, DOM.getDocument, describeNode or second DOMSnapshot.
    Native observations still use the inherited bracket (``observe``).
    """
    capture_boundary = 'agent-custody-unmarked-v1'

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.pipeline_pairs = OrderedDict()
        self.pending_probe = None

    def install(self):
        # No private CDP session is needed for the pipeline boundary; the native
        # bracket remains available for fallback captures.
        super().install()

    def before_capture(self, page):
        self.pending_probe = None
        if not self.enabled:
            return
        self.capture_count += 1
        try:
            self.pending_probe = page.evaluate(self.script, {'site_id': self.site_id,
                                                             'revision': self.capture_count})
        except Exception as error:
            self._unknown(error)

    def after_capture(self, observation, frame_id):
        """Pure Python on captured data; caller has validated the revision bracket."""
        probe, self.pending_probe = self.pending_probe, None
        if not self.enabled or probe is None:
            return
        try:
            if probe['meta'].get('url') not in (None, observation.get('url')):
                raise ValueError('Probe URL differs from captured observation')
            result = capture_from_snapshot(probe, observation['dom_object'], observation['axtree_object']['nodes'],
                                           snapshot_id=f'render-{probe["revision"]}', frame_id=frame_id)
            raw_hash = object_digest(observation['axtree_object'])
            self.pipeline_pairs[id(observation)] = (observation, raw_hash, result)
            while len(self.pipeline_pairs) > 4:
                self.pipeline_pairs.popitem(last=False)
        except Exception as error:
            self._unknown(error)

    def __call__(self, env, observation, context):
        pair = self.pipeline_pairs.get(id(observation))
        if pair is None:
            return super().__call__(env, observation, context)
        if pair[0] is not observation or pair[1] != object_digest(observation['axtree_object']):
            raise ValueError('Observation was not paired with this pipeline capture')
        packet = harness_source_packet(pair[2]['normalized'])
        for source in packet['sources']:
            source['binding']['snapshot_id'] = context['snapshot_id']
        packet['private_context']['pairing'] = {'raw_ax_sha256': pair[1],
            'render_revision': pair[2]['commit']['revision'], 'source': 'harness_background_capture',
            'capture_boundary': self.capture_boundary, 'extra_ax_captures': 0, 'extra_dom_snapshots': 0,
            'scripted_delivery': False}
        return packet


def package_pins():
    """All modules/assets needed by this private package, before import dispatch."""
    root = Path(__file__).parent
    return {str(p.resolve()): sha256(p.read_bytes()).hexdigest()
            for p in [*root.glob('*.py'), *ASSETS.glob('*.js')]}


def recording_runner(run_episode, *, enabled=False, expected_sources=None, report=None, capture='native'):
    """Return a once-per-episode wrapper; disabled returns the original callable.

    A rejected optional setup records its reason and calls the unchanged runner.
    Ordinary capture errors remain unknown and cannot block policy/grade dispatch.
    Once a policy starts, it is never retried through the disabled path.
    """
    if type(enabled) is not bool:
        raise TypeError('Explicit recording boolean required')
    if capture not in ('native', 'pipeline'):
        raise ValueError('Recording capture must be native or pipeline')
    if not enabled:
        return run_episode
    used = False

    def run(factory, backend, metadata, *args, **options):
        nonlocal used
        if used:
            raise ValueError('Suite recording wrapper is single-episode; create another per case')
        used = True
        status = {'schema': 'native-suite-recording-status-v1', 'enabled': False,
                  'served_assets_modified': False, 'model_specific': False}
        run.recording_status = status
        provider = None
        try:
            native_options = dict(options)
            if args:
                signature = inspect.signature(run_episode)
                bound = signature.bind(factory, backend, metadata, *args, **options)
                first = set(list(signature.parameters)[:3])
                native_options = {}
                for name, value in bound.arguments.items():
                    if name in first:
                        continue
                    if signature.parameters[name].kind in (
                            inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.POSITIONAL_ONLY):
                        raise ValueError('Recording cannot rebind variadic/positional-only options')
                    if signature.parameters[name].kind == inspect.Parameter.VAR_KEYWORD:
                        native_options.update(value)
                    else:
                        native_options[name] = value
            required = {'record_fact_provenance', 'fact_source_provider', 'fact_capture_observer'}
            if not required.issubset(inspect.signature(run_episode).parameters):
                raise ValueError('Native runner lacks capture callback API')
            if not expected_sources or package_pins() != expected_sources:
                raise ValueError('Inspection module/asset closure differs from the approved package')
            if any(name in native_options for name in required):
                raise ValueError('Another source provider is already installed')
            validate_native_options(native_options, capture=capture)
            provider = (PipelineSuiteProvider if capture == 'pipeline' else NativeSuiteProvider)(
                enabled=True, expected_sources=expected_sources)
            if package_pins() != expected_sources:
                raise ValueError('Inspection package changed during provider construction')
            wrapped = recording_env_factory(SimpleNamespace(make_env=factory), provider)
            # Pipeline capture keeps the caller's selection ('auto' may still fall
            # back to native, where the inherited observe bracket applies).
            updated = dict(native_options, record_fact_provenance=True,
                fact_source_provider=provider, fact_capture_observer=provider.observe,
                **({} if capture == 'pipeline' else {'observation_pipeline': None}))
            bound_metadata = deepcopy(metadata)
            bound_metadata['inspection'] = {'enabled': True, 'source': 'native-private-dom-probe-v1',
                                           'capture': capture,
                                           'served_assets_modified': False, 'source_sha256': dict(expected_sources)}
            status['enabled'] = True
        except Exception as error:
            if provider is not None:
                provider.enabled = False
            status.update(setup_error=type(error).__name__, reason=str(error))
            wrapped, updated, bound_metadata = factory, options, metadata
        try:
            return run_episode(wrapped, backend, bound_metadata, *(args if not status['enabled'] else ()), **updated)
        finally:
            if provider is not None:
                status.update(provider_enabled=provider.enabled, capture_count=provider.capture_count,
                              pairing_failures=provider.failures)
            if report is not None:
                # Optional reporting cannot replace a task/transport outcome.
                try:
                    with Path(report).open('x') as stream:
                        json.dump(status, stream, indent=2, ensure_ascii=False)
                        stream.write('\n')
                except Exception as error:
                    status.update(report_error=type(error).__name__, report_error_detail=str(error))
    run.recording_status = None
    return run
