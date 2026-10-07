"""Explicit private Runtime copy and pre-reset provider installation.

These helpers do not replace shared Website/Harness modules. The integration
caller owns exact dependency approval, file bindings and native acceptance.
"""
from hashlib import sha256
from pathlib import Path
from types import ModuleType

from .fact_render_overlay import _once, overlay_assets


def copied_runtime(source_path, output_path, private_mount, *, expected_sha256):
    """Materialize the copied runtime before any HTTP host captures a handler.

    Bind this class explicitly in a separately copied consumer; importing the
    shared .runtime in its constructor would still select the original class.
    The written copy and helper/producer sources must enter the episode closure.
    """
    source_path, output_path = Path(source_path).resolve(), Path(output_path).resolve()
    raw = source_path.read_bytes()
    if sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('Runtime source pin changed')
    source = _once(raw.decode(), '        self.asset_hashes = {name: sha256(body).hexdigest() for name, body in assets.items()}',
        '        assets, self.fact_recording_asset_receipt = _fact_overlay_assets(assets, enabled=True)\n'
        '        self.asset_hashes = {name: sha256(body).hexdigest() for name, body in assets.items()}')
    if output_path == source_path:
        raise ValueError('Cannot overwrite the Website Runtime')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('x') as stream:
        stream.write(source)
    module = ModuleType('environments.website_world._fact_runtime_copy')
    module.__package__ = 'environments.website_world'
    module.__file__ = str(output_path)
    module.__dict__['_fact_overlay_assets'] = overlay_assets
    exec(compile(source, str(output_path), 'exec'), module.__dict__)
    if Path(module.ROOT).resolve() != source_path.parents[2]:
        raise ValueError('Runtime imports escaped the frozen source root')
    if not callable(private_mount.mount):
        raise ValueError('Private review mount callable required')
    module.mount_surrounding = private_mount.mount
    return module, {'schema': 'fact-runtime-copy-installation-v1',
        'original': str(source_path), 'original_sha256': expected_sha256,
        'copy': str(output_path), 'copy_sha256': sha256(output_path.read_bytes()).hexdigest(),
        'mount_global': 'mount_surrounding', 'shared_files_modified': False,
        'runtime_accepted': False}


def recording_env_factory(task, provider):
    """Install on the policy page before inherited setup navigates/captures.

    The caller also supplies provider.observe/provider to Harness's released
    native callback options. This wrapper does not capture or retry observations.
    """
    original = task.make_env
    if not provider.enabled:
        return original

    def make_env(video=None):
        env = original(video)
        base = getattr(env, 'unwrapped', env)
        entrypoint = base.task_entrypoint
        if not isinstance(entrypoint, type):
            env.close()
            raise ValueError('Recording requires the declared native task class')

        class RecordingStart(entrypoint):
            def setup(self, page):
                provider.page = page
                provider.install()
                return super().setup(page)

        base.task_entrypoint = RecordingStart
        original_close = env.close

        def close():
            provider_error = None
            try:
                provider.close()
            except BaseException as error:
                provider_error = error
            try:
                original_close()
            except BaseException as browser_error:
                if provider_error is not None:
                    # The released runner persists str(exc); both failures must
                    # be present there, not only in exception chaining.
                    raise RuntimeError(
                        f'Fact provider cleanup failed ({type(provider_error).__name__}): {provider_error}; '
                        f'browser cleanup failed ({type(browser_error).__name__}): {browser_error}'
                    ) from browser_error
                raise
            if provider_error is not None:
                raise provider_error

        env.close = close
        return env

    return make_env


def copied_execution(source_path, output_path, runtime_module, provider, *,
                     expected_sha256, trusted_files):
    """Explicitly bind the copied Runtime and released native provider options.

    Only a separately approved compound execution source can be used. Its
    external AutomaticGrading/cleanup/identity guards remain unchanged. The
    caller supplies exact hashes of the helper, producer and dependency files;
    they are checked now and included in the task's existing pre-dispatch checks.
    No shared import/module global is replaced.
    """
    source_path, output_path = Path(source_path).resolve(), Path(output_path).resolve()
    if not provider.enabled:
        raise ValueError('Copied execution requires explicitly enabled recording')
    raw = source_path.read_bytes()
    if sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('Compound execution source pin changed')
    source = raw.decode()
    source = _once(source, '        from .runtime import Runtime',
                   '        Runtime = _fact_private_runtime.Runtime')
    source = _once(source, '            self.task.site_discovery_callback = self.site_discovery',
                   '            self.task.site_discovery_callback = self.site_discovery\n'
                   '            _fact_check_files(_fact_trusted_files)\n'
                   '            if any(name in self.task.files and self.task.files[name] != pin\n'
                   '                   for name, pin in _fact_trusted_files.items()):\n'
                   '                raise ValueError(\"Recording source conflicts with task source binding\")\n'
                   '            self.task.files.update(_fact_trusted_files)')
    source = _once(source, 'runner(episode.task.make_env, backend, bound_metadata,',
                   'runner(_fact_env_factory(episode.task, _fact_provider), backend, bound_metadata,')
    source = _once(source, "observation_pipeline='native', terminal_response_instruction=TERMINAL_INSTRUCTION,",
                   'observation_pipeline=None, record_fact_provenance=True,\n'
                   '                    fact_source_provider=_fact_provider, fact_capture_observer=_fact_provider.observe,\n'
                   '                    terminal_response_instruction=TERMINAL_INSTRUCTION,')
    source = _once(source, "'automatic_grading', 'allow_ungraded', 'ungraded_reason', 'agent_runtime', 'agent_actor'",
                   "'automatic_grading', 'allow_ungraded', 'ungraded_reason', 'agent_runtime', 'agent_actor', "
                   "'record_fact_provenance', 'fact_source_provider', 'fact_capture_observer'")
    if output_path == source_path:
        raise ValueError('Cannot overwrite Website execution')
    pins = {}
    for name, expected in trusted_files.items():
        path = Path(name).resolve()
        if not Path(name).is_absolute() or sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Trusted recording source pin changed: '+str(name))
        pins[str(path)] = expected
    helper = Path(__file__).resolve()
    if pins.get(str(helper)) != sha256(helper.read_bytes()).hexdigest():
        raise ValueError('Recording installation helper must be source-pinned')
    runtime_copy = Path(runtime_module.__file__).resolve()
    if pins.get(str(runtime_copy)) != sha256(runtime_copy.read_bytes()).hexdigest():
        raise ValueError('Private Runtime copy must be source-pinned')
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open('x') as stream:
        stream.write(source)
    pins[str(source_path)] = expected_sha256
    pins[str(output_path)] = sha256(output_path.read_bytes()).hexdigest()
    module = ModuleType('environments.website_world._fact_execution_copy')
    module.__package__ = 'environments.website_world'
    module.__file__ = str(output_path)
    from intent_browser.connected_world_task import checked_files
    module.__dict__.update(_fact_private_runtime=runtime_module,
        _fact_provider=provider, _fact_env_factory=recording_env_factory,
        _fact_trusted_files=pins, _fact_check_files=checked_files)
    exec(compile(source, str(output_path), 'exec'), module.__dict__)
    return module, {'schema': 'fact-execution-copy-installation-v1',
        'original': str(source_path), 'original_sha256': expected_sha256,
        'copy': str(output_path), 'copy_sha256': pins[str(output_path)],
        'source_files': pins, 'observation_pipeline': None,
        'record_fact_provenance': True, 'shared_files_modified': False,
        'runtime_accepted': False}
