"""Prospective trusted automatic grading; private to the host, never policy input."""
from dataclasses import dataclass
import hashlib
import importlib
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

from .evaluation import Evaluation
from .trace import write_json

VERSION='automatic-episode-grading-v1'
MANIFEST='automatic-grading.json'
GRADE='automatic-grade.json'
PROJECTION='automatic-grade-projection.json'


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,
        separators=(',',':'),allow_nan=False).encode()).hexdigest()


def file_hash(path):
    h=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def canonical_viewer_check(trace, evaluation):
    """Verify the actual shared read-only viewer adapter, not a new parser."""
    from agent_trace.adapters.browsergym import project
    group=project(trace.directory,ledger=False)
    found=[]
    for message in group['messages']:
        if message.get('title')=='Privileged verifier — not model input':
            found.append(json.loads(message['text']))
    if found != [evaluation]:raise ValueError('Automatic grade missing/different in shared viewer projection')
    return {'schema':'automatic-grade-projection-v1','episode_id':trace.episode_id,
        'evaluation_sha256':file_hash(trace.directory/'evaluation.json'),
        'adapter':'agent_trace.adapters.browsergym.project','verified':True}


@dataclass(frozen=True)
class AutomaticGrading:
    """Explicit automatic contract, not inferred from an evaluate hook.

    bind(env,trace,observation) -> task_id, goal_sha256, reference_files,
    source_files. grade(env,trace,outcome) -> raw native JSON or Evaluation.
    project(raw_grade,binding) -> canonical Evaluation. viewer_check verifies
    saved projection. External owners call finalize_external after their close.
    """
    contract_id: str
    bind: object
    grade: object
    project: object
    phase: str='after_close'
    viewer_check: object=canonical_viewer_check

    def validate(self):
        if not isinstance(self.contract_id,str) or not self.contract_id.strip():
            raise ValueError('Automatic grader requires a nonempty contract_id')
        if self.phase not in ('before_close','after_close','external'):
            raise ValueError('Unsupported automatic grading phase')
        for name in ('bind','grade','project','viewer_check'):
            if not callable(getattr(self,name)):raise ValueError('Missing automatic grader callable: '+name)
        if self.viewer_check is canonical_viewer_check:
            try:importlib.import_module('agent_trace.adapters.browsergym')
            except ImportError as exc:
                raise ValueError('Shared grade viewer unavailable; install common_agent_util before inference') from exc
        return self

    def describe(self):
        return {'contract_id':self.contract_id,'phase':self.phase,'callbacks':{
            name:{'module':getattr(getattr(self,name),'__module__',type(getattr(self,name)).__module__),
                'name':getattr(getattr(self,name),'__qualname__',type(getattr(self,name)).__qualname__)}
            for name in ('bind','grade','project','viewer_check')}}

    def callable_sources(self):
        paths=[]
        for name in ('bind','grade','project','viewer_check'):
            fn=getattr(self,name)
            try:path=inspect.getsourcefile(fn)
            except TypeError:path=inspect.getsourcefile(type(fn))
            if not path or not Path(path).is_file():raise ValueError('Unbound grading callable source: '+name)
            paths.append(str(Path(path).resolve()))
        if self.viewer_check is canonical_viewer_check:
            paths.append(str(Path(importlib.import_module('agent_trace.adapters.browsergym').__file__).resolve()))
        return set(paths)


def validate_options(contract,allow_ungraded,reason):
    if type(allow_ungraded) is not bool:raise ValueError('allow_ungraded must be boolean')
    if allow_ungraded:
        if contract is not None:raise ValueError('Choose automatic grading or explicit ungraded diagnostic')
        if not isinstance(reason,str) or not reason.strip():raise ValueError('Ungraded diagnostic requires a nonempty recorded reason')
    else:
        if reason is not None:raise ValueError('ungraded_reason requires allow_ungraded=True')
        if not isinstance(contract,AutomaticGrading):
            raise ValueError('Automatic grading required before episode dispatch; attach AutomaticGrading or explicitly set allow_ungraded=True with ungraded_reason')
        contract.validate()


def validate_binding(binding,contract,goal=None):
    binding=json.loads(json.dumps(binding,allow_nan=False))
    if not isinstance(binding,dict):raise ValueError("Automatic grading binding must be an object")
    if not isinstance(binding.get('task_id'),str) or not binding['task_id'].strip():raise ValueError('Missing automatic task binding')
    pin=binding.get('goal_sha256')
    if not isinstance(pin,str) or len(pin)!=64 or any(c not in '0123456789abcdef' for c in pin):raise ValueError('Missing displayed goal binding')
    if goal is not None and pin!=hashlib.sha256(goal.encode()).hexdigest():raise ValueError('Automatic grader goal binding differs')
    for kind in ('reference_files','source_files'):
        values=binding.get(kind)
        if not isinstance(values,dict) or not values:raise ValueError('Missing automatic grading '+kind)
        normalized={}
        for path,expected in values.items():
            path=Path(path).resolve(strict=True)
            if not path.is_file() or not isinstance(expected,str) or file_hash(path)!=expected:
                raise ValueError('Automatic grading file binding differs: '+str(path))
            normalized[str(path)]=expected
        binding[kind]=normalized
    if not contract.callable_sources()<=binding['source_files'].keys():raise ValueError('Automatic grading callbacks missing from source bindings')
    return binding


class GradingGate:
    def __init__(self,trace,contract=None,*,allow_ungraded=False,reason=None,auxiliary=None):
        self.trace,self.contract=trace,contract
        self.binding=None;self.stamps={}
        self.record={'schema':VERSION,'episode_id':trace.episode_id,
            'status':'auxiliary' if auxiliary else 'explicitly_ungraded' if allow_ungraded else 'awaiting_binding',
            'contract_id':contract.contract_id if contract else None,'phase':contract.phase if contract else None,
            'contract':contract.describe() if contract else None,
            'reason':reason,'auxiliary_parent':auxiliary,'binding':None,'binding_sha256':None,
            'grade_artifact':None,'projection_artifact':None,'infrastructure_complete':False}
        self.save()

    def save(self):
        write_json(self.trace.directory/MANIFEST,self.record)

    def bind(self,env,obs):
        if self.contract is None:return
        self.binding=validate_binding(self.contract.bind(env,self.trace,obs),self.contract,obs['goal'])
        self.record.update(binding=self.binding,binding_sha256=digest(self.binding),status='attached')
        self.check(force=True);self.save()

    def check(self,*,force=False):
        if self.contract is None:return
        if self.binding is None:raise ValueError('Automatic grading contract not bound before dispatch')
        for kind in ('reference_files','source_files'):
            for name,pin in self.binding[kind].items():
                path=Path(name);stat=path.stat();stamp=(stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
                if force or self.stamps.get(name)!=stamp:
                    if file_hash(path)!=pin:raise ValueError('Automatic grading binding changed: '+name)
                    self.stamps[name]=stamp

    def pending_external(self):
        self.record.update(status='pending_external',infrastructure_complete=False);self.save()

    def fail(self,error):
        self.record.update(status='failed',error=error,infrastructure_complete=False);self.save()

    def collect(self,env,outcome):
        """Run native grading once at its declared phase; preserve original result."""
        self.check(force=True)
        if hasattr(self.trace,'flush_observations'):self.trace.flush_observations()
        self.record.update(status='grading');self.save()
        native=self.contract.grade(env,self.trace,outcome)
        raw=native.to_dict() if isinstance(native,Evaluation) else native
        if not isinstance(raw,dict):raise ValueError('Automatic grader produced no native JSON artifact')
        path=self.trace.directory/GRADE
        with path.open('x',encoding='utf-8') as file:
            json.dump({'schema':VERSION,'episode_id':self.trace.episode_id,
                'contract_id':self.contract.contract_id,'binding_sha256':self.record['binding_sha256'],
                'raw_grade':raw},file,ensure_ascii=False,allow_nan=False,indent=2)
        self.record.update(grade_artifact=GRADE,grade_sha256=file_hash(path));self.save()
        if raw.get('task_id',self.binding['task_id'])!=self.binding['task_id']:
            raise ValueError('Native automatic grade task binding differs')
        self.native=native

    def publish(self,outcome):
        """Project only after cleanup; errors remain infrastructure errors."""
        self.check(force=True)
        value=self.contract.project(self.native,self.binding)
        if not isinstance(value,Evaluation):raise ValueError('Missing supported canonical Evaluation projection')
        for name in ('verifier','verifier_version','trust'):
            declaration=getattr(value,name)
            if not isinstance(declaration,str) or not declaration.strip():
                raise ValueError('Automatic grade requires a nonempty '+name+' declaration')
        trust=value.trust.strip().lower();verifier=value.verifier.strip().lower()
        if (trust in ('unknown','ungraded','none','explicitly_ungraded','auxiliary','pending_external')
                or trust.startswith('manual') or verifier in ('none','manual-review')):
            raise ValueError('Manual/ungraded projection is not an automatic grade')
        value=value.to_dict()
        if value['task_completed'] is None and not value['technical_error'] and not value['limitations']:
            raise ValueError('Automatic grade has neither verdict nor explicit inconclusive reason')
        if outcome.get('error'):
            value['technical_error']=outcome['error'];value['safe_success']=None
        write_json(self.trace.directory/'evaluation.json',value)
        evaluation_sha=file_hash(self.trace.directory/'evaluation.json')
        proof=self.contract.viewer_check(self.trace,value)
        if (not isinstance(proof,dict) or proof.get('schema')!='automatic-grade-projection-v1'
            or proof.get('episode_id')!=self.trace.episode_id or proof.get('verified') is not True
            or proof.get('evaluation_sha256')!=evaluation_sha
            or file_hash(self.trace.directory/'evaluation.json')!=evaluation_sha):
            raise ValueError('Missing or unbound automatic grade viewer projection')
        self.check(force=True)
        if file_hash(self.trace.directory/GRADE)!=self.record['grade_sha256']:
            raise ValueError('Automatic native grade changed during publication')
        write_json(self.trace.directory/PROJECTION,proof)
        self.record.update(status='graded',projection_artifact=PROJECTION,
            projection_sha256=file_hash(self.trace.directory/PROJECTION),
            infrastructure_complete=not bool(value['technical_error']))
        self.save();return value

    def finish(self,env,outcome):
        try:
            self.collect(env,outcome)
            return self.publish(outcome)
        except (Exception, KeyboardInterrupt) as exc:
            self.fail(f'{type(exc).__name__}: {exc}');raise


def failure_evaluation(error):
    return Evaluation('automatic-grading-failed',VERSION,trust='infrastructure_failure',technical_error=error).to_dict()


def finalize_external(directory,contract):
    """Finalize a declared external contract once, after the owner's native close.

    This cannot adopt a historical trace lacking the prospective declaration.
    Native callbacks must verify their own session-close and reference evidence.
    """
    contract.validate();directory=Path(directory).resolve()
    record=json.loads((directory/MANIFEST).read_text())
    if (record['schema']!=VERSION or record['episode_id']!=directory.name
        or record['status']!='pending_external' or contract.phase!='external'
        or record['contract_id']!=contract.contract_id or record.get('contract')!=contract.describe()):raise ValueError('No matching pending external automatic grader')
    # Durable once-only claim: concurrent finalizers may not both call a native grader.
    with (directory/'automatic-grading-finalization.lock').open('x',encoding='utf-8') as claim:
        json.dump({'episode_id':directory.name,'contract':contract.describe()},claim)
    summary=json.loads((directory/'episode.json').read_text())
    trace=SimpleNamespace(directory=directory,episode_id=directory.name)
    gate=object.__new__(GradingGate);gate.trace=trace;gate.contract=contract;gate.record=record;gate.stamps={}
    try:
        gate.binding=validate_binding(record['binding'],contract)
        if digest(gate.binding)!=record['binding_sha256']:raise ValueError('External automatic grading binding changed')
        if summary.get('trace_complete') is not True:raise ValueError('Cannot grade an incomplete browser trace')
        value=gate.finish(None,summary)
        summary.update(evaluation=value,grading=gate.record,grading_error=None,
            infrastructure_completed=gate.record['infrastructure_complete'],success=value['safe_success'],
            error=summary.get('error') or value['technical_error'])
    except (Exception, KeyboardInterrupt) as exc:
        error=f'Automatic grading failed: {type(exc).__name__}: {exc}'
        gate.fail(error)
        value=failure_evaluation(error)
        write_json(directory/'evaluation.json',value)
        summary.update(evaluation=value,grading=gate.record,grading_error=error,
            infrastructure_completed=False,success=None,error=summary.get('error') or error)
    write_json(directory/'episode.json',summary)
    return summary
