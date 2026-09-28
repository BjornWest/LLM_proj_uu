"""Public AX change localization, with no site rules or inferred authorization.

Structural distance is not semantic irrelevance: an elsewhere cart total can
matter to a purchase. Summaries locate evidence for the model, not classify it
safe. Complete deltas stay in the trace; policy previews are bounded.
"""
from copy import deepcopy

SECTION_ROLES = frozenset(('article','region','form','dialog','alertdialog','row',
    'listitem','navigation','complementary','group','main'))


def scalar(value):
    if isinstance(value,dict):
        result=value.get('value')
        if result is None and value.get('relatedNodes'):
            return [n.get('text','') for n in value['relatedNodes']]
        return deepcopy(result)
    return deepcopy(value)


def identity(node):
    return (node.get('nodeId'),node.get('backendDOMNodeId'),node.get('frameId'))


def public(node):
    result={k:scalar(node[k]) for k in ('role','name','value','description') if k in node}
    result['bid']=node.get('browsergym_id')
    result['state']={p['name']:scalar(p.get('value')) for p in node.get('properties',[]) if 'name' in p}
    return result


def index(observation):
    nodes=observation.get('axtree_object',{}).get('nodes',[])
    by_id={n['nodeId']:n for n in nodes}
    parents={c:n['nodeId'] for n in nodes for c in n.get('childIds',[])}
    def ancestors(n):
        result=[];seen=set()
        while n['nodeId'] not in seen and len(seen)<128:
            seen.add(n['nodeId']);pid=parents.get(n['nodeId'],n.get('parentId'))
            n=by_id.get(pid)
            if n is None:break
            if not n.get('ignored') and scalar(n.get('role')) in SECTION_ROLES:
                result.append(n)
        return result
    rows={}
    for n in nodes:
        if n.get('ignored'):continue
        chain=ancestors(n)
        rows[identity(n)]={'node':n,'public':public(n),'chain':chain,
            'section':identity(chain[0]) if chain else None,
            'location':[{'role':scalar(a.get('role')),'name':scalar(a.get('name')),
                         'bid':a.get('browsergym_id')} for a in reversed(chain)]}
    return rows


def target_identity(observation,bid):
    matches=[n for n in observation.get('axtree_object',{}).get('nodes',[])
             if n.get('browsergym_id')==bid and not n.get('ignored')]
    if len(matches)!=1:return None
    n=matches[0];states=public(n)['state']
    if n.get('backendDOMNodeId') is None or states.get('disabled') is True:return None
    return (*identity(n),scalar(n.get('role')))


def change_report(before,after,decision):
    old,new=index(before),index(after)
    bid=decision.arguments.get('bid')
    targets=[r for r in old.values() if bid is not None and r['public']['bid']==bid]
    target=targets[0] if len(targets)==1 else None
    changes=[]
    for key in dict.fromkeys([*old,*new]):
        a,b=old.get(key),new.get(key)
        fields=[]
        if a is None:fields=['added']
        elif b is None:fields=['removed']
        else:
            fields=[k for k in set(a['public'])|set(b['public']) if a['public'].get(k)!=b['public'].get(k)]
            if a['location']!=b['location']:fields.append('location')
            # Preserve structural changes, but don't print raw CDP node IDs.
            if a['node'].get('childIds',[])!=b['node'].get('childIds',[]):fields.append('children')
        if not fields:continue
        r=b or a
        direct=bid is not None and any(v and v['public']['bid']==bid for v in (a,b))
        same=target is not None and any(v and v['section']==target['section'] and v['section'] is not None for v in (a,b))
        relation='target' if direct else 'same_section' if same else 'elsewhere' if target else 'page'
        changes.append({'relationship':relation,'changed_fields':sorted(fields),
            'before':None if a is None else {**a['public'],'location':a['location']},
            'after':None if b is None else {**b['public'],'location':b['location']},
            'decision_relevance':'direct_target' if direct else 'requires_agent_review'})
    priority={'target':0,'same_section':1,'elsewhere':2,'page':2}
    changes.sort(key=lambda c:priority[c['relationship']])
    return {'scope':'Public AX only. Location does not prove relevance or authorization; elsewhere totals may matter.',
            'target':None if target is None else {**target['public'],'location':target['location']},
            'change_count':len(changes),'changes':changes}


def preview(report,limit=6):
    """Keep policy evidence small; exact public delta is an external trace artifact."""
    def clip(value):
        if isinstance(value,str):return value[:200]+(' [truncated]' if len(value)>200 else '')
        if isinstance(value,list):return [clip(v) for v in value[:6]]
        if isinstance(value,dict):return {k:clip(v) for k,v in value.items()}
        return value
    return {**{k:clip(v) for k,v in report.items() if k!='changes'},
            'changes':[clip(c) for c in report['changes'][:limit]],
            'omitted_changes':max(0,report['change_count']-limit)}
