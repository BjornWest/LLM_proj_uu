"""Opt-in public memory adapter boundary; no preference inference or grading."""
from copy import deepcopy
import json
from jsonschema import Draft202012Validator
from .trace import write_json

VERSION='user-memory-v1'
TOOLS=('memory_read','memory_update','memory_delete')

class MemoryRejected(ValueError):
    """Adapter guarantees rejection occurred before any mutation."""


def bounded(value, limit=32768):
    text=json.dumps(value,ensure_ascii=False,allow_nan=False)
    if len(text.encode())>limit:raise ValueError('Memory JSON exceeds size bound')
    return deepcopy(value)


def description(adapter):
    for name in ('describe','snapshot','update','delete'):
        if not callable(getattr(adapter,name,None)):raise ValueError('Missing memory adapter method: '+name)
    data=bounded(adapter.describe())
    if set(data)!={'schema_version','fields'} or data['schema_version']!=VERSION or not isinstance(data['fields'],dict):
        raise ValueError('Invalid public memory description')
    if not 1<=len(data['fields'])<=64:raise ValueError('Invalid memory field count')
    for key,schema in data['fields'].items():
        if not isinstance(key,str) or not 1<=len(key)<=128:raise ValueError('Invalid memory key')
        # Keep v1 local/scalar. No references, arbitrary executable validators,
        # task-specific expected values, or implicit coercion/default insertion.
        if not isinstance(schema,dict) or set(schema)-{'type','enum','description','minimum','maximum','maxLength'}:
            raise ValueError('Unsupported memory field schema')
        if schema.get('type') not in ('string','number','integer','boolean'):raise ValueError('Memory v1 uses scalar fields')
        Draft202012Validator.check_schema(schema)
    return data


def snapshot(adapter, desc):
    data=bounded(adapter.snapshot())
    if (set(data)!={'revision','values'} or not isinstance(data['revision'],str)
            or not 1<=len(data['revision'])<=128 or not isinstance(data['values'],dict)
            or set(data['values'])-set(desc['fields'])):raise ValueError('Invalid memory snapshot')
    for key,value in data['values'].items():Draft202012Validator(desc['fields'][key]).validate(value)
    return data


class MemorySession:
    def __init__(self,adapter,trace):
        self.adapter,self.trace=adapter,trace
        self.description=description(adapter);self.initial=snapshot(adapter,self.description)
        self.events=[];self.uncertain=False
        write_json(trace.directory/'memory-initial.json',{'schema_version':VERSION,
                   'description':self.description,'snapshot':self.initial})

    def execute(self,name,args,index):
        artifact=f'memory-{index:03d}.json'
        if (self.trace.directory/artifact).exists():raise ValueError('Memory evidence already exists')
        row={'tool':name,'arguments':bounded(args),'before':None,'after':None,'applied':None,'error':None}
        self.events.append(row);write_json(self.trace.directory/artifact,row)
        dispatched=False
        try:
            before=snapshot(self.adapter,self.description);row['before']=before
            if name=='memory_read':after=before;row['applied']=False
            else:
                key=args['key']
                if key not in self.description['fields']:raise MemoryRejected('Unknown memory field')
                if args['expected_revision']!=before['revision']:raise MemoryRejected('Stale memory revision; read current memory before deciding again')
                if name=='memory_update':
                    try:Draft202012Validator(self.description['fields'][key]).validate(args['value'])
                    except Exception:raise MemoryRejected('Value does not match the public field schema') from None
                    bounded(args['value'])
                    dispatched=True;returned=self.adapter.update(key,args['value'],args['expected_revision'])
                elif name=='memory_delete':
                    dispatched=True;returned=self.adapter.delete(key,args['expected_revision'])
                else:raise ValueError('Unknown memory operation')
                after=snapshot(self.adapter,self.description)
                if returned!=after or after['revision']==before['revision']:raise RuntimeError('Memory adapter acknowledgment/state mismatch')
                expected=deepcopy(before['values'])
                if name=='memory_update':expected[key]=args['value']
                else:expected.pop(key,None)
                if after['values']!=expected:raise RuntimeError('Memory adapter changed unexpected fields')
                row['applied']=True
            row['after']=after
            result={'tool':name,'applied':row['applied'],'snapshot':after}
            if name=='memory_read':result['description']=self.description
            return result,artifact
        except MemoryRejected as exc:
            row['applied']=False;row['error']=str(exc)
            row['after']=snapshot(self.adapter,self.description)
            return {'tool':name,'applied':False,'error':str(exc),'snapshot':row['after']},artifact
        except BaseException as exc:
            self.uncertain=True;row['applied']=None;row['error']=f'{type(exc).__name__}: {exc}'
            row['dispatch_started']=dispatched
            # Never replay or infer no effect after an ambiguous persistence error.
            raise
        finally:write_json(self.trace.directory/artifact,row)

    def finish(self):
        final=snapshot(self.adapter,self.description)
        mutations=[deepcopy(e) for e in self.events if e['tool']!='memory_read' and e['applied'] is not False]
        evidence={'coverage':'unknown' if self.uncertain else 'complete','initial':self.initial['values'],
                  'final':final['values'],'events':mutations}
        write_json(self.trace.directory/'memory-final.json',{'schema_version':VERSION,'snapshot':final,'evidence':evidence})
        private=self.trace.directory/'manual-review-private';private.mkdir(exist_ok=True)
        path=private/'state-evidence.private.json'
        if path.exists():raise ValueError('Memory state evidence already exists')
        write_json(path,{'schema_version':'shopping-extra-state-v1','episode_id':self.trace.episode_id,'channels':{'memory':evidence}})
        return evidence
