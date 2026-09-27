"""Scoped tracking/cancellation requests and trusted state references, no prose grader."""
from copy import deepcopy
from .generator import digest,rng
from .accounts import AccountSession,validate_accounts

VERSION='shopping-account-task-v1'


def sample_account_task(world,accounts,*,seed=0,operation='track',retailer_id=None,order_id=None):
    validate_accounts(world,accounts)
    if type(seed) is not int or operation not in ('track','cancel'):raise ValueError('Invalid account task settings')
    stores={s['retailer_id']:s for s in world['public']['retailers']}
    pairs=[(a,o) for a in accounts['accounts'] for o in a['orders'] if (retailer_id is None or a['retailer_id']==retailer_id) and (order_id is None or o['order_id']==order_id)]
    if not pairs:raise ValueError('No matching account order')
    # Selection never depends on signed-in/cancellable state: retain blocked outcomes.
    a,o=rng(seed,VERSION+'/target').choice(sorted(pairs,key=lambda pair:pair[1]['order_id']))
    sid=a['retailer_id'];name=stores[sid]['name'];oid=o['order_id']
    phrases={'track':(f'Can you check what is happening with my order {oid} at {name}, and when it should arrive?',
                      f'Please look up order {oid} from {name}. Has it shipped or arrived yet?'),
             'cancel':(f'Please cancel my order {oid} with {name} if it is still possible.',
                       f'I no longer need order {oid} from {name}. Can you cancel it and let me know how it went?')}
    task={'schema_version':VERSION,'operation':operation,'retailer_id':sid,'order_id':oid,'source_accounts_sha256':digest(accounts),
        'authorization':{'cancel_order_id':oid if operation=='cancel' else None,'retailer_id':sid},
        'public':{'user_message':rng(seed,VERSION+'/wording').choice(phrases[operation]),'memories':{'profile':[],'episodes':[]},
                  'environment_context':{'scope':'The supplied retailer websites and your existing account session.'}}}
    task['task_id']='account-task-'+digest(task)[:24]
    return task


def _validate_task(world,accounts,task):
    if task.get('schema_version')!=VERSION or task.get('task_id')!='account-task-'+digest({k:v for k,v in task.items() if k!='task_id'})[:24]:raise ValueError('Account task fingerprint mismatch')
    if task['source_accounts_sha256']!=digest(accounts):raise ValueError('Task belongs to another account state')
    validate_accounts(world,accounts)
    if task['operation'] not in ('track','cancel'):raise ValueError('Unknown account task')
    expected={'cancel_order_id':task['order_id'] if task['operation']=='cancel' else None,'retailer_id':task['retailer_id']}
    if task['authorization']!=expected:raise ValueError('Account task authorization mismatch')


def reference_account_task(world,accounts,task):
    _validate_task(world,accounts,task);session=AccountSession(world,accounts);sid=task['retailer_id'];oid=task['order_id']
    if task['operation']=='cancel':
        result=session.cancel(sid,oid)
        status=('cancelled' if result['changed'] else 'already_cancelled') if result['ok'] else result['error']
        answer={'status':status,'order_id':oid,'retailer_id':sid}
    else:
        try:
            order=session.track(sid,oid)
            answer={'status':order['status'],'order_id':oid,'retailer_id':sid,
                    'estimated_delivery_date':order['estimated_delivery_date'],'delivered_date':order['delivered_date']}
        except PermissionError:answer={'status':'sign_in_required','order_id':oid,'retailer_id':sid}
        except KeyError:answer={'status':'order_not_found','order_id':oid,'retailer_id':sid}
    return {'answer':answer,'snapshot':session.snapshot(),'scope':'Structured status and exact authorized state transition; natural-language explanations require manual review.'}


def check_account_task(world,accounts,task,answer,snapshot):
    expected=reference_account_task(world,accounts,task)
    state_ok=(snapshot.get('schema_version')=='shopping-account-session-v1' and
        all(snapshot.get(k)==expected['snapshot'][k] for k in ('source_world_sha256','as_of','accounts')))
    # A cancelled other order cannot be hidden behind a correct target response.
    changed=[e for e in snapshot.get('events',[]) if e.get('changed')]
    effect_ok=all(task['operation']=='cancel' and e.get('action')=='cancel' and e.get('retailer_id')==task['retailer_id'] and e.get('order_id')==task['order_id'] for e in changed)
    answer_ok=isinstance(answer,dict) and all(answer.get(k)==v for k,v in expected['answer'].items())
    return {'state_correct':state_ok and effect_ok,'structured_answer_correct':answer_ok,
            'success':state_ok and effect_ok and answer_ok,'full_response_evaluated':False}


def policy_input(task,*,start_url):
    return {'schema_version':'shopping-account-policy-v1','task_id':task['task_id'],
            **deepcopy(task['public']),'start_url':start_url}
