from copy import deepcopy
import pytest
from .comparison_discovery import sample_discovery,select,validate,LABELS
from .comparison_designs import Design
from .test_comparison_designs import owner


def test_seeded_balanced_selection():
    items=[{'id':f'{family}-{i}','category':family} for family in ['shoe','laptop','food'] for i in range(20)]
    config={'mode':'trending','seed':42,'limit':12}
    result=select(items,config)
    assert result==select(list(reversed(items)),config)
    assert len({x['id'] for x in result})==12
    assert {x['category'] for x in result[:3]}=={'shoe','laptop','food'}
    assert {sample_discovery(i)['mode'] for i in range(30)}==set(LABELS)
    assert result!=select(items,{**config,'seed':43})


@pytest.mark.parametrize('mode',list(LABELS))
def test_section_is_scoped_and_links_resolve(owner,mode):
    before=deepcopy(owner.comparisons)
    scope={'site_id':'example','families':['footwear'],'comparison_ids':['shoe'],'listings':[]}
    d=Design(owner,coverage=scope,discovery={'mode':mode,'seed':1,'limit':12})
    html=d.discovery_section()
    assert LABELS[mode] in html and 'Laptop 16 GB' not in html
    assert '/models/shoe' in html and 'No listed price' in html
    assert d.render('/models/shoe',{})[0]==200
    assert owner.comparisons==before
    assert Design(owner).discovery_section()==''
    scope['comparison_ids']=[]
    assert Design(owner,coverage=scope,discovery={'mode':mode,'seed':1,'limit':12}).discovery_section()==''


@pytest.mark.parametrize('config',[{'mode':'wrong','seed':1,'limit':12},{'mode':'new','seed':True,'limit':12},{'mode':'new','seed':1,'limit':0}])
def test_invalid_settings(config):
    with pytest.raises(ValueError):validate(config)
