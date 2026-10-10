"""Focused shared status/stage tests; no authoring guard replay or world draw."""
import importlib.util
from pathlib import Path
from copy import deepcopy
import pytest
from environments.product_world.shared_state import freeze

from experiments.accepted_catalog_commerce import shared_semantics as core

FIELDS={
 'product.product_id':{'type':'string','input':True},
 'product.facts.has_buttons':{'type':'boolean'},
 'product.facts.button_material':{'type':'string'},
 'product.facts.material_status':{'type':'enum','values':['known','unknown','not_applicable']},
 'product.facts.material':{'type':'string'},
 'product.facts.mounting_size':{'type':'string'},
 'sku.mounting_size':{'type':'enum','values':['small','unspecified','not_applicable']},
 'sku.sku_id':{'type':'string'},
}
DEFINITIONS={
 'product.facts.button_material':{'definition':{'type':'string','applicable_when':'product.facts.has_buttons'}},
 'product.facts.material':{'definition':{'type':'string'}},
 'product.facts.mounting_size':{'definition':{'type':'string'}},
 'sku.mounting_size':{'definition':{'type':'enum','unknown_values':['unspecified'],'not_applicable_values':['not_applicable']}},
}

@pytest.mark.parametrize('value,expected',[('small','known'),('unspecified','unknown'),('not_applicable','not_applicable')])
def test_declared_sku_sentinels_also_qualify_same_product_fact(value,expected):
 projection=core.StatusProjection(FIELDS,DEFINITIONS)
 assert projection.status('product.facts.mounting_size',value,{'product':{'facts':{}}})==expected

@pytest.mark.parametrize('status',['known','unknown','not_applicable'])
def test_explicit_sibling_status_is_retained(status):
 projection=core.StatusProjection(FIELDS,DEFINITIONS)
 context={'product':{'facts':{'material_status':status}}}
 assert projection.status('product.facts.material','cotton',context)==status


def test_logical_absence_does_not_become_known_from_a_placeholder():
 projection=core.StatusProjection(FIELDS,DEFINITIONS)
 assert projection.status('product.facts.button_material','none',{'product':{'facts':{'has_buttons':False}}})=='not_applicable'


def test_projection_shares_immutable_manufacture_and_trace_without_resampling():
 projection=core.StatusProjection(FIELDS,DEFINITIONS)
 entities=freeze({'product':{'facts':{'has_buttons':False,'button_material':'none','material':'cotton','material_status':'unknown','mounting_size':'unspecified'},'skus':[{'sku_id':'sku1','mounting_size':'not_applicable'}]}})
 trace=freeze([{'step_id':'manufacture'}])
 result={'entities':entities,'trace':trace,'field_status':{'product.facts.button_material':'known','product.facts.material':'known'}}
 output=projection.project(result)
 assert output['entities'] is entities and output['trace'] is trace
 assert result['field_status']['product.facts.button_material']=='known'
 assert output['field_status']['product.facts.button_material']=='not_applicable'
 assert output['field_status']['product.facts.material']=='unknown'
 assert output['typed_status_projection']['manufactured_SKU_status'][0]['statuses']['sku.mounting_size']=='not_applicable'


def test_market_stage_replaces_one_existing_step_and_preserves_other_nodes():
 unrelated={'id':'material','target':'product.facts.material','sample':'constant','value':'cotton'}
 doc={'concept_id':'trousers.jeans','fields':{},'steps':[unrelated,{'id':'market_range','sample':'constant','value':'unisex'}]}
 original=deepcopy(doc)
 changed,stage=core.compose_market_stage(doc)
 assert doc==original and changed['steps'][0] is unrelated
 assert changed['steps'][1]==stage['steps'][0]
 weights=changed['steps'][1]['weights']
 total=sum(weights.values())
 assert {key:value/total for key,value in weights.items()}=={'men':.4,'women':.4,'unisex':.2}


def test_concept_without_market_stage_is_unchanged_by_identity():
 doc={'concept_id':'beer.lager_pilsner','steps':[],'fields':{}}
 assert core.compose_market_stage(doc)==(doc,None)


from .catalog_registry import SHARED_ADDITIONS, TASK_LABELS
from .execution import Execution
from . import package_export
from .test_catalog_expansion import BRAND
from environments.product_world.execution import TraversalPackage
from environments.product_world.catalog_publication import export_catalog_content, inventory
import json


@pytest.fixture(scope='module')
def execution():
 return Execution()


@pytest.mark.parametrize('cid',SHARED_ADDITIONS)
def test_shared_stages_preserve_authored_manufacture_reviews_and_known_content(execution,cid):
 item=execution.sample(7,cid,BRAND,'semantic-integration/'+cid,review_count=2)
 doc=execution.documents[cid]
 composed,_=core.compose_market_stage(doc)
 raw=TraversalPackage(composed)
 entities=item['private']['sample']['entities']
 assert entities['product']['product_id']=='semantic-integration/'+cid
 assert all(s['product_id']==entities['product']['product_id'] for s in entities['product']['skus'])
 inputs={'brand':entities['brand'],'product':{}}
 for path,d in doc['fields'].items():
  if path.startswith('product.') and path.count('.')==1 and d.get('input'):
   inputs['product'][path.split('.')[1]]=entities['product'][path.split('.')[1]]
 expected=raw.sample(7,inputs=inputs)
 assert entities==expected['entities']
 assert item['private']['sample']['trace']==expected['trace']
 assert cid in TASK_LABELS
 for index,review in enumerate(item['reviews']):
  seed=int.from_bytes(package_export.sha256(f'accepted-catalog-review/7/{index}'.encode()).digest()[:4],'big')
  authored=raw.programs['review'].sample(seed,inputs=entities)
  assert review['rating']==package_export.review_rating(authored['entities'])
  assert review['private_trace']==authored['trace']
  assert review['sku_id']==authored['entities']['sku']['sku_id']
 sid=item['public']['skus'][0]['sku_id']
 packet=export_catalog_content(item,sku_id=sid,seed=7,retailer_id='probe',
    selected_groups=list(inventory(cid)['groups']))
 for group in packet['display_groups']:
  for slot in group['slots']:
   for record in slot['assertions']:
    assert record['status']=='known'
    assert record['subject']['id'] in (item['public']['product_id'],sid)
    assert not record['field'].endswith('model_price_factor')
 assert item['private']['commerce_source_gate']['capability']=='shared_declared_factual_stages_v1'


def test_cache_keeps_one_compiled_manufacture_with_owned_outputs(execution):
 cid='bedding.pillowcases'
 first=execution.sample(7,cid,BRAND,'cache-one')
 packages=tuple(execution.packages.values())
 second=execution.sample(8,cid,BRAND,'cache-two')
 assert tuple(execution.packages.values())==packages
 assert first['public']['product_id']=='cache-one' and second['public']['product_id']=='cache-two'
 assert first['private']['sample']['entities']['product']['product_id']=='cache-one'
 assert first['catalog_status']['product.facts.sewing_thread_composition']=='unknown'
 assert not any(row['source_pool_id']=='description.fabric' for row in first['descriptions'])


def test_full_mode_remains_an_opt_in_on_shared_graphs():
 off=Execution().sample(7,'wine.crisp_light_white_wine',BRAND,'full-parity',review_count=2)
 full=Execution(validation='full').sample(7,'wine.crisp_light_white_wine',BRAND,'full-parity',review_count=2)
 assert full['public']==off['public']
 assert full['catalog_status']==off['catalog_status'] and full['sku_status']==off['sku_status']
 assert full['private']['sample']['trace']==off['private']['sample']['trace']


def test_fixture_only_wok_is_not_admitted_as_fresh_manufacture():
 with pytest.raises(ValueError,match='adopted'):
  package_export.source_gate('cookware.woks')


def test_admission_rejects_changed_entry_and_exact_historical_archive(tmp_path,monkeypatch):
 cid='bedding.sheets'
 ledger=json.loads(package_export.LEDGER.read_text())
 entry=deepcopy(ledger[cid]);entry['invented_field']=True
 with pytest.raises(ValueError,match='accepted entry changed'):
  core.source_gate(cid,root=package_export.ROOT,entry=entry)
 declared=core.registration()[cid]
 alias=next(iter(declared['historical_controls'].values()))
 archive=tmp_path/alias['archive'];archive.parent.mkdir(parents=True)
 archive.write_text('foreign')
 isolated={cid:{'accepted_entry_sha256':declared['accepted_entry_sha256'],
  'source_hashes':{next(iter(declared['historical_controls'])):alias['sha256']},
  'historical_controls':declared['historical_controls']}}
 monkeypatch.setattr(core,'registration',lambda:isolated)
 with pytest.raises(ValueError,match='consumed source changed'):
  core.source_gate(cid,root=tmp_path,entry=ledger[cid])
