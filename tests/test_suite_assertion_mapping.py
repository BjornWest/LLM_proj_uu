"""Native typed-slot and title-axis mappings, without new browser/model runs."""
from copy import deepcopy
from hashlib import sha256
import json
import pytest
from training.browser_training.fact_role_joins import (
    typed_slot_assertions, page_title_axes, selected_configurations)
from training.browser_training.suite_source_inventory import build_inventory, pin
from training.browser_training.fact_exposure import object_digest
from training.browser_training.task_prefix_coverage import project


def source(identifier, text):
    return dict(id=identifier, text=text, sha256=sha256(text.encode()).hexdigest())


def part(name, identifier, text):
    return dict(part=name, spans=[dict(source_id=identifier, start=0,
        end=len(text.encode('utf-16-le'))//2)])


def slot():
    text='Reference configuration (gray / Wi-Fi only): weight 470 g.'
    assertion=dict(semantic_id='tablet.reference_mass',field='product.facts.reference_mass_g',
        authority='catalog_fact',subject={'kind':'product','id':'p'},
        value=470,status='known',unit='g',qualifiers={})
    row=dict(id='slot',binding=dict(authority='native_existing_public_dom',source_family='retailer',
        field=None,slot_id='tablet.size_weight',status='known',displayed_value=text,
        product_id='p',site_id='shop',sku_id='selected-green',assertions=[assertion]),
        effective_state={'product_id':'p','sku_id':'selected-green'},
        parts=[part('label','label','Reference size weight'),part('value','value',text)])
    sources={s['id']:s for s in [source('label','Reference size weight'),source('value',text)]}
    return row,sources,assertion


def title():
    text='Sandal 🥾 — standard'
    state=dict(site='shop',product_id='p',page_id='page',sku_id='sku',offer_id='offer',
        page_configuration={'width':'standard'},selection={'size':'38'})
    row=dict(id='title',binding=dict(authority='native_existing_public_dom',source_family='retailer',
        field='product_name',displayed_value=text,site_id='shop',product_id='p',page_id='page',
        sku_id='sku',offer_id='offer'),effective_state=state,
        parts=[part('value','title-text',text)])
    return row,{'title-text':source('title-text',text)}


def write(path,value):
    path.write_text(json.dumps(value));return pin(path)


def inventory(tmp_path,row,sources,need):
    trace=tmp_path/'trace';trace.mkdir()
    task=dict(schema_version='fixture',task_id='t',memories=[])
    program=dict(schema='compiled-task-requirements-v1',source_schema='fixture',task_id='t',
        task_sha256=object_digest(task),semantics={},information_needs=[need])
    t=write(tmp_path/'task.json',task);p=write(tmp_path/'program.json',program)
    write(trace/'metadata.json',dict(native_task_id='t',fact_recording={'enabled':True}))
    write(trace/'fact-capture-0001.json',dict(sources=list(sources.values()),
        private_context={'occurrences':[row]}))
    return build_inventory(trace,task=t,compiled=p)


def need(assertion):
    return dict(id='mass',field_role=assertion['field'],unit='g',
        qualifiers=dict(product_id='p',row=dict(slotId='tablet.size_weight',
            label='Reference size weight',assertions=[deepcopy(assertion)])))


def test_declared_assertion_requires_full_slot_and_retains_reference_subject(tmp_path):
    row,sources,assertion=slot();original=deepcopy(row)
    expanded=typed_slot_assertions({'occurrences':[row]},sources)[0]
    assert expanded['parts']==row['parts'] and row==original
    assert expanded['binding']['typed_assertion']==assertion
    assert expanded['binding']['sku_id']=='selected-green'
    inv=inventory(tmp_path,row,sources,need(assertion));assert inv['mapped_field_templates']==1
    target=inv['targets'][0];assert target['assertion_bindings']==[assertion]
    witness=target['witnesses'][0];sha=witness['capture_sha256']
    # Merely the weight substring omits the reference configuration and label.
    end=len(sources['value']['text']);ranges={(sha,'value'):[(end-6,end)]}
    assert project(inv,ranges,{},read_complete=True)['rows'][0]['status']=='partial'
    full={(sha,s['id']):[(0,len(s['text']))] for s in sources.values()}
    assert project(inv,full,{},read_complete=True)['rows'][0]['status']=='complete'


@pytest.mark.parametrize('bad',['subject','authority','status','unit','value','semantic_id',
    'no_slot','slot_status','missing_label','missing_value','truncated_value','different_display',
    'wrong_slot_contract','wrong_label_contract','wrong_assertion_contract','undeclared','foreign_state'])
def test_private_or_incomplete_assertions_do_not_earn_mapping(tmp_path,bad):
    row,sources,a=slot();n=need(a);actual=row['binding']['assertions'][0]
    if bad=='subject':actual['subject']['id']='foreign'
    elif bad=='authority':actual['authority']='private_oracle'
    elif bad=='status':actual['status']='unknown'
    elif bad=='unit':actual['unit']='kg'
    elif bad=='value':actual['value']=float('nan')
    elif bad=='semantic_id':actual['semantic_id']=''
    elif bad=='no_slot':row['binding']['slot_id']=None
    elif bad=='slot_status':row['binding']['status']='not_applicable'
    elif bad.startswith('missing_'):sources.pop(bad.removeprefix('missing_'))
    elif bad=='truncated_value':row['parts'][1]['spans'][0]['end']-=3
    elif bad=='different_display':row['binding']['displayed_value']='weight 470 g'
    elif bad=='wrong_slot_contract':n['qualifiers']['row']['slotId']='foreign'
    elif bad=='wrong_label_contract':n['qualifiers']['row']['label']='Selected weight'
    elif bad=='wrong_assertion_contract':n['qualifiers']['row']['assertions'][0]['value']=471
    elif bad=='undeclared':n['qualifiers'].pop('row')
    elif bad=='foreign_state':row['effective_state']['product_id']='foreign'
    assert inventory(tmp_path,row,sources,n)['mapped_field_templates']==0


def test_exact_assertion_id_can_supply_the_declared_identity(tmp_path):
    row,sources,a=slot();n=need(a);n['qualifiers'].pop('row');n['producer_assertion_id']=a['semantic_id']
    assert inventory(tmp_path,row,sources,n)['mapped_field_templates']==1


@pytest.mark.parametrize('nested',[False,True])
def test_boolean_numeric_assertion_declarations_are_not_equivalent(tmp_path,nested):
    row,sources,a=slot()
    if nested:a['qualifiers']['limit']=0
    else:a['value']=0
    n=need(a)
    declared=n['qualifiers']['row']['assertions'][0]
    if nested:declared['qualifiers']['limit']=False
    else:declared['value']=False
    assert inventory(tmp_path,row,sources,n)['mapped_field_templates']==0


def test_json_number_transport_keeps_integral_float_equivalence(tmp_path):
    row,sources,a=slot();n=need(a)
    n['qualifiers']['row']['assertions'][0]['value']=470.0
    assert inventory(tmp_path,row,sources,n)['mapped_field_templates']==1


@pytest.mark.parametrize('id_only',[False,True])
def test_present_but_truncated_label_cannot_drop_reference_qualification(tmp_path,id_only):
    row,sources,a=slot();n=need(a)
    # Even a matching task row cannot excuse a truncated producer registration.
    row['parts'][0]['spans'][0]['start']=len('Reference ')
    if id_only:
        n['qualifiers'].pop('row');n['producer_assertion_id']=a['semantic_id']
    else:n['qualifiers']['row']['label']='size weight'
    assert inventory(tmp_path,row,sources,n)['mapped_field_templates']==0


def test_title_axis_utf16_and_full_title_context_are_exact():
    row,sources=title();original=deepcopy(row)
    axis=page_title_axes({'occurrences':[row]},sources)[0]
    span=axis['parts'][1]['spans'][0]
    text=sources['title-text']['text'].encode('utf-16-le')
    assert text[2*span['start']:2*span['end']].decode('utf-16-le')=='standard'
    assert axis['parts'][0]['spans']==row['parts'][0]['spans'] and row==original
    joined=selected_configurations({'occurrences':[row,axis]},sources)[0]
    assert joined['unresolved_axes']==['size'] and joined['parts']==[]
    assert [p['part'] for p in joined['resolved_axis_parts']]==['width.label','width.value']


@pytest.mark.parametrize('bad',['foreign_product','foreign_site','wrong_suffix','empty_name',
    'multiple_axes','numeric_axis','missing_source','truncated_title','duplicate_title','foreign_authority'])
def test_title_state_is_not_a_substitute_for_exact_producer_text(bad):
    row,sources=title();rows=[row]
    if bad=='foreign_product':row['binding']['product_id']='foreign'
    elif bad=='foreign_site':row['binding']['site_id']='foreign'
    elif bad=='wrong_suffix':row['effective_state']['page_configuration']['width']='wide'
    elif bad=='empty_name':row['binding']['displayed_value']=' — standard'
    elif bad=='multiple_axes':row['effective_state']['page_configuration']['height']='low'
    elif bad=='numeric_axis':row['effective_state']['page_configuration']['width']=1
    elif bad=='missing_source':sources.clear()
    elif bad=='truncated_title':row['parts'][0]['spans'][0]['end']-=2
    elif bad=='duplicate_title':rows.append(deepcopy(row))
    elif bad=='foreign_authority':row['binding']['authority']='guessed_title'
    assert page_title_axes({'occurrences':rows},sources)==[]


def test_malformed_or_changed_assertion_sources_fail_explicitly():
    row,sources,_=slot();row['binding']['assertions']={}
    with pytest.raises(ValueError,match='Malformed'):typed_slot_assertions({'occurrences':[row]},sources)
    row,sources,_=slot();sources['value']['text']='changed'
    with pytest.raises(ValueError,match='Changed'):typed_slot_assertions({'occurrences':[row]},sources)
