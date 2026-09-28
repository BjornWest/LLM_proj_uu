"""Shoe type is discoverable model data, never an exact-fit selection control."""
from copy import deepcopy
import pytest
from .test_comparison_designs import owner
from .comparison_designs import Design
from .comparison_alternatives import Ledger, Finder
from .comparison_profiles import demonstration

@pytest.mark.parametrize('layout',['directory','specialist','ledger','finder'])
def test_type_filter_preserves_model_identity_and_absent_types(owner,layout):
    base=next(x for x in owner.comparisons if x['category']=='footwear')
    rows=[]
    for i,kind in enumerate(('walking shoes','dress shoes','flip-flops')):
        row=deepcopy(base);row.update(id=f'shoe-{i}',path=f'/models/shoe-{i}',name=f'Example {kind}')
        row['attributes']['shoe_type']=kind;rows.append(row)
    owner.comparisons=rows
    profile={'attributes':{'footwear':['shoe_type','activity']},'price_ceiling':False,'sorting':False}
    if layout in ('directory','specialist'):
        design=Design(owner,layout=layout,family='footwear' if layout=='specialist' else None,filter_config=profile)
    else:design=(Ledger if layout=='ledger' else Finder)(owner,family='footwear' if layout=='finder' else None,filter_config=profile)
    facets=design.facet_options('footwear');index=facets['shoe_type'].index('dress shoes')
    result,category,selected=design.filtered({'category':'footwear',f'f_shoe_type_{index}':'1'})
    assert [r['id'] for r in result]==['shoe-1']
    html=design.filters({},category,selected)
    assert 'Shoe type' in html and 'flip-flops' in html
    assert all(k not in facets for k in ('size_eu','colour','width'))
    # Multi-choice stays OR, rather than impossible intersection across types.
    ix=facets['shoe_type'].index('walking shoes')
    assert len(design.filtered({'category':'footwear',f'f_shoe_type_{index}':'1',f'f_shoe_type_{ix}':'1'})[0])==2


def test_old_world_has_no_invented_type_and_new_profiles_discover_it(owner):
    assert 'shoe_type' not in Design(owner).facet_options('footwear')
    for item in owner.comparisons:
        if item['category']=='footwear':item['attributes']['shoe_type']='walking shoes'
    profiles=demonstration(owner)
    for key in ('comparison-general-a','comparison-footwear'):
        assert 'shoe_type' in profiles[key]['filters']['attributes']['footwear']
