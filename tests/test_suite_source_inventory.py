"""Required-vs-observed inventory controls independent of any model or oracle."""
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import pytest
from training.browser_training.fact_exposure import object_digest
from training.browser_training.suite_source_inventory import build_inventory, pin


def write(path,value):
    path.write_text(json.dumps(value));return pin(path)


def fixture(tmp_path):
    trace=tmp_path/'trace';trace.mkdir()
    task={'schema_version':'native-fixture','task_id':'task','memories':[]}
    program={'schema':'compiled-task-requirements-v1','source_schema':task['schema_version'],
        'task_id':'task','task_sha256':object_digest(task),'semantics':{},
        'information_needs':[{'id':'price','field_role':'listed_price_minor','qualifiers':{'product_id':'p'}},
            {'id':'stock','field_role':'dispatch_stock','qualifiers':{}}]}
    t=write(tmp_path/'task.json',task);p=write(tmp_path/'compiled.json',program)
    write(trace/'metadata.json',{'native_task_id':'task','fact_recording':{'enabled':True}})
    source={'id':'harness-source','export_id':'dom-run','text':'49 kr','sha256':sha256(b'49 kr').hexdigest()}
    occurrence={'id':'o','binding':{'field':'listing_price','product_id':'p','site_id':'shop'},
        'effective_state':{'sku_id':'s','product_id':'p'},
        'parts':[{'part':'value','spans':[{'source_id':'dom-run','start':0,'end':5}]}]}
    capture={'sources':[source],'private_context':{'occurrences':[occurrence]}}
    c=write(trace/'fact-capture-0001.json',capture)
    return trace,t,p,c,program,capture


def test_exact_export_join_is_a_witness_not_observation_or_reward(tmp_path):
    trace,t,p,c,_,_=fixture(tmp_path);inventory=build_inventory(trace,task=t,compiled=p)
    assert inventory['field_templates']==2 and inventory['mapped_field_templates']==1
    price=next(x for x in inventory['targets'] if x['need_id']=='price')
    assert price['witnesses'][0]['parts'][0]['spans'][0]['source_id']=='harness-source'
    assert 'observed' not in price and 'reward' not in inventory
    stock=next(x for x in inventory['targets'] if x['need_id']=='stock')
    assert stock['witnesses']==[] and stock['reason']=='unresolved_task_role_or_subject'
    assert inventory['unmapped_field_templates']==['dispatch_stock']


@pytest.mark.parametrize('mutation',['different_product','missing_AX_source','empty_spans'])
def test_private_truth_or_foreign_scope_cannot_fill_a_public_mapping(tmp_path,mutation):
    trace,t,p,c,_,capture=fixture(tmp_path)
    if mutation=='different_product':capture['private_context']['occurrences'][0]['binding']['product_id']='q'
    if mutation=='missing_AX_source':capture['sources']=[]
    if mutation=='empty_spans':capture['private_context']['occurrences'][0]['parts'][0]['spans']=[]
    write(Path(c['path']),capture)
    inventory=build_inventory(trace,task=t,compiled=p)
    assert inventory['mapped_field_templates']==0
    assert all(not x['witnesses'] for x in inventory['targets'])


def test_changed_task_program_or_source_dependencies_reject(tmp_path):
    trace,t,p,c,program,capture=fixture(tmp_path)
    program['task_sha256']='0'*64;p=write(Path(p['path']),program)
    with pytest.raises(ValueError,match='identity'):build_inventory(trace,task=t,compiled=p)
    with pytest.raises(ValueError,match='Changed inventory input'):
        build_inventory(trace,task={**t,'sha256':'0'*64},compiled=p)


def test_task_trace_identity_is_checked_separately(tmp_path):
    trace,t,p,c,_,_=fixture(tmp_path)
    write(trace/'metadata.json',{'native_task_id':'foreign','fact_recording':{'enabled':True}})
    with pytest.raises(ValueError,match='trace identity'):build_inventory(trace,task=t,compiled=p)


@pytest.mark.parametrize('qualifier',[{'retailer_role':'has_actual_initial_cart'},
    {'declaration_sha256':'task-declaration'}, {'product_id':'p','basis':'added_item_subtotal'}, {}])
def test_unresolved_roles_cannot_be_satisfied_by_an_arbitrary_product(tmp_path,qualifier):
    trace,t,p,c,program,_=fixture(tmp_path)
    program['information_needs'][0]['qualifiers']=qualifier;p=write(Path(p['path']),program)
    inventory=build_inventory(trace,task=t,compiled=p)
    assert inventory['mapped_field_templates']==0
    price=next(x for x in inventory['targets'] if x['need_id']=='price')
    assert not price['witnesses'] and price['reason']=='unresolved_task_role_or_subject'


def test_later_mapping_failure_does_not_override_an_exact_witness(tmp_path):
    trace,t,p,c,_,capture=fixture(tmp_path)
    capture['sources']=[];write(trace/'fact-capture-0002.json',capture)
    inventory=build_inventory(trace,task=t,compiled=p)
    price=next(x for x in inventory['targets'] if x['need_id']=='price')
    assert price['witnesses'] and 'reason' not in price
    assert inventory['unresolved_occurrence_parts']


@pytest.mark.parametrize('missing',['parts','site'])
def test_malformed_occurrences_have_an_explicit_validation_error(tmp_path,missing):
    trace,t,p,c,_,capture=fixture(tmp_path);row=capture['private_context']['occurrences'][0]
    if missing=='parts':del row['parts']
    else:
        row['effective_state'].update(quote_result={'quoteId':'q','shipments':[{}]},draft={})
        row['binding']['quote_id']='q'
    write(Path(c['path']),capture)
    with pytest.raises(ValueError,match='Malformed'):
        build_inventory(trace,task=t,compiled=p)



def test_price_selection_qualifier_cannot_bind_a_different_variant(tmp_path):
    trace,t,p,c,program,capture=fixture(tmp_path)
    program['information_needs'][0]['qualifiers']['selection']={'size':38};p=write(Path(p['path']),program)
    capture['private_context']['occurrences'][0]['effective_state']['selection']={'size':40}
    write(Path(c['path']),capture)
    assert build_inventory(trace,task=t,compiled=p)['mapped_field_templates']==0


@pytest.mark.parametrize('bad',['sources','context','shipment_index','selected_service'])
def test_malformed_capture_and_service_contracts_reject_explicitly(tmp_path,bad):
    trace,t,p,c,_,capture=fixture(tmp_path)
    if bad=='sources':del capture['sources']
    elif bad=='context':capture['private_context']=[]
    else:
        row=capture['private_context']['occurrences'][0]
        row['effective_state'].update(site='shop',draft={},quote_result={'quoteId':'q','shipments':[{}]})
        row['binding'].update(field='selected_service',quote_id='q')
        if bad=='selected_service':row['binding']['shipment_index']=0
    write(Path(c['path']),capture)
    with pytest.raises(ValueError,match='Malformed'):build_inventory(trace,task=t,compiled=p)


def test_native_declaration_source_root_is_independent_and_rejects_foreign_bytes(tmp_path):
    from types import SimpleNamespace
    from training.browser_training.feature_offer_requirements import checked_native_sources
    native=tmp_path/'producer';file=native/'environments/website_world/feature_offer_task.py';file.parent.mkdir(parents=True);file.write_text('native')
    declaration=native/'environments/website_world/fields.json';declaration.write_text('declared')
    module=SimpleNamespace(__file__=str(file));name='environments/website_world/fields.json'
    checked_native_sources({name:sha256(declaration.read_bytes()).hexdigest()},module)
    with pytest.raises(ValueError,match='source changed'):checked_native_sources({name:'0'*64},module)
    with pytest.raises(ValueError,match='source changed'):checked_native_sources({'../escape':'0'*64},module)
