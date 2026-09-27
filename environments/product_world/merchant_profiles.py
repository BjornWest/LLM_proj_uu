"""Authored scale correlations, orthogonal to product specialization."""
import math
from .generator import rng, weighted
from .config import _weights

PROFILES = {
    'local_shop': {'label':'Local shop','models_factor':.6,'stock_max':8,'branches':(1,2),'international_probability':.05},
    'regional_chain': {'label':'Regional chain','models_factor':1,'stock_max':30,'branches':(3,5),'international_probability':.25},
    'major_retailer': {'label':'Major retailer','models_factor':1.8,'stock_max':120,'branches':(6,10),'international_probability':.8},
    'online_specialist': {'label':'Online specialist','models_factor':1.2,'stock_max':45,'branches':(0,0),'international_probability':.6},
}


def sample_profiles(seed, retailer_ids, base_models=5, weights=None):
    if type(seed) is not int:raise ValueError('Profile seed must be an integer')
    if type(base_models) is not int or not 1<=base_models<=20:raise ValueError('models_per_store must be 1..20')
    priors=_weights({'local_shop':.35,'regional_chain':.35,'major_retailer':.2,'online_specialist':.1}, {} if weights is None else weights, 'merchant profile weights')
    result={}
    for id in retailer_ids:
        key=weighted(rng(seed,id+'/scale'),list(priors),list(priors.values()));p=PROFILES[key]
        result[id]={'profile_id':key,'label':p['label'],
            'model_count':max(1,min(20,math.ceil(base_models*p['models_factor']))),
            'stock_max':p['stock_max'],'branch_count':rng(seed,id+'/branch-count').randint(*p['branches']),
            'international_probability':p['international_probability']}
    return result
