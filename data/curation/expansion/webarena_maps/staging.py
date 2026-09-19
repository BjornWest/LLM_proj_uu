"""Pure contract loading and fail-closed startup-evidence validation; no networking."""
import hashlib,json
from pathlib import Path
from urllib.parse import urlsplit
HERE=Path(__file__).parent
class NotReady(RuntimeError):pass

def contracts():return json.loads((HERE/'contracts.json').read_text())
def contract(task_id):return next(t for t in contracts()['tasks']if t['source_task_id']==task_id)
def policy_projection(task):
    goal=task['policy_input']['goal']
    if not isinstance(goal,str)or not goal.strip():raise ValueError('Explicit original goal required')
    if goal!=task['original_prompt']:raise ValueError('Original goal changed without derived revision')
    return {'goal':goal}

def preflight_status(task,receipt,root):
    """Validate only a supplied, evidence-bound site preflight; not task acceptance.

    Receipts must be produced by a future real site/browser preflight. This
    function does not manufacture them or trust a top-level ready flag.
    """
    root=Path(root).resolve();issues=[];top=contracts()
    if receipt.get('schema')!='webarena-maps-site-preflight-v1':issues.append('missing_versioned_preflight')
    if receipt.get('image')!=top['image']or receipt.get('dataset_sha256')!=top['source_sha256']:issues.append('source_pin_mismatch')
    origin=urlsplit(receipt.get('origin',''))
    if origin.scheme not in('http','https')or origin.hostname not in('localhost','127.0.0.1')or not origin.port or origin.path not in('','/')or origin.query or origin.fragment:issues.append('unverified_local_origin')
    if receipt.get('source_inspection_only')is not False or receipt.get('browser_preflight_executed')is not True:issues.append('actual_browser_preflight_missing')
    checks=receipt.get('checks',{})
    for name in task['required_preflight_gates']:
        check=checks.get(name,{})
        if check.get('passed')is not True:issues.append(name+':not_proven');continue
        refs=check.get('evidence',[])
        if not refs:issues.append(name+':no_evidence');continue
        for ref in refs:
            path=(root/ref.get('path','')).resolve()
            if not path.is_relative_to(root)or not path.is_file()or hashlib.sha256(path.read_bytes()).hexdigest()!=ref.get('sha256'):issues.append(name+':invalid_evidence')
    return {'site_preflight_sufficient':not issues,'issues':issues,'task_accepted':False,'training_eligible':False}

class MapsStagingTask:
    """EpisodeTask-shaped scaffold: captures raw evidence but supplies no verdict.

    Future runner integration must pin the runtime before importing BrowserGym.
    No browser factory, site startup or executable live CLI is provided here.
    """
    supported_harness_profiles=('core-tools-v3',)
    def __init__(self,task_id,receipt,root):self.contract=contract(task_id);self.receipt=receipt;self.root=Path(root)
    @property
    def policy_goal(self):return policy_projection(self.contract)['goal']
    def prepare(self,trace):
        status=preflight_status(self.contract,self.receipt,self.root)
        if not status['site_preflight_sufficient']:raise NotReady(json.dumps(status))
        self.trace=trace
        (trace.directory/'maps-staging-contract-private.json').write_text(json.dumps(self.contract,indent=2))
        return {'source':'webarena-verified','source_task_id':self.contract['source_task_id'],'source_revision':self.contract['source_revision'],'task_accepted':False,'training_eligible':False,'verifier_implemented':False}
    def capture_initial(self,env,observation,info):return {'url':env.unwrapped.page.url,'status':'staging_only','task_accepted':False}
    def evaluate(self,env,trace,outcome):
        from intent_browser.evaluation import Evaluation
        return Evaluation('webarena-maps-staging','unimplemented-v1',trust='unknown',task_completed=None,authorization_satisfied=None,limitations=['Source-only scaffold; no outcome verifier implemented.','Infrastructure failures must not become NOT_FOUND labels.','Native grade must be retained separately and cannot establish route or map rendering alone.'])
