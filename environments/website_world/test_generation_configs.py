"""Immutable recipes, explicit overrides and historical evidence preservation."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import json
import subprocess
import sys
import pytest
from environments.website_world.generation_configs import Library, config, capture, digest, unpack, save

REQUEST={'schema':'website-world-generation-v2','seed':62,
 'world':{'controls':{'world_size':4,'product_concentration':1}},
 'task':{'kind':'cheapest_available','concept_id':'footwear.walking_shoes','comparison_site_id':'comparison-00'},
 'requirements':[{'example':'preserve exactly, do not reinterpret in storage'}]}


def test_versions_reuse_and_parent_immutable(tmp_path):
 library=Library(tmp_path);original=deepcopy(REQUEST)
 first=library.put('large',REQUEST,tags=['large','low-concentration'])
 assert library.put('large',REQUEST,tags=['low-concentration','large'])==first
 changed=deepcopy(REQUEST);changed['seed']=63
 second=library.put('large',changed,tags=['large'])
 assert second['version']==2 and second['config_sha256']!=first['config_sha256']
 assert library.get('large@1')==library.get(first['config_sha256'])==first
 assert library.get('large')==second and REQUEST==original
 assert library.search(tag='low-concentration')==[]
 assert library.search(tag='low-concentration',history=True)==[first]
 assert library.search(query='walking_shoes')==[second]
 second['config']['request']['seed']=0
 assert library.get('large')['config']['request']['seed']==63


def test_concurrent_config_versions_are_not_lost(tmp_path):
 library=Library(tmp_path)
 def put(seed):
  return library.put('parallel',{**REQUEST,'seed':seed})
 with ThreadPoolExecutor(max_workers=4) as workers:records=list(workers.map(put,range(8)))
 assert {r['version'] for r in records}==set(range(1,9))
 assert len(library.records())==8


def test_corrupt_recipe_detected_and_invalid_inputs_rejected(tmp_path):
 library=Library(tmp_path);library.put('valid',REQUEST)
 p=next((tmp_path/'recipes').glob('*.json'));value=json.loads(p.read_text())
 value['config']['request']['seed']=99;p.write_text(json.dumps(value))
 with pytest.raises(ValueError,match='digest differs'):library.get('valid')
 for request in ({**REQUEST,'seed':True},{**REQUEST,'schema':'unknown'},{**REQUEST,'seed':float('nan')}):
  with pytest.raises(ValueError):config(request)
 with pytest.raises(ValueError):Library(tmp_path/'other').put('../outside',REQUEST)
 with pytest.raises(ValueError):config(REQUEST,{'lazy_publication':1})


def test_historical_import_preserves_exact_files_and_marks_missing_defaults(tmp_path):
 generated=tmp_path/'old';generated.mkdir();run=tmp_path/'run';run.mkdir()
 save(generated/'request.json',REQUEST)
 save(generated/'basic-offer-task.private.json',{'concept_id':'footwear.walking_shoes','quantity':1})
 save(generated/'execution.private.json',{'validation':'off','runtime_options':{'lazy_publication':True},
 'answer_grading':{'mode':'subscription-post-run'}})
 save(run/'execution-plan.private.json',{'runner_options':{'max_steps':100,'max_input_tokens':100000}})
 before={str(p):p.read_bytes() for folder in (generated,run) for p in folder.iterdir()}
 record,evidence=Library(tmp_path/'library').import_generation(generated,'old',run_directories=[run])
 assert record['config']['request']==REQUEST
 assert record['config']['execution']['lazy_publication'] is True
 assert record['config']['execution']['answer_grading']['model']=='gpt-6.1-sol'
 assert evidence['resolved_defaults_recorded'] is False
 assert 'basic-offer-task.private.json' in evidence['artifacts']
 assert evidence['runs'][0]['artifacts']['execution-plan.private.json']['sha256']
 assert before=={str(p):p.read_bytes() for folder in (generated,run) for p in folder.iterdir()}


def test_resolved_record_preserves_conditions_and_execution_identity():
 resolved={'requirements':[{'id':'condition'}],'world':{'controls':{'world_size':4,'brand_diversity':1}},
 'basic_offer_selection':REQUEST['task']}
 record=capture(REQUEST,resolved,world_id='frozen-world',selected_seed=71)
 assert record['resolved']==resolved and record['selected_seed']==71
 assert record['task_source']=='structured_template' and unpack(record)==config(REQUEST)
 record['execution']['lazy_publication']=True
 with pytest.raises(ValueError,match='digest differs'):unpack(record)


def test_cli_export_seed_and_size_do_not_change_parent(tmp_path):
 library=Library(tmp_path/'library');original=library.put('baseline',REQUEST)
 target=tmp_path/'export.json'
 proc=subprocess.run([sys.executable,'-m','scripts.website_generation_configs','--library',str(library.root),
  'export','baseline@1','--output',str(target),'--seed','63','--world-size','2'],capture_output=True,text=True)
 assert proc.returncode==0,proc.stderr
 exported=json.loads(target.read_text());bundle=unpack(exported)
 assert bundle['request']['seed']==63 and bundle['request']['world']['controls']['world_size']==2
 assert bundle['request']['requirements']==REQUEST['requirements']
 assert exported['derived_from']['config_sha256']==original['config_sha256']
 assert library.get('baseline')==original
 assert exported['config_sha256']==digest(bundle)


def test_generation_cli_named_recipe_and_overrides_are_recorded(tmp_path,monkeypatch):
 from scripts import generate_website_world_execution as cli
 library=Library(tmp_path/'library');request=deepcopy(REQUEST);request['requirements']=[]
 first=library.put('cli',request,{'lazy_publication':True,'answer_grading':{'mode':'subscription-post-run'}})
 target=tmp_path/'generated';seen=[]
 def prepare(req,out,**kwargs):
  seen.append((req,kwargs));out.mkdir()
  save(out/'request.json',req)
  save(out/'execution.private.json',{'validation':kwargs['validation'],
   'runtime_options':{'lazy_publication':kwargs['lazy_publication']},'answer_grading':kwargs['answer_grading']})
  return {'world_id':'offline','summary':{}}
 monkeypatch.setattr(cli,'prepare',prepare)
 monkeypatch.setattr(sys,'argv',['generate','--recipe','cli@1','--library',str(library.root),
  '--output',str(target),'--no-lazy-publication','--answer-grading','off'])
 cli.main()
 assert seen==[(request,{'validation':'off','answer_grading':None,'lazy_publication':False})]
 assert library.get('cli@1')==first and library.get('cli')['version']==2
 assert library.get('cli')['config']['execution']['answer_grading']=={'mode':'off'}


def test_human_report_uses_real_tables_escaped_content_and_downloadable_configs(tmp_path):
 from html.parser import HTMLParser
 from environments.website_world.generation_configs import render_report
 library=Library(tmp_path/'library');request=deepcopy(REQUEST)
 request['task']['concept_id']='<img src=x onerror=alert(1)>'
 library.put('report',request,tags=['readable'])
 result=render_report(library,tmp_path/'report');text=(tmp_path/'report/index.html').read_text()
 class Parser(HTMLParser):
  def __init__(self):super().__init__();self.tables=0;self.rows=0;self.images=0
  def handle_starttag(self,tag,attrs):
   self.tables+=tag=='table';self.rows+=tag=='tr';self.images+=tag=='img'
 parser=Parser();parser.feed(text)
 assert parser.tables==1 and parser.rows==2 and parser.images==0
 assert '&lt;img' in text and result['configs']==1
 assert unpack(json.loads((tmp_path/'report/report--1.json').read_text()))['request']==request
