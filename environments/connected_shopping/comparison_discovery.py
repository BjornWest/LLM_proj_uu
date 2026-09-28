"""Seeded synthetic merchandising, never a task/stock/price ranking."""
import hashlib

LABELS={'trending':'Trending now','popular':'Popular products','new':'New on this site'}


def sample_discovery(seed=0):
    if type(seed) is not int:raise ValueError('Discovery seed must be an integer')
    n=int.from_bytes(hashlib.sha256(f'discovery-mode-v1:{seed}'.encode()).digest()[:8],'big')
    return {'mode':tuple(LABELS)[n%3],'seed':seed,'limit':12}


def validate(config):
    if config is None:return None
    if not isinstance(config,dict) or set(config)!={'mode','seed','limit'}:raise ValueError('Invalid discovery configuration')
    if config['mode'] not in LABELS or type(config['seed']) is not int or type(config['limit']) is not int or not 1<=config['limit']<=48:raise ValueError('Invalid discovery values')
    return dict(config)


def select(items,config):
    """Interleave categories; deterministic within each, independent of input order."""
    config=validate(config)
    if config is None:return []
    def rank(identity):return hashlib.sha256(f"discovery-items-v1:{config['seed']}:{config['mode']}:{identity}".encode()).digest()
    groups={family:sorted([x for x in items if x['category']==family],key=lambda x:rank(x['id'])) for family in sorted({x['category'] for x in items},key=rank)}
    result=[]
    while groups and len(result)<config['limit']:
        for family in list(groups):
            result.append(groups[family].pop(0))
            if not groups[family]:del groups[family]
            if len(result)==config['limit']:break
    return result
