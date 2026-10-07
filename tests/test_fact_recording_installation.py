"""Source/ordering controls; no browser, world, model or live Runtime adoption."""
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest

from training.browser_training.fact_recording_installation import copied_runtime, recording_env_factory


def test_private_copy_selects_mount_before_host_binding_without_shared_changes(tmp_path, monkeypatch):
    import training.browser_training.fact_recording_installation as helper
    monkeypatch.setattr(helper, "overlay_assets", lambda assets, enabled: (dict(assets), {"enabled": enabled}))
    source = tmp_path/'frozen/environments/website_world/runtime.py'
    source.parent.mkdir(parents=True)
    text = f'''from hashlib import sha256
ROOT={str(tmp_path/'frozen')!r}
def mount_surrounding(*args):return 'original'
class Runtime:
    def __init__(self):
        assets={{}}
        self.asset_hashes = {{name: sha256(body).hexdigest() for name, body in assets.items()}}
        self.handler=mount_surrounding
'''
    source.write_text(text)
    mount = SimpleNamespace(mount=lambda: 'copied')
    copy, receipt = copied_runtime(source, tmp_path/'private/runtime.py', mount,
                                   expected_sha256=sha256(source.read_bytes()).hexdigest())
    assert copy.Runtime.__init__.__globals__['mount_surrounding'] is mount.mount
    instance = copy.Runtime()
    assert instance.handler() == 'copied'
    assert instance.fact_recording_asset_receipt['enabled'] is True
    assert receipt['mount_global'] == 'mount_surrounding'
    assert source.read_text() == text and not receipt['shared_files_modified']
    with pytest.raises(ValueError, match='pin changed'):
        copied_runtime(source, tmp_path/'private/other.py', mount, expected_sha256='wrong')


def test_disabled_factory_is_the_original_bound_factory_and_never_installs():
    class Task:
        def make_env(self, video=None):
            raise AssertionError('Not called')
    task = Task()
    assert recording_env_factory(task, SimpleNamespace(enabled=False)) == task.make_env


def test_provider_is_installed_before_inherited_setup_and_capture_and_closed_before_browser():
    events = []

    class Start:
        def setup(self, page):
            events.append(('native_setup', page))
            return 'original-goal'

    class Provider:
        enabled = True
        def install(self):events.append(('install', self.page))
        def close(self):events.append(('detach', self.page))

    env = SimpleNamespace(task_entrypoint=Start, close=lambda: events.append(('browser_close', None)))
    task = SimpleNamespace(make_env=lambda video: env)
    provider = Provider()
    made = recording_env_factory(task, provider)()
    assert made is env and env.task_entrypoint is not Start
    assert env.task_entrypoint().setup('page') == 'original-goal'
    assert events == [('install', 'page'), ('native_setup', 'page')]
    env.close()
    assert events[-2:] == [('detach', 'page'), ('browser_close', None)]
    assert Start.setup.__name__ == 'setup'


def test_invalid_native_factory_is_closed_before_rejection():
    events=[]
    env=SimpleNamespace(task_entrypoint=lambda: None, close=lambda: events.append('closed'))
    with pytest.raises(ValueError, match='native task class'):
        recording_env_factory(SimpleNamespace(make_env=lambda video: env),
                              SimpleNamespace(enabled=True))()
    assert events==['closed']


def test_browser_closes_even_when_provider_detach_fails():
    events=[]
    class Provider:
        enabled=True
        def close(self):raise RuntimeError('detach failed')
    class Start:pass
    env=SimpleNamespace(task_entrypoint=Start, close=lambda: events.append('browser closed'))
    recording_env_factory(SimpleNamespace(make_env=lambda video: env), Provider())()
    with pytest.raises(RuntimeError, match='detach failed'):env.close()
    assert events==['browser closed']


def test_copied_consumer_binds_native_provider_and_pins_without_changing_external_grading(tmp_path):
    from training.browser_training.fact_recording_installation import copied_execution
    import training.browser_training.fact_recording_installation as helper
    source=tmp_path/'execution.py'
    source.write_text('''from types import SimpleNamespace
TERMINAL_INSTRUCTION='same terminal'
class Episode:
    def __init__(self):
        from .runtime import Runtime
        self.runtime=Runtime()
        self.site_discovery=None
        self.task=SimpleNamespace(files={})
        if True:
            self.task.site_discovery_callback = self.site_discovery

def run(episode, runner, runner_options):
    protected={'automatic_grading', 'allow_ungraded', 'ungraded_reason', 'agent_runtime', 'agent_actor'}
    if set(runner_options) & protected:raise ValueError('protected')
    backend='backend';bound_metadata={};contract='external_grading'
    return runner(episode.task.make_env, backend, bound_metadata,
        observation_pipeline='native', terminal_response_instruction=TERMINAL_INSTRUCTION,
        automatic_grading=contract, **runner_options)
''')
    runtime=tmp_path/'runtime-copy.py';runtime.write_text('# pinned runtime')
    calls=[]
    provider=SimpleNamespace(enabled=True, observe=lambda op: op())
    module,receipt=copied_execution(source,tmp_path/'private/execution.py',
        SimpleNamespace(__file__=str(runtime),Runtime=lambda:'private runtime'),provider,
        expected_sha256=sha256(source.read_bytes()).hexdigest(),
        trusted_files={str(runtime):sha256(runtime.read_bytes()).hexdigest(),
                       str(Path(helper.__file__).resolve()):sha256(Path(helper.__file__).read_bytes()).hexdigest()})
    episode=module.Episode();episode.task.make_env=lambda video: None
    assert episode.runtime=='private runtime'
    assert episode.task.files==receipt['source_files']
    def runner(env_factory,backend,metadata,**options):
        calls.append(options)
    module.run(episode,runner,{})
    assert calls[0]['observation_pipeline'] is None
    assert calls[0]['fact_source_provider'] is provider
    assert calls[0]['fact_capture_observer']==provider.observe
    assert calls[0]['record_fact_provenance'] is True
    assert calls[0]['automatic_grading']=='external_grading'
    for key in ('record_fact_provenance','fact_source_provider','fact_capture_observer','allow_ungraded'):
        with pytest.raises(ValueError,match='protected'):module.run(episode,runner,{key:None})
    assert len(calls)==1
    # All task pins are rechecked at construction, before any runner call.
    source.write_text(source.read_text()+'# drift')
    with pytest.raises(ValueError,match='changed'):module.Episode()


def test_runtime_imports_cannot_escape_frozen_root(tmp_path):
    source=tmp_path/'frozen/environments/website_world/runtime.py'
    source.parent.mkdir(parents=True)
    source.write_text('''from hashlib import sha256
ROOT='/some/other/tree'
class Runtime:
    def __init__(self):
        assets={}
        self.asset_hashes = {name: sha256(body).hexdigest() for name, body in assets.items()}
''')
    with pytest.raises(ValueError,match='escaped'):
        copied_runtime(source,tmp_path/'private/runtime.py',SimpleNamespace(mount=lambda:None),
                       expected_sha256=sha256(source.read_bytes()).hexdigest())


def test_changed_consumer_pin_rejects_before_creating_private_file(tmp_path):
    from training.browser_training.fact_recording_installation import copied_execution
    source=tmp_path/'execution.py';source.write_text('not an approved consumer')
    output=tmp_path/'private/execution.py'
    with pytest.raises(ValueError,match='pin changed'):
        copied_execution(source,output,None,SimpleNamespace(enabled=True),
                         expected_sha256='wrong',trusted_files={})
    assert not output.exists()


def test_both_cleanup_failures_are_retained_in_runner_persisted_error_text():
    events=[]
    class Provider:
        enabled=True
        def close(self):
            events.append('detach attempted')
            raise RuntimeError('detach failed')
    class Start:pass
    def close():
        events.append('browser close attempted')
        raise ValueError('browser failed')
    env=SimpleNamespace(task_entrypoint=Start,close=close)
    recording_env_factory(SimpleNamespace(make_env=lambda video:env),Provider())()
    with pytest.raises(RuntimeError) as failure:env.close()
    assert 'detach failed' in str(failure.value) and 'browser failed' in str(failure.value)
    assert events==['detach attempted','browser close attempted']
