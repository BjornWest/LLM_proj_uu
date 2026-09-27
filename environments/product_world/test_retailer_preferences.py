from copy import deepcopy
import pytest
from environments.shopping_intent.retailer_preferences import resolve
from environments.shopping_intent.world import fingerprint
from .scenario import generate_scenario
from .outcomes import evaluate

@pytest.mark.parametrize('mode',['request','memory','override'])
def test_named_retailer_preferences_bind_real_stores_and_grade_without_changing_world(mode):
    args={'seed':7,'family':'laptops','destination_city':'malmo','memory':'mixed','world_preferences':'none','hidden':'none'}
    base=generate_scenario(args,{'seed':42,'models_per_store':1},{})
    s=generate_scenario({**args,'retailer_preferences':mode},{'seed':42,'models_per_store':1},{})
    assert s['bundle']==base['bundle'] and s['locations']==base['locations']
    t=s['task'];assert t['semantic_sha256']==fingerprint(t)
    assert '[[retailer:' not in str(t['public'])
    excluded=t['resolved_task']['excluded_retailer_ids']
    assert len(excluded)==(0 if mode=='override' else 1)
    result=evaluate(s)
    for a,c in zip(result['outcome']['candidate_assessments'],result['candidates']):
        assert a['requirements']['retailer_preferences']==(c['lines'][0]['retailer_id'] not in excluded)
    assert t['hidden_user_specifications']==[]


def test_multiple_exclusions_and_explicit_permission_override():
    remembered=[{'retailer_id':'a','avoid':True},{'retailer_id':'b','avoid':True}]
    assert resolve(remembered,[{'retailer_id':'a','avoid':False}])==['b']
