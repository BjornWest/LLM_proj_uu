"""Synthetic, zero-provider browser fixtures for pool lifecycle qualification."""
import json
from browsergym.core.env import BrowserEnv
from browsergym.core.task import AbstractBrowserTask


class IsolatedPageTask(AbstractBrowserTask):
    def __init__(self,seed,color):
        super().__init__(seed)
        self.color=color;self.slow_mo=0

    def setup(self,page):
        def respond(route):
            if route.request.url.endswith('/download'):
                route.fulfill(status=200,headers={'Content-Disposition':'attachment; filename=test.txt'},body='test')
            else:
                route.fulfill(status=200,content_type='text/html',body=f'''<!doctype html>
<html><head><title>{self.color}</title></head><body><main><h1>{self.color}</h1>
<button id="buy" onclick="localStorage.setItem('basket','{self.color}'); document.cookie='cart={self.color}'; this.textContent='Added {self.color}'">Add {self.color}</button>
<a id="popup" href="http://shared.test/popup" target="_blank">Details</a>
<a id="download" href="http://shared.test/download">Download</a></main></body></html>''')
        page.context.route('http://shared.test/**',respond)
        page.goto('http://shared.test/')
        return 'Select '+self.color, {'synthetic':True}

    def validate(self,page,chat_messages):return 0,False,'',{}


def factory(color):
    return lambda video=None: BrowserEnv(task_entrypoint=IsolatedPageTask,
        task_kwargs={'color':color},headless=True,pre_observation_delay=0,
        record_video_dir=video,pw_context_kwargs={'accept_downloads':False,'service_workers':'block'})


def worker(descriptor,color,pipe,shared=True):
    from intent_browser.chromium_pool import PoolClient
    client=PoolClient.from_file(descriptor) if shared else None
    episode=client.episode(color) if shared else None
    env=episode.wrap(factory(color))() if shared else factory(color)()
    try:
        from intent_browser.chat_ui import repo_chat_ui
        with repo_chat_ui(env):obs,_=env.reset(seed=1)
        pipe.send({'ready':True,'title':env.page.title(),'metadata':episode.metadata() if episode else None})
        while True:
            operation=pipe.recv()
            if operation=='inspect':
                pipe.send({'title':env.page.title(),'basket':env.page.evaluate("localStorage.getItem('basket')"),
                    'cookies':env.context.cookies()})
            elif operation=='act':
                env.page.locator('#buy').click()
                pipe.send({'basket':env.page.evaluate("localStorage.getItem('basket')")})
            elif operation=='reset':
                with repo_chat_ui(env):env.reset(seed=2)
                pipe.send({'basket':env.page.evaluate("localStorage.getItem('basket')"),
                           'cookies':env.context.cookies(),'metadata':episode.metadata() if episode else None})
            elif operation=='close':break
            else:raise ValueError(operation)
    finally:
        env.close()
        if episode:episode.close()
        pipe.close()


def graded_worker(descriptor,case,directory,pipe):
    """Correct/wrong/missing synthetic policy outputs through the actual runner."""
    from pathlib import Path
    import hashlib
    from intent_browser.chromium_pool import PoolClient
    from intent_browser.backend import Completion
    from intent_browser.runner import run_episode
    from intent_browser.automatic_grading import AutomaticGrading,file_hash
    from intent_browser.evaluation import Evaluation
    from intent_browser.trace import write_json
    root=Path(directory);root.mkdir()
    reference=root/'reference.json';reference.write_text('{"color":"red"}')
    episode=PoolClient.from_file(descriptor).episode('grading-'+case)
    env_holder=[]
    def env_factory(video):
        env=episode.wrap(factory('red'))(video);env_holder.append(env);return env
    class Policy:
        calls=0
        def complete(self,messages):
            self.calls+=1
            if self.calls==1 and case!='wrong':
                bid=env_holder[0].page.locator('#buy').get_attribute('bid')
                return Completion(f'click({bid!r})',{'scripted':True})
            return Completion("send_msg_to_user('Done')",{'scripted':True})
    class EpisodeTask:
        def prepare(self,trace):return {'synthetic':True}
        def capture_initial(self,env,observation,info):return {}
        def evaluate(self,env,trace,outcome):
            write_json(trace.directory/'native-state.json',{
                'basket':env.page.evaluate("localStorage.getItem('basket')"),
                'answered':any(x['role']=='assistant'and x['message']=='Done'for x in env.chat.messages)})
            return Evaluation('synthetic-browser-phase','1',trust='manual')
    def bind(env,trace,obs):
        import intent_browser.automatic_grading as automatic
        import agent_trace.adapters.browsergym as viewer
        return {'task_id':'pool-'+case,'goal_sha256':hashlib.sha256(obs['goal'].encode()).hexdigest(),
            'reference_files':{str(reference):file_hash(reference)},
            'source_files':{str(Path(p).resolve()):file_hash(p) for p in
                (__file__,automatic.__file__,viewer.__file__)}}
    def grade(env,trace,outcome):
        state=json.loads((trace.directory/'native-state.json').read_text())
        assert env.context is None
        return {'state':state,'closed':True,'technical_error':outcome.get('error')}
    def project(raw,binding):
        state=raw['state']
        return Evaluation('pool-synthetic-native','1',trust='native_state',
            task_completed=None if not state['answered']else state['basket']=='red',authorization_satisfied=True,
            technical_error=raw['technical_error'],limitations=['Synthetic state only; no real-task acceptance'])
    try:
        trace,summary=run_episode(env_factory,Policy(),{'model':'scripted','tags':['scripted','pool-qualification']},
            output=root/'runs',max_steps=1 if case=='missing'else 2,trace_screenshots=False,
            episode_task=EpisodeTask(),automatic_grading=AutomaticGrading('pool-fixture-v1',bind,grade,project),
            observation_pipeline='native')
        pipe.send({'trace':str(trace),'summary':summary})
    finally:episode.close();pipe.close()
