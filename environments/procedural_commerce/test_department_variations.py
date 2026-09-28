import pytest
from environments.procedural_commerce.presentation import resolve_presentations
from environments.procedural_commerce.department_variations import BASE,CONTRAST,CHOICES


def test_each_axis_can_change_without_changing_others():
    designs={'nordhem':'department-market'}
    _,a=resolve_presentations(7,['nordhem'],designs,{'nordhem':BASE})
    for key in CHOICES:
        _,b=resolve_presentations(7,['nordhem'],designs,{'nordhem':{**BASE,key:CONTRAST[key]}})
        assert {k:v for k,v in a['nordhem'].items() if k!=key}=={k:v for k,v in b['nordhem'].items() if k!=key}


def test_unsupported_and_invalid_options_fail_explicitly():
    for design in ('technical-catalog','editorial-boutique','legacy-catalog'):
        with pytest.raises(ValueError):resolve_presentations(7,['nordhem'],{'nordhem':design},{'nordhem':{'product_structure':'details-first'}})
    with pytest.raises(ValueError):resolve_presentations(7,['nordhem'],{'nordhem':'department-market'},{'nordhem':{'fact_structure':'magic'}})
