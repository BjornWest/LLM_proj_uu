import json
from pathlib import Path
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'common_agent_util'))
from agent_trace.collections import CollectionStore
from scripts.trace_hub import Hub
from intent_browser.trace import Trace


def make_run(root,name,collection=None):
    path=root/name;path.mkdir(parents=True)
    metadata={'browsergym_version':'fixture'}
    if collection is not None:metadata['collection']=collection
    (path/'metadata.json').write_text(json.dumps(metadata))
    return path


def test_declared_folder_root_fallback_and_assignment_priority(tmp_path,monkeypatch):
    root=tmp_path/'runs';run=make_run(root,'parent','Integration/checkout')
    child=make_run(run/'children','child');other=make_run(root,'other')
    registry=tmp_path/'sources.json';registry.write_text(json.dumps({'project_root':str(tmp_path),'roots':[str(root)],'collection_roots':{str(root):'Historical'}}))
    hub=Hub(registry);rows=json.loads(hub.snapshot()[0]);by_id={row['id']:row for row in rows}
    assert sorted(row['viewer_collection'] for row in rows)==['Historical','Integration/checkout','Integration/checkout']
    parent=next(row['id'] for row in rows if row.get('collection'))
    assert by_id[parent]['recording_locations']==[str(run.resolve())+'/']
    assert by_id[parent]['summary_pending']
    before=hub.load(hub.lookup(parent))
    assert json.loads(before[0])['recording_locations']==[str(run.resolve())+'/']
    store=hub.collections
    store.update(dict(action='move',path='RL/experiment',episode_ids=[parent]),store.index()['revision'],set(by_id))
    store.update(dict(action='tag_add',tags=['reviewed'],episode_ids=[parent]),store.index()['revision'],set(by_id))
    monkeypatch.setattr(hub,'project',lambda *a:pytest.fail('Folder/tag edit reprojected trace'))
    rows=json.loads(hub.snapshot()[0])
    assert sum(row['viewer_collection']=='RL/experiment' for row in rows)==2
    assert sum('reviewed' in row['viewer_tags'] for row in rows)==1
    assert hub.load(hub.lookup(parent))==before
    assert json.loads((run/'metadata.json').read_text())['collection']=='Integration/checkout'
    assert len(json.loads(Hub(registry).snapshot()[0]))==3


def test_metadata_declaration_normalized_without_changing_output(tmp_path,monkeypatch):
    monkeypatch.setattr('intent_browser.trace.runtime_provenance',lambda:{})
    trace=Trace(tmp_path,{'collection':' RL / run 1 '})
    assert trace.directory.parent==tmp_path
    assert trace.metadata['collection']=='RL/run 1'
    child=Trace(trace.directory/'children',{})
    assert child.metadata['collection']=='RL/run 1'
    child.finish({});trace.finish({})


@pytest.mark.parametrize('collection',['../escape','/absolute','bad//name'])
def test_bad_declaration_rejected_before_trace_created(tmp_path,collection):
    with pytest.raises(ValueError):Trace(tmp_path,{'collection':collection})
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize('driver',['scripted_validation','smoke','privileged-scripted'])
def test_scripted_recordings_default_tag_and_preserve_caller(tmp_path,monkeypatch,driver):
    monkeypatch.setattr('intent_browser.trace.runtime_provenance',lambda:{})
    metadata={'driver':driver,'tags':[' integration ','custom']}
    trace=Trace(tmp_path,metadata)
    assert trace.metadata['tags']==['custom','integration','scripted']
    assert metadata=={'driver':driver,'tags':[' integration ','custom']}
    trace.finish({})
    assert json.loads((trace.directory/'metadata.json').read_text())['tags']==trace.metadata['tags']


def test_model_recording_is_not_scripted_just_because_python_launched_it(tmp_path,monkeypatch):
    monkeypatch.setattr('intent_browser.trace.runtime_provenance',lambda:{})
    trace=Trace(tmp_path,{'driver':'llm','model':'example','tags':[' integration ']})
    assert trace.metadata['tags']==['integration']
    trace.finish({})


@pytest.mark.parametrize('tags',[None,[''],['a,b'],['x'*65]])
def test_bad_tags_rejected_before_trace_created(tmp_path,tags):
    with pytest.raises(ValueError):Trace(tmp_path,{'tags':tags})
    assert not list(tmp_path.iterdir())


def test_scripted_default_in_lazy_hub_catalog_and_persistent_removal(tmp_path,monkeypatch):
    run=make_run(tmp_path/'runs','scripted')
    metadata={'browsergym_version':'fixture','driver':'scripted_validation','tags':['integration']}
    (run/'metadata.json').write_text(json.dumps(metadata))
    registry=tmp_path/'sources.json';registry.write_text(json.dumps({'project_root':str(tmp_path),'roots':[str(run.parent)]}))
    hub=Hub(registry);row=json.loads(hub.snapshot()[0])[0];ident=row['id']
    assert row['summary_pending'] and row['viewer_tags']==['integration','scripted']
    body=hub.load(hub.lookup(ident))
    assert json.loads(hub.snapshot()[0])[0]['viewer_tags']==['integration','scripted']
    hub.collections.update(dict(action='tag_remove',tags=['scripted'],episode_ids=[ident]),hub.collections.index()['revision'],{ident})
    monkeypatch.setattr(hub,'project',lambda *a:pytest.fail('Tag removal reprojected trace'))
    assert json.loads(hub.snapshot()[0])[0]['viewer_tags']==['integration']
    assert hub.load(hub.lookup(ident))==body
    assert json.loads((run/'metadata.json').read_text())==metadata
