"""Named retailer avoidance in requests and durable memories, with explicit override."""
from copy import deepcopy
from .generator import stream
from .world import fingerprint


def resolve(memories,explicit):
    states={}
    for source in (memories,explicit):
        for row in source:
            if not isinstance(row.get('retailer_id'),str) or not row['retailer_id'] or type(row.get('avoid')) is not bool:
                raise ValueError('Invalid retailer preference')
            states[row['retailer_id']]=row['avoid']
    return sorted(sid for sid,avoid in states.items() if avoid)


def extend(bundle,recipe='none',retailer_ids=None):
    if recipe not in ('none','auto','avoid','request','memory','override'):raise ValueError('Unknown retailer preference recipe')
    if recipe=='auto':recipe=stream(bundle['seed'],'retailer-preference-mode').choice(('none','none','memory','request'))
    if recipe=='none':return bundle
    ids=retailer_ids if retailer_ids is not None else [f'store-{i+1:03d}' for i in range(6)]
    if not isinstance(ids,list) or not ids or any(not isinstance(s,str) or not s for s in ids) or len(ids)!=len(set(ids)):
        raise ValueError('Planned retailer IDs required')
    sid=stream(bundle['seed'],'retailer-preference-target').choice(sorted(ids));name='[[retailer:'+sid+']]'
    mode=bundle['settings']['resolved_memory_mode']
    remembered=recipe in ('memory','override') or recipe=='avoid' and mode!='none'
    explicit=[];memories=[]
    text=stream(bundle['prose_seed'],'retailer-preference-prose').choice((
        f'Please avoid {name}; I had a bad experience with them.',
        f"I don't want to buy from {name} again after my last order.",
        f'Leave {name} out of my shopping searches. Their handling of my last order put me off.'))
    if remembered:
        channel=mode if mode in ('profile','episodic') else stream(bundle['seed'],'retailer-memory-channel').choice(('profile','episodic'))
        fact={'id':'retailer-memory-1','retailer_id':sid,'avoid':True,'scope':'future shopping','channel':channel}
        memories=[fact]
        if channel=='profile':bundle['public']['memories']['profile'].append({**deepcopy(fact),'retailer_name':name,'text':text})
        else:bundle['public']['memories']['episodes'].append({'id':fact['id'],'text':f'Previous shopping conversation: "{text} Remember this for future purchases."'})
    else:explicit=[{'retailer_id':sid,'avoid':True}]
    if recipe=='override':
        explicit=[{'retailer_id':sid,'avoid':False}];text=f"For this search, it's okay to include {name}, despite my earlier preference."
    if explicit:
        bundle['public']['user_message']+=' '+text
        bundle['authoring']['message_segments'].append({'stage':'requirement','text':' '+text,'sources':['retailer_preferences']})
    bundle['retailer_memory_facts']=memories
    bundle['request']['explicit_retailer_preferences']=deepcopy(explicit)
    excluded=resolve(memories,explicit)
    for key in ('initial_accessible_task','resolved_task'):bundle[key]['excluded_retailer_ids']=excluded.copy()
    bundle['settings']['retailer_preferences']=recipe
    bundle['semantic_sha256']=fingerprint(bundle)
    return bundle


def bind_names(bundle,retailers):
    """Presentation-only binding after store identities exist; no outcome inputs."""
    names={'[[retailer:'+s['retailer_id']+']]':s['name'] for s in retailers}
    def bind(value):
        if isinstance(value,str):
            for token,name in names.items():value=value.replace(token,name)
            if '[[retailer:' in value:raise ValueError('Unbound retailer preference')
            return value
        if isinstance(value,list):return [bind(v) for v in value]
        if isinstance(value,dict):return {k:bind(v) for k,v in value.items()}
        return value
    bundle['public']=bind(bundle['public']);bundle['authoring']['message_segments']=bind(bundle['authoring']['message_segments'])
    return bundle
