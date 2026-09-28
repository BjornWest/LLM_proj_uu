"""Explicit demonstration presentation; layout, filters and membership are separate."""
from .comparison_designs import Design,FACETS
from .comparison_alternatives import Ledger,Finder
from .comparison_discovery import sample_discovery


def demonstration(owner):
    available={f:{k for x in owner.comparisons if x['category']==f for k in x['attributes']} for f in owner.families}
    fields={f:[k for k in FACETS.get(f,[]) if k in available[f]] for f in owner.families}
    broad={'attributes':fields,'price_ceiling':True,'sorting':True}
    simple={'attributes':{f:keys[:1] for f,keys in fields.items()},'price_ceiling':True,'sorting':False}
    footwear={'attributes':{'footwear':[k for k in ['shoe_type','activity'] if k in available.get('footwear',set())]},'price_ceiling':False,'sorting':True}
    laptops={'attributes':{'laptops':[k for k in ['ram_gb','storage_gb'] if k in available.get('laptops',set())]},'price_ceiling':True,'sorting':True}
    return {'comparison-general-a':{'layout':'directory','name':'Prislyktan','family':None,'filters':broad,'discovery':sample_discovery(42)},
            'comparison-general-b':{'layout':'ledger','name':'Prisradar','family':None,'filters':simple},
            'comparison-footwear':{'layout':'specialist','name':'Stegvis','family':'footwear','filters':footwear},
            'comparison-laptops':{'layout':'finder','name':'Datorval','family':'laptops','filters':laptops}}


def create(owner,profile,coverage):
    if set(profile)-{'discovery'}!={'layout','name','family','filters'}:raise ValueError('Unknown design profile fields')
    common={'family':profile['family'],'name':profile['name'],'coverage':coverage,'filter_config':profile['filters']}
    layout=profile['layout']
    if profile.get('discovery') is not None and layout!='directory':raise ValueError('Discovery section currently supported on directory base only')
    if layout=='directory':return Design(owner,layout=layout,discovery=profile.get('discovery'),**common)
    if layout=='specialist':return Design(owner,layout=layout,**common)
    if layout=='ledger':return Ledger(owner,**common)
    if layout=='finder':return Finder(owner,**common)
    raise ValueError('Unknown comparison base design')
