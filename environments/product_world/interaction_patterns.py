"""Opt-in retail interaction sampling; changes access paths, never business facts.

Destination postcodes are deterministic synthetic aliases of existing home geography,
not geocoding inputs or claimed real postal assignments. No network or task inputs.
"""
from copy import deepcopy
import re
from .config import _number,_weights
from .generator import digest,rng,weighted
from .stores import validate_store_world
from .locations import validate_locations
from .comparison_coverage import validate_coverage

VERSION='shopping-interaction-patterns-v1'
PROFILES={
    'direct':{'search_sections_probability':.15,'list_probability':.2,'offer_expand_probability':.2,
        'spec_expand_probability':.15,'shipping_separate_probability':.1,
        'destination_form_weights':{'none':.85,'single':.15,'split':0},'related_limits':(0,1,2,3)},
    'browse':{'search_sections_probability':.8,'list_probability':.2,'offer_expand_probability':.45,
        'spec_expand_probability':.45,'shipping_separate_probability':.3,
        'destination_form_weights':{'none':.5,'single':.3,'split':.2},'related_limits':(6,8,10,12)},
    'compact':{'search_sections_probability':.5,'list_probability':.75,'offer_expand_probability':.8,
        'spec_expand_probability':.85,'shipping_separate_probability':.7,
        'destination_form_weights':{'none':.2,'single':.4,'split':.4},'related_limits':(2,4,6)},
}
PROBABILITIES=tuple(k for k in PROFILES['direct'] if k.endswith('_probability'))
FIELDS={'site_id','kind','search_sections','result_presentation','offer_disclosure',
        'specification_disclosure','shipping_disclosure','destination_form','related_limit'}
TOP_FIELDS={'schema_version','source_world_sha256','source_locations_sha256',
            'source_comparison_coverage_sha256','destination','sites'}
FORMATS={'SE':(3,2),'FI':(5,),'NO':(4,),'DK':(4,),'IS':(3,),'BE':(4,),
         'LU':(4,),'FR':(5,),'DE':(5,),'AT':(4,),'CH':(4,),'ES':(5,),'PT':(4,3),'IT':(5,)}


def resolve_config(patch=None):
    if patch is None:patch={}
    allowed={'profile_weights','destination_form_weights','related_limits',*PROBABILITIES}
    if not isinstance(patch,dict) or set(patch)-allowed:raise ValueError('Unknown interaction pattern config')
    result={'profile_weights':_weights({'direct':.3,'browse':.4,'compact':.3},patch.get('profile_weights',{}),'interaction profiles')}
    for name in PROBABILITIES:
        if name in patch:
            _number(patch[name],name,probability=True);result[name]=patch[name]
    if 'destination_form_weights' in patch:
        result['destination_form_weights']=_weights(dict.fromkeys(('none','single','split'),0),patch['destination_form_weights'],'destination forms')
    if 'related_limits' in patch:
        values=patch['related_limits']
        if not isinstance(values,list) or not values or any(type(v) is not int or not 0<=v<=12 for v in values) or len(set(values))!=len(values):
            raise ValueError('related_limits must be distinct integers0..12')
        result['related_limits']=sorted(values)
    return result


def destination_alias(locations):
    if locations is None:return None
    home=locations['public']['user_location'];country=home['country']
    # Alias is stable across UI draws and stores for the same exact frozen home.
    r=rng(0,VERSION+'/destination/'+digest(home))
    def digits(n):return str(r.randint(10**(n-1),10**n-1))
    letters='ABCDEFGHJKLMNPRSTUVWXYZ'
    if country=='GB':parts=[r.choice(letters)+r.choice(letters)+digits(2),str(r.randrange(10))+r.choice(letters)+r.choice(letters)]
    elif country=='IE':parts=[r.choice(letters)+digits(2),''.join(r.choice(letters+'0123456789') for _ in range(4))]
    elif country=='NL':parts=[digits(4),r.choice(letters)+r.choice(letters)]
    elif country in FORMATS:parts=[digits(n) for n in FORMATS[country]]
    else:raise ValueError('Destination country lacks an authored postcode format')
    return {'location_id':home['location_id'],'country':country,
            'postcode':('-' if country=='PT' else ' ').join(parts),'postcode_parts':parts,'synthetic':True}


def _normalize(value):
    if not isinstance(value,str) or len(value)>32:return None
    compact=re.sub(r'[ \t-]','',value).upper()
    return compact if re.fullmatch(r'[A-Z0-9]+',compact) else None


def destination_matches(data,country,postcode=None,*,parts=None):
    """Match already-validated sidecar destination; never interpret other postcodes.

    Split inputs must match corresponding parts. Full inputs accept ordinary ASCII
    spaces/hyphens and letter case. Country remains explicit for international sites.
    """
    dest=data.get('destination')
    if dest is None or not isinstance(country,str) or country.strip().upper()!=dest['country']:return False
    if (postcode is None)==(parts is None):return False
    if parts is not None:
        return (isinstance(parts,(list,tuple)) and len(parts)==len(dest['postcode_parts'])
                and all(_normalize(a)==_normalize(b) for a,b in zip(parts,dest['postcode_parts'])))
    return _normalize(postcode)==_normalize(dest['postcode'])


def _registry(world,coverage):
    validate_store_world(world)
    stores={s['retailer_id']:'retailer' for s in world['public']['retailers']}
    if coverage is not None:
        validate_coverage(world,coverage)
        comparisons={s['site_id']:'aggregator' for s in coverage['sites']}
    else:comparisons={'aggregator':'aggregator'}
    if set(stores)&set(comparisons):raise ValueError('Comparison and retailer site IDs collide')
    return {**stores,**comparisons}


def generate_interaction_patterns(world,locations=None,*,coverage=None,seed=0,config=None):
    if type(seed) is not int:raise ValueError('Interaction seed must be an integer')
    settings=resolve_config(config);sites=_registry(world,coverage)
    if locations is not None:validate_locations(world,locations)
    dest=destination_alias(locations);rows=[]
    for sid,kind in sorted(sites.items()):
        ns=VERSION+'/'+sid;weights=settings['profile_weights'];names=sorted(weights)
        profile=weighted(rng(seed,ns+'/profile'),names,[weights[k] for k in names])
        cfg={**PROFILES[profile],**{k:v for k,v in settings.items() if k!='profile_weights'}}
        def draw(name):return rng(seed,ns+'/'+name).random()<cfg[name]
        forms=cfg['destination_form_weights'];names=sorted(forms)
        form=weighted(rng(seed,ns+'/destination'),names,[forms[k] for k in names]) if kind=='retailer' and dest else 'none'
        if form=='split' and len(dest['postcode_parts'])!=2:form='single'
        rows.append({'site_id':sid,'kind':kind,'search_sections':draw('search_sections_probability'),
            'result_presentation':'list' if kind=='retailer' and draw('list_probability') else 'cards',
            'offer_disclosure':'expand' if kind=='aggregator' and draw('offer_expand_probability') else 'inline',
            'specification_disclosure':'expand' if kind=='retailer' and draw('spec_expand_probability') else 'inline',
            'shipping_disclosure':'separate' if kind=='retailer' and draw('shipping_separate_probability') else 'inline',
            'destination_form':form,'related_limit':rng(seed,ns+'/related-limit').choice(cfg['related_limits']) if kind=='retailer' else 0})
    result={'schema_version':VERSION,'source_world_sha256':world['world_sha256'],
        'source_locations_sha256':locations['locations_sha256'] if locations else None,
        'source_comparison_coverage_sha256':digest(coverage) if coverage else None,'destination':dest,'sites':rows}
    validate_interaction_patterns(world,result,locations,coverage=coverage)
    return result


def validate_interaction_patterns(world,data,locations=None,*,coverage=None):
    sites=_registry(world,coverage)
    if not isinstance(data,dict) or set(data)!=TOP_FIELDS or data['schema_version']!=VERSION:
        raise ValueError('Unsupported interaction pattern sidecar')
    if data['source_world_sha256']!=world['world_sha256']:raise ValueError('Interaction patterns belong to another world')
    if locations is not None:validate_locations(world,locations)
    if data['source_locations_sha256']!=(locations['locations_sha256'] if locations else None):raise ValueError('Interaction patterns belong to different geography')
    if data['source_comparison_coverage_sha256']!=(digest(coverage) if coverage else None):raise ValueError('Interaction patterns belong to different comparison coverage')
    if data['destination']!=destination_alias(locations):raise ValueError('Destination alias differs from frozen home location')
    if data['destination'] is not None and data['destination'].get('synthetic') is not True:raise ValueError('Destination alias must be explicitly synthetic')
    if not isinstance(data['sites'],list):raise ValueError('Interaction sites must be a list')
    seen=set()
    for row in data['sites']:
        if not isinstance(row,dict) or set(row)!=FIELDS:raise ValueError('Invalid interaction site fields')
        sid=row['site_id']
        if not isinstance(sid,str) or sid not in sites or sid in seen or row['kind']!=sites[sid]:raise ValueError('Unknown or duplicate interaction site')
        seen.add(sid)
        if type(row['search_sections']) is not bool:raise ValueError('search_sections must be boolean')
        choices={'result_presentation':('cards','list'),'offer_disclosure':('inline','expand'),
                 'specification_disclosure':('inline','expand'),'shipping_disclosure':('inline','separate'),
                 'destination_form':('none','single','split')}
        for key,values in choices.items():
            if row[key] not in values:raise ValueError('Invalid '+key)
        if type(row['related_limit']) is not int or not 0<=row['related_limit']<=12:raise ValueError('Invalid related limit')
        if row['kind']=='aggregator' and any(row[k]!=v for k,v in {'result_presentation':'cards','specification_disclosure':'inline','shipping_disclosure':'inline','destination_form':'none','related_limit':0}.items()):
            raise ValueError('Retail-only controls on comparison site')
        if row['kind']=='retailer' and row['offer_disclosure']!='inline':raise ValueError('Comparison-only control on retailer')
        if row['destination_form']!='none' and data['destination'] is None:raise ValueError('Destination form has no known destination')
        if row['destination_form']=='split' and len(data['destination']['postcode_parts'])!=2:raise ValueError('Split form requires a two-part postcode')
    if seen!=set(sites):raise ValueError('Missing interaction sites')
    return {'valid':True,'sites':len(seen),'public_sha256':digest(data)}


def attach_interaction_patterns(scenario,*,coverage=None,seed=0,config=None):
    """Return an additive scenario copy; canonical task/business facts stay intact."""
    result=deepcopy(scenario)
    result['interaction_patterns']=generate_interaction_patterns(result['bundle'],result.get('locations'),coverage=coverage,seed=seed,config=config)
    return result
