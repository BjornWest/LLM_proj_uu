"""One scenario episode over a saved generated world.

`GeneratedEpisode` builds a plain `Runtime` from a world directory; this builds
a `ScenarioRuntime` from the same files and wires the session capture into the
task lifecycle. The public request comes from the caller (Product's prepared
instance), not from the world's own task.
"""
from hashlib import sha256
import json
from pathlib import Path

from intent_browser.connected_world_task import ConnectedWorldTask, public_projection
from environments.website_world import generation
from environments.website_world.adapter import ROOT
from .capture import SessionCapture
from .runtime import ScenarioRuntime

VERSION = 'website-commerce-scenario-episode-v1'
STARTS = ('retailer', 'world')


def kit_sources():
    """Pins of every source file of this package, for a grading source binding."""
    here = Path(__file__).resolve().parent
    return {str(path): sha256(path.read_bytes()).hexdigest()
            for path in sorted(here.rglob('*')) if path.suffix in ('.py', '.js', '.css')}


def runtime_arguments(world, *, lazy_publication=None):
    """Checked manifest plus the Runtime arguments `GeneratedEpisode` uses for a saved world."""
    output = Path(world).resolve()
    manifest = generation.load(output)

    def read(name):
        return json.loads((output/name).read_text()) if (output/name).exists() else None

    episode = read('episode.json')
    if lazy_publication is None:
        policy = manifest.get('execution_policy') or {}
        lazy_publication = bool((policy.get('runtime_options') or {}).get('lazy_publication', False))
    arguments = dict(
        presentation=read('presentation.json'), surrounding=read('surrounding.private.json'),
        basket_plan=read('basket-plan.private.json'), checkout_domain=read('checkout-domain.private.json'),
        delivery_plan=read('delivery-plan.private.json'),
        discovery_mode='tool' if episode['start']['kind'] == 'tool_discovery' else 'index',
        readable_origins=episode.get('readable_origins', False), lazy_publication=lazy_publication)
    return output, manifest, arguments


class ScenarioEpisode:
    def __init__(self, world, settings, *, task, bind_episode, assets=None,
                 lazy_publication=None, source_files=None, headless=True, origin_diagnostics_path=None):
        """`task` is `{task_id, user_message, memories, start}` with start 'retailer' or 'world'.

        `bind_episode(episode_id) -> binding` is called in the task's `prepare`
        with the trace's episode id; its result becomes the journal's `binding`.
        """
        if (type(task) is not dict or set(task) != {'task_id', 'user_message', 'memories', 'start'}
                or task['start'] not in STARTS):
            raise ValueError('Give the public task id, request, memories and start')
        if not callable(bind_episode):
            raise ValueError('Supply the bind_episode(episode_id) callback')
        self.output, self.manifest, arguments = runtime_arguments(world, lazy_publication=lazy_publication)
        if origin_diagnostics_path is not None and not arguments['readable_origins']:
            raise ValueError('Origin phase diagnostics require readable logical origins')
        self.runtime = ScenarioRuntime(self.output/'pin', scenario=settings, scenario_assets=assets,
                                       origin_diagnostics_path=origin_diagnostics_path, **arguments)
        try:
            runtime = self.runtime
            if runtime.session is None:
                raise ValueError('A scenario episode needs scenario settings')
            expected = json.loads((self.output/'compositions.private.json').read_text())
            if expected != runtime.compositions:
                raise ValueError('Runtime composition differs from sampled plans')
            self.retailer_id = runtime.scenario['retailer_id']
            if task['start'] == 'retailer':
                start_url = runtime.origins[self.retailer_id] + '/'
            else:
                start_url = (runtime.research_origin if runtime.discovery_mode == 'tool' else runtime.index_origin) + '/'
            self.public = public_projection({
                'schema_version': 'connected-world-manual-v1', 'task_id': task['task_id'],
                'user_message': task['user_message'], 'memories': task['memories'],
                'environment_context': {'currency': 'SEK', 'scenario_date': runtime.world['quote_as_of'],
                                        'shopping_scope': 'All retailers in this generated world'},
                'start_url': start_url})
            from intent_browser.standard_profile import standard_profile
            self.profile = standard_profile(navigation_origins=runtime.navigation_origins, helpers=False)
            self.site_discovery = None
            if runtime.discovery_mode == 'tool':
                from intent_browser.harness import with_site_discovery
                self.profile = with_site_discovery(self.profile)
                self.site_discovery = runtime.site_discovery.search
            files = {str(self.output/name): pin for name, pin in self.manifest['files'].items()}
            files.update({str(ROOT/name): pin for name, pin in self.manifest['source_sha256'].items()})
            files.update(kit_sources())
            files.update(source_files or {})
            self.capture = capture = SessionCapture(runtime)

            class ScenarioTask(ConnectedWorldTask):
                supports_observation_pipeline = 'native_full_only'

                def make_env(self, video=None):
                    env = super().make_env(video)
                    if runtime.origin_map is not None:
                        from browsergym.core.task import OpenEndedTask

                        class LocalWorldStart(OpenEndedTask):
                            def setup(self, page):
                                runtime.attach_browser(page.context)
                                return super().setup(page)
                        env.unwrapped.task_entrypoint = LocalWorldStart
                    return env

                def prepare(self, trace):
                    result = super().prepare(trace)
                    capture.bind(trace, bind_episode(trace.episode_id))
                    if runtime.origin_map is not None:
                        from intent_browser.trace import write_json
                        name = 'site-origins.private.json'
                        write_json(trace.directory/'manual-review-private'/name, runtime.origin_map.descriptor)
                        result['logical_origins_private_artifact'] = 'manual-review-private/' + name
                    return {**result, 'commerce_scenario': {'schema': VERSION, 'retailer_id': runtime.scenario['retailer_id']}}

                def capture_initial(self, env, observation, info):
                    initial = super().capture_initial(env, observation, info)
                    return {**initial, 'commerce_session_before': capture.before(env, self.trace)}

                def evaluate(self, env, trace, outcome):
                    capture.after(env, trace, outcome)
                    return super().evaluate(env, trace, outcome)

            self.task = ScenarioTask(self.public, origins=runtime.navigation_origins, files=files,
                                     headless=headless, profile_name=self.profile.name)
        except BaseException:
            self.runtime.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.runtime.close()
