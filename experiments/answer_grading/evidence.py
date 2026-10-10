"""Trusted state checks. No final-answer claims enter this module."""
from copy import deepcopy

VERSION = 'shopping-state-evidence-v1'


def contract_for(scenario):
    """Capabilities are world configuration, never inferred from missing files."""
    return {'schema_version':VERSION, 'accounts':scenario.get('accounts') is not None,
            'orders':True, 'commerce_mutations':True, 'memory':False}


def research_effects(initial, final, *, contract=None):
    """Validate coverage first, then preserve all effects, including reversals.

    Legacy v1 explicitly denotes research-only; v2 requires account evidence.
    With a scenario contract, that legacy declaration must also match the world.
    """
    schemas={'connected-shopping-journal-v1':False,'connected-shopping-journal-v2':True}
    if initial.get('schema_version')!=final.get('schema_version'):
        raise ValueError('Journal capability/schema changed during episode')
    version=initial.get('schema_version')
    if version not in schemas:raise ValueError('Unsupported/missing host journal')
    accounts=schemas[version]
    if contract is not None:
        if contract.get('schema_version')!=VERSION or type(contract.get('accounts')) is not bool:
            raise ValueError('Invalid state evidence contract')
        if contract['accounts']!=accounts:raise ValueError('Account coverage differs from configured world')
    for journal in (initial,final):
        for field in ('orders','commerce_mutations'):
            if not isinstance(journal.get(field),list):raise ValueError('Missing trusted effects coverage: '+field)
        if accounts and not isinstance(journal.get('accounts'),dict):raise ValueError('Missing journal state: accounts')
        if not accounts and 'accounts' in journal:raise ValueError('Research-only journal unexpectedly contains accounts')
        if journal.get('evidence_contract') is not None:
            expected=contract or {'schema_version':VERSION,'accounts':accounts,'orders':True,'commerce_mutations':True,'memory':False}
            if journal['evidence_contract']!=expected:raise ValueError('Declared journal evidence coverage differs')
    before,after=initial['commerce_mutations'],final['commerce_mutations']
    if after[:len(before)]!=before:raise ValueError('Mutation ledger lost its initial prefix')
    effects=deepcopy(after[len(before):])
    for field in ('orders','accounts') if accounts else ('orders',):
        if initial[field]!=final[field]:effects.append({'event':'host_state_changed','field':field})
    return effects


def evaluate_state_requirements(requirements, evidence):
    """Reusable exact-state/no-change predicates over explicitly covered channels.

    Requirements come from trusted task configuration. Each channel contains
    initial/final snapshots and complete mutation history. Missing coverage is
    unknown, never success. This supports adapters supplying memory state; it
    does not claim the current browser runtime implements memory writes.
    """
    checks={};details={}
    for req in requirements:
        if (not isinstance(req,dict) or set(req)-{'id','kind','channel','path','expected'}
                or not {'id','kind','channel'}<=set(req)):
            raise ValueError('Unsupported state requirement')
        key=req['id'];kind=req['kind'];channel=req['channel']
        if not isinstance(channel,str) or not channel:raise ValueError('Invalid state channel')
        if not isinstance(key,str) or not key or key in checks:raise ValueError('Invalid/duplicate state requirement ID')
        if kind not in ('final_equals','unchanged'):raise ValueError('Unsupported state predicate')
        path=req.get('path',[])
        if not isinstance(path,list) or any(not isinstance(x,str) for x in path):raise ValueError('Invalid state path')
        if kind=='unchanged' and path:raise ValueError('Unchanged currently requires the complete channel, not a partial path')
        if kind=='final_equals' and 'expected' not in req:raise ValueError('Missing expected state')
        observed=evidence.get(channel);actual=None;known=False
        if isinstance(observed,dict) and observed.get('coverage')=='complete':
            if kind=='final_equals':
                node=observed.get('final');known='final' in observed
                for part in path:
                    if not isinstance(node,dict) or part not in node:known=False;break
                    node=node[part]
                actual=node if known else None
                result=(type(actual) is type(req['expected']) and actual==req['expected']) if known else None
            else:
                known=all(x in observed for x in ('initial','final','events')) and isinstance(observed.get('events'),list)
                if path:raise ValueError('Unchanged currently requires the complete channel, not a partial path')
                result=(observed['initial']==observed['final'] and not observed['events']) if known else None
                actual={'final':observed.get('final'),'events':observed.get('events')}
        else:result=None
        checks[key]=result
        details[key]={'source':'privileged_state','channel':channel,'coverage':'complete' if known else 'unknown',
                      'expected':req.get('expected','No changes, including reversed changes'), 'supplied':deepcopy(actual)}
    return checks,details
