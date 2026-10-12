"""Atomic schema dispatch and immutable qualifier/task binding; no browser runs."""
from copy import deepcopy
from unittest.mock import Mock

import pytest

from training.browser_training import atomic_product_requirements as atomic
from training.browser_training.suite_task_requirements import compile_suite_task


def fixture(schema=atomic.QUALIFIED_NATIVE, kind='read_public_fact'):
    row={'field':'product.facts.reference_mass_g', 'label':'Reference mass',
         'value':470, 'unit':'g', 'qualifier':'Wi-Fi / 4GB / 64GB / gray'}
    fact={'heading':'Product details','row':row}
    if schema==atomic.QUALIFIED_NATIVE:
        fact['qualifier_declaration']={
            'version':'website-canonical-qualifier-domains-v1',
            'field':'product.facts.reference_configuration',
            'values':[row['qualifier'],'Wi-Fi / 128GB / RAM unknown / silver'],
            'source_sha256':{'producer/reference.json':'a'*64,'producer/base.json':'b'*64}}
    task=dict(schema_version=schema,kind=kind,spec={'kind':kind},
              task_id='original-task',world_id='original-world',world_sha256='1'*64,
              catalog_sha256='2'*64,bindings_sha256='3'*64,
              checkout_domain_sha256='4'*64,retailer_id='r',product_id='p',
              sku_id='s',offer_id='o',page_id='page',selection={'size':'42'},
              initial_selection=None,public_fact=fact if kind=='read_public_fact' else None,
              user_message='Read this product fact with its stated qualification.',memories=[])
    catalog={'products':[{'id':'page','variants':[{'offerId':'o','details':[]}],
                          'options':[{'key':'size','label':'Size'}]}]}
    native=Mock(return_value=deepcopy(task))
    inputs=dict(native_make=native,world={'world_id':'original-world'},catalog=catalog,
                bindings={'original':'bindings'},checkout_domain={'original':'domain'})
    return task,inputs


@pytest.mark.parametrize('schema',[atomic.NATIVE,atomic.QUALIFIED_NATIVE])
def test_both_entrypoints_bind_canonical_task_without_mutating_inputs(schema):
    task,inputs=fixture(schema);before=deepcopy(task)
    direct=atomic.compile_atomic(task,**inputs)
    dispatched=compile_suite_task(task,native_inputs=inputs)
    assert direct==dispatched and task==before
    assert direct['source_schema']==schema
    assert direct['task_sha256']==atomic.digest(task)
    assert direct['semantic_sha256']==atomic.digest(direct['semantics'])
    assert direct['semantics']['fact']==task['public_fact']
    assert [n['id'] for n in direct['information_needs']]==['configuration','requested_public_fact']
    assert direct['capability']['exposure_mapping']=='not_bound'
    inputs['native_make'].assert_called_with(inputs['world'],task['spec'],
        catalog=inputs['catalog'],bindings=inputs['bindings'],checkout_domain=inputs['checkout_domain'])


def test_complete_declaration_is_retained_without_creating_alternative_read_obligations():
    task,inputs=fixture();compiled=compile_suite_task(task,native_inputs=inputs)
    domain=compiled['semantics']['fact']['qualifier_declaration']
    assert domain==task['public_fact']['qualifier_declaration']
    assert len(domain['values'])==2 and len(domain['source_sha256'])==2
    need=compiled['information_needs'][1]
    assert need['qualifiers']['row']['qualifier']==domain['values'][0]
    assert domain['values'][1] not in str(compiled['information_needs'])
    domain['values'].append('changed');domain['source_sha256'].clear()
    assert len(task['public_fact']['qualifier_declaration']['values'])==2
    assert len(task['public_fact']['qualifier_declaration']['source_sha256'])==2


@pytest.mark.parametrize('mutation',['version','values','source_sha256','qualifier','schema','task_id'])
def test_v2_task_or_declaration_drift_is_rejected_by_full_native_comparison(mutation):
    task,inputs=fixture()
    if mutation in ('version','values','source_sha256'):
        task['public_fact']['qualifier_declaration'][mutation]='changed'
    elif mutation=='qualifier':task['public_fact']['row']['qualifier']='selected SKU'
    elif mutation=='schema':task['schema_version']=atomic.NATIVE
    else:task['task_id']='changed'
    with pytest.raises(ValueError,match='qualifier declaration' if mutation=='schema' else 'mismatch'):
        compile_suite_task(task,native_inputs=inputs)


@pytest.mark.parametrize('kind',['read_listed_price','select_exact_variant','add_exact_quantity'])
@pytest.mark.parametrize('carry_declaration',[False,True])
def test_v2_does_not_expand_to_other_atomic_actions(kind,carry_declaration):
    task,inputs=fixture(kind=kind)
    if carry_declaration:task['public_fact']=fixture()[0]['public_fact']
    with pytest.raises(ValueError,match='declaration-bearing'):
        compile_suite_task(task,native_inputs=inputs)
    inputs['native_make'].assert_not_called()


@pytest.mark.parametrize('value',[None,{},[],False,'declaration'])
def test_v2_requires_a_public_fact_and_a_declaration_object(value):
    task,inputs=fixture();task['public_fact']=value
    with pytest.raises(ValueError,match='declaration-bearing'):
        compile_suite_task(task,native_inputs=inputs)
    inputs['native_make'].assert_not_called()


@pytest.mark.parametrize('value',[None,{},[],False,'declaration'])
def test_v2_rejects_nonobject_declaration(value):
    task,inputs=fixture();task['public_fact']['qualifier_declaration']=value
    with pytest.raises(ValueError,match='declaration-bearing'):
        compile_suite_task(task,native_inputs=inputs)
    inputs['native_make'].assert_not_called()


@pytest.mark.parametrize('schema',[atomic.NATIVE,atomic.QUALIFIED_NATIVE])
@pytest.mark.parametrize('mode',['missing','extra','wrong_reference','uncallable'])
def test_dispatch_requires_exact_native_inputs_for_both_versions(schema,mode):
    task,inputs=fixture(schema);reference=None
    if mode=='missing':inputs.pop('world')
    elif mode=='extra':inputs['ambient_source_root']='mutable'
    elif mode=='wrong_reference':reference={'expected':'answer'}
    else:inputs['native_make']=None
    with pytest.raises(ValueError):
        compile_suite_task(task,native_inputs=inputs,scoring_reference=reference)


@pytest.mark.parametrize('schema',['website-atomic-product-task-v3',None,[],{}])
def test_direct_compiler_rejects_future_and_malformed_versions(schema):
    task,inputs=fixture();task['schema_version']=schema
    with pytest.raises(ValueError,match='Supported exact native atomic'):
        atomic.compile_atomic(task,**inputs)
    inputs['native_make'].assert_not_called()


@pytest.mark.parametrize('kind',['read_listed_price','select_exact_variant','add_exact_quantity'])
def test_literal_and_action_v1_keep_original_needs(kind):
    task,inputs=fixture(atomic.NATIVE,kind=kind)
    compiled=compile_suite_task(task,native_inputs=inputs)
    assert compiled['source_schema']==atomic.NATIVE
    assert compiled['semantics']['fact'] is None
    assert [n['id'] for n in compiled['information_needs']]==(
        ['configuration','item_price'] if kind=='read_listed_price' else ['configuration'])


def test_spliced_v1_does_not_match_either_original_or_fresh_native_factory():
    old,old_inputs=fixture(atomic.NATIVE);fresh,fresh_inputs=fixture()
    spliced=deepcopy(old)
    spliced['public_fact']['qualifier_declaration']=deepcopy(fresh['public_fact']['qualifier_declaration'])
    for inputs in (old_inputs,fresh_inputs):
        with pytest.raises(ValueError,match='qualifier declaration'):
            compile_suite_task(spliced,native_inputs=inputs)
        inputs['native_make'].assert_not_called()


@pytest.mark.parametrize('declaration',[None,{},fixture()[0]['public_fact']['qualifier_declaration']])
def test_declaration_bearing_v1_rejects_even_an_agreeing_intermediate_factory(declaration):
    task,inputs=fixture(atomic.NATIVE)
    task['public_fact']['qualifier_declaration']=deepcopy(declaration)
    inputs['native_make']=Mock(return_value=deepcopy(task))
    with pytest.raises(ValueError,match='Atomic v1 cannot carry'):
        compile_suite_task(task,native_inputs=inputs)
    inputs['native_make'].assert_not_called()
