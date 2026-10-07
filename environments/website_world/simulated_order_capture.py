"""Actual private ledger captures; missing whole-run authority stays null.

These callbacks belong to an accepted generated task lifecycle, not policy tools.
Source preparation only: this module does not certify its own capture provenance.
"""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

from intent_browser.connected_world_task import checked_files
from .adapter import digest
from .catalog_cart_execution import save_new
from .simulated_order_store import OrderStore

VERSION='website-simulated-order-capture-v1'


def prepared_task(base_task, capture, plan, runtime):
    """Use ordinary cart controls before the first policy observation.

    The ledger baseline/terminal callbacks are private task lifecycle hooks.
    Neither this wrapper nor the resulting dictionary establishes authority.
    """
    from . import short_task_setup as setup
    class OrderTask(type(base_task)):
        def make_env(self, video=None):
            env=super().make_env(video)
            entrypoint=env.unwrapped.task_entrypoint
            class OrderStart(entrypoint):
                def setup(self,page):
                    result=super().setup(page)
                    capture.prepared_setup=setup.apply(page,plan,runtime=runtime)
                    return result
            env.unwrapped.task_entrypoint=OrderStart
            return env
        def capture_initial(self,env,observation,info):
            initial=super().capture_initial(env,observation,info)
            private=self.trace.directory/'manual-review-private';private.mkdir(exist_ok=True)
            save_new(private/'order-prepared-setup.private.json',capture.prepared_setup)
            return {**initial,'actual_order_baseline':capture.before(env,self.trace)}
        def evaluate(self,env,trace,outcome):
            capture.after(env,trace,outcome)
            return super().evaluate(env,trace,outcome)
    return OrderTask(base_task.public,origins=base_task.policy_navigation_origins,
        files=base_task.files,attachments=base_task.attachments,
        headless=base_task.headless,profile_name=base_task.supported_harness_profiles[0])


class OrderCapture:
    def __init__(self,runtime,task,*,source_files):
        if type(runtime.orders) is not OrderStore or not source_files:
            raise ValueError('Capture the actual private runtime store with complete source pins')
        checked_files(source_files)
        self.runtime,self.task=runtime,deepcopy(task)
        self.store=runtime.orders
        self.source_files=deepcopy(source_files)
        self.capture_sha256=sha256(Path(__file__).read_bytes()).hexdigest()
        if self.source_files.get(str(Path(__file__).resolve()))!=self.capture_sha256:
            raise ValueError('Capture implementation is absent from the source union')
        self.trace=None;self.binding=None;self.artifacts={};self.outcome=None
        self.outcome_artifact=None;self.sealed=False

    def _check(self):
        checked_files(self.source_files)
        if self.runtime.orders is not self.store or type(self.store) is not OrderStore:
            raise ValueError('Runtime order store changed during capture')
        if self.binding is not None and self.trace.episode_id!=self.binding['episode_binding']['episode_id']:
            raise ValueError('Actual captured episode identity changed')

    def _snapshot(self,trace,name,phase):
        self._check()
        if name in self.artifacts:raise FileExistsError('Duplicate order capture phase')
        if self.trace is not trace:raise ValueError('Order capture trace identity changed')
        value={'phase':phase,'order_snapshot':self.store.snapshot()}
        private=trace.directory/'manual-review-private';private.mkdir(exist_ok=True)
        path=private/('orders-'+name+'.private.json');save_new(path,value)
        self.artifacts[name]={'path':str(path.resolve()),'sha256':sha256(path.read_bytes()).hexdigest()}
        return deepcopy(self.artifacts[name])

    def before(self,env,trace):
        if self.trace is not None:raise ValueError('Order baseline already captured')
        self.trace=trace
        episode_binding={'episode_id':trace.episode_id,'task_sha256':digest(self.task),
            'source_union_sha256':digest(self.source_files),'capture_implementation_sha256':self.capture_sha256}
        self.store.bind_episode(episode_binding)
        self.binding={'runtime_id':self.store.snapshot()['runtime_id'],'episode_binding':episode_binding}
        return self._snapshot(trace,'before','before_policy')

    def after(self,env,trace,outcome):
        if 'before' not in self.artifacts or self.outcome is not None:
            raise ValueError('Capture one order terminal phase after its baseline')
        result=self._snapshot(trace,'after','after_policy_before_context_close')
        self.outcome=deepcopy(outcome)
        path=trace.directory/'manual-review-private/orders-terminal-outcome.private.json'
        save_new(path,self.outcome)
        self.outcome_artifact={'path':str(path.resolve()),'sha256':sha256(path.read_bytes()).hexdigest()}
        return result

    def seal(self,returned_trace,summary):
        self._check()
        path=Path(returned_trace).resolve()
        if (self.sealed or self.trace is None or path!=self.trace.directory.resolve()
                or set(self.artifacts)!={'before','after'} or self.outcome is None):
            raise ValueError('Seal exactly one complete actual returned order capture')
        metadata=json.loads((path/'metadata.json').read_bytes())
        if metadata['episode_id']!=self.trace.episode_id:raise ValueError('Returned episode identity changed')
        terminal=Path(self.outcome_artifact['path'])
        if (not terminal.is_relative_to(path) or sha256(terminal.read_bytes()).hexdigest()!=self.outcome_artifact['sha256']
                or json.loads(terminal.read_bytes())!=self.outcome):
            raise ValueError('Actual terminal capture artifact changed')
        if any(self.outcome[k]!=summary[k] for k in ('stop_reason','terminated','truncated')):
            raise ValueError('Returned summary differs from live terminal capture')
        rows={}
        for name,record in self.artifacts.items():
            document=Path(record['path'])
            if not document.is_relative_to(path) or sha256(document.read_bytes()).hexdigest()!=record['sha256']:
                raise ValueError('Actual captured order artifact changed')
            rows[name]=json.loads(document.read_bytes())
        completed=(summary['stop_reason'] in ('agent_finished','terminated') and not summary.get('error')
            and not summary.get('execution_error') and not summary.get('cleanup_errors') and not summary.get('truncated'))
        # Runtime cleanup precedes this callback. Serialize sealing against any
        # remaining commit thread; changed terminal truth must never be omitted.
        self.store.seal(rows['after']['order_snapshot'])
        capsule={'schema_version':'website-simulated-order-capsule-v1','task_sha256':digest(self.task),
            'episode_id':metadata['episode_id'],'main_trace_sha256':sha256((path/'steps.jsonl').read_bytes()).hexdigest(),
            'before':rows['before'],'after':rows['after'],'effect_journal':None}
        save_new(path/'order-capsule.private.json',capsule)
        save_new(path/'order-capture-provenance.private.json',{'schema':VERSION,'binding':self.binding,
            'captures':self.artifacts,'terminal_capture':self.outcome_artifact,
            'source_files':self.source_files,'policy_completed':completed,
            'effect_authority':'unaccepted; complete journal remains null',
            'qualification':'Actual Runtime callbacks required; source tests do not certify origin or whole-run effects'})
        self.sealed=True
        return capsule,completed
