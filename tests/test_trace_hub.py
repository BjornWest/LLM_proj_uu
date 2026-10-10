"""Cross-root viewer ordering, refresh and artifact isolation without inference."""
import hashlib,json,sys
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT.parent/'common_agent_util'))
from scripts.trace_hub import Hub,media_prefix,source_key


def episode(root,name,started,finished=None):
    p=root/name;p.mkdir(parents=True)
    (p/'metadata.json').write_text(json.dumps({'browsergym_version':'0.14.3','driver':'llm'}))
    events=[{'event':'episode_started','timestamp':started}]
    if finished:events.append({'event':'episode_finished','timestamp':finished})
    (p/'events.jsonl').write_text('\n'.join(map(json.dumps,events))+'\n')
    (p/'steps.jsonl').write_text(json.dumps({'step':0,'observation':{'text':'observation-000.txt'},'action':None})+'\n')
    (p/'observation-000.txt').write_text(name)
    return p


@pytest.fixture
def setup(tmp_path):
    a=tmp_path/'runs';b=tmp_path/'.local/real-web-first/runs'
    episode(a,'old','2026-01-01T00:00:00Z','2026-03-01T00:00:00Z')
    episode(b,'new','2026-02-01T00:00:00Z')
    config=tmp_path/'sources.json';config.write_text(json.dumps({'project_root':str(tmp_path),'roots':[str(a)],'patterns':['.local/real-web-*/runs']}))
    return Hub(config),a,b


def test_newest_start_first_even_when_old_run_updated_later(setup):
    h,a,b=setup;summary,entries=h.snapshot();rows=json.loads(summary)
    assert [r['id'] for r in rows]==[hashlib.sha256(('browsergym:'+n).encode()).hexdigest()[:20] for n in ['new','old']]
    assert len(entries)==2


def test_source_media_and_read_only_originals(setup):
    h,a,b=setup;before=(b/'new/steps.jsonl').read_bytes();summary,entries=h.snapshot()
    raw=entries[hashlib.sha256(b'browsergym:new').hexdigest()[:20]][0]
    assert ('/artifacts/'+source_key(b)+'/new/observation-000.txt').encode() in raw
    path,mime=h.asset(source_key(b)+'/new/observation-000.txt');assert path.read_text()=='new'
    assert before==(b/'new/steps.jsonl').read_bytes()


@pytest.mark.parametrize('path',['unknown/new/observation-000.txt','KEY/../secret.txt','KEY/new/../../secret.txt','KEY/new/private.txt'])
def test_artifact_escape_rejected(setup,path):
    h,a,b=setup
    with pytest.raises((ValueError,OSError)):h.asset(path.replace('KEY',source_key(b)))


def test_new_matching_root_and_episode_discovered(setup):
    h,a,b=setup;h.snapshot();new=b.parents[1]/'real-web-next/runs'
    episode(new,'newest','2026-04-01T00:00:00Z')
    summary,_=h.snapshot();assert len(json.loads(summary))==3
    assert json.loads(summary)[0]['id']==hashlib.sha256(b'browsergym:newest').hexdigest()[:20]


def test_ambiguous_ids_fail_instead_of_returning_wrong_trace(setup):
    h,a,b=setup;episode(a,'new','2026-05-01T00:00:00Z')
    with pytest.raises(ValueError,match='Duplicate trace'):h.snapshot()


def test_rewrite_only_artifact_url_fields():
    obj={'text':'/artifacts/not-media','nested':[{'url':'/artifacts/episode/image-1.png'},{'url':'https://example.org'}]}
    rewritten=media_prefix(obj,'source')
    assert obj['nested'][0]['url']=='/artifacts/episode/image-1.png'
    assert rewritten['text']==obj['text'] and rewritten['nested'][1]==obj['nested'][1]
    assert rewritten['nested'][0]['url']=='/artifacts/source/episode/image-1.png'


def trace_id(name):
    return hashlib.sha256(('browsergym:'+name).encode()).hexdigest()[:20]


def test_catalog_does_not_read_steps_or_project_messages(setup,monkeypatch):
    from agent_trace.adapters import browsergym
    h,a,b=setup
    original=Path.read_text
    def read(path,*args,**kwargs):
        assert path.name!='steps.jsonl','Catalog read a full trace'
        return original(path,*args,**kwargs)
    monkeypatch.setattr(Path,'read_text',read)
    monkeypatch.setattr(browsergym,'project',lambda *a,**kw:pytest.fail('Catalog projected a trace'))
    raw,entries=h.snapshot()
    assert len(entries)==2 and trace_id('new') in entries
    assert all(row['summary_pending'] for row in json.loads(raw))


def test_load_only_selected_trace_and_reuse_cache(setup,monkeypatch):
    from agent_trace.adapters import browsergym
    h,a,b=setup;calls=[];original=browsergym.project
    def project(directory,**kwargs):
        calls.append(directory.name)
        return original(directory,**kwargs)
    monkeypatch.setattr(browsergym,'project',project)
    _,entries=h.snapshot();first=entries[trace_id('new')]
    _,entries=h.snapshot();assert entries[trace_id('new')]==first
    assert calls==['new']
    assert h.body_bytes<=h.cache_bytes
    rows=json.loads(h.snapshot()[0])
    assert 'summary_pending' not in rows[0] and rows[0]['model_turn_count']==1
    assert rows[1]['summary_pending']


def test_other_trace_update_keeps_selected_cache(setup,monkeypatch):
    from agent_trace.adapters import browsergym
    h,a,b=setup;_,entries=h.snapshot();first=entries[trace_id('new')]
    (a/'old/evaluation.json').write_text('{"safe_success":true}')
    monkeypatch.setattr(browsergym,'project',lambda *a,**kw:pytest.fail('Unchanged trace rebuilt'))
    raw,entries=h.snapshot()
    assert entries[trace_id('new')]==first
    assert json.loads(raw)[1]['title'].endswith('safe success')


def test_selected_lookup_does_not_rescan_catalog(setup,monkeypatch):
    h,a,b=setup;h.snapshot()
    monkeypatch.setattr(h,'snapshot',lambda:pytest.fail('Selected trace rescanned catalog'))
    first=h.lookup(trace_id('new'))
    (b/'new/evaluation.json').write_text('{"safe_success":true}')
    after=h.lookup(trace_id('new'))
    assert after['revision']!=first['revision']
    assert after['summary']['title'].endswith('safe success')


def test_initial_summaries_are_cached_across_restarts(setup,monkeypatch):
    import scripts.trace_hub as module
    h,a,b=setup;before=h.snapshot()[0]
    restarted=Hub(h.registry)
    monkeypatch.setattr(module,'initial_summary',lambda *a:pytest.fail('Unchanged metadata reread'))
    assert restarted.snapshot()[0]==before


@pytest.mark.parametrize('filename',['steps.jsonl','observation-000.txt','evaluation.json'])
def test_changed_trace_invalidates_only_its_revision(setup,filename):
    h,a,b=setup;_,entries=h.snapshot();before=entries[trace_id('new')]
    path=b/'new'/filename
    if filename=='evaluation.json':path.write_text('{"safe_success":true}')
    else:path.write_text(path.read_text()+'\n')
    _,entries=h.snapshot();after=entries[trace_id('new')]
    assert after[1]!=before[1]


def test_summary_persists_max_isl_without_loading_trace_on_restart(setup,monkeypatch):
    from agent_trace.adapters import browsergym
    h,a,b=setup
    row=json.loads((b/'new/steps.jsonl').read_text())
    row['model_response']={'usage':{'prompt_tokens':12345}}
    (b/'new/steps.jsonl').write_text(json.dumps(row)+'\n')
    _,entries=h.snapshot();entries[trace_id('new')]
    restarted=Hub(h.registry)
    monkeypatch.setattr(browsergym,'project',lambda *a,**kw:pytest.fail('Restart loaded full trace'))
    summary,_=restarted.snapshot();new=json.loads(summary)[0]
    assert new['max_isl_tokens']==12345 and new['input_token_usage_count']==1
    assert 'messages' not in new and 'turns' not in new


def test_body_cache_is_bounded_and_eviction_keeps_summary(setup):
    h,a,b=setup;h.cache_bytes=1
    _,entries=h.snapshot();entries[trace_id('new')]
    assert not h.bodies and h.body_bytes==0
    assert json.loads(h.snapshot()[0])[0]['model_turn_count']==1


def test_catalog_tolerates_diagnostic_numeric_clock_values(setup):
    h,a,b=setup;path=b/'new/events.jsonl'
    path.write_text(path.read_text()+json.dumps({'event':'diagnostic','timestamp':123.4})+'\n')
    rows=json.loads(h.snapshot()[0])
    assert rows[0]['updated_at']=='2026-02-01T00:00:00Z'


def test_parallel_readers_project_same_trace_once(setup,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from agent_trace.adapters import browsergym
    import time
    h,a,b=setup;calls=[];original=browsergym.project
    def project(directory,**kwargs):
        calls.append(directory.name);time.sleep(.02)
        return original(directory,**kwargs)
    monkeypatch.setattr(browsergym,'project',project)
    _,entries=h.snapshot()
    with ThreadPoolExecutor(max_workers=3) as pool:
        results=list(pool.map(lambda _:entries[trace_id('new')],range(3)))
    assert results[0]==results[1]==results[2]
    assert calls==['new']


def test_slow_projection_does_not_block_catalog_or_other_trace(setup,monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from agent_trace.adapters import browsergym
    from threading import Event
    h,a,b=setup;started=Event();release=Event();original=browsergym.project
    def project(directory,**kwargs):
        if directory.name=='new':
            started.set();assert release.wait(5)
        return original(directory,**kwargs)
    monkeypatch.setattr(browsergym,'project',project)
    _,entries=h.snapshot()
    with ThreadPoolExecutor(max_workers=3) as pool:
        loading=pool.submit(lambda:entries[trace_id('new')])
        try:
            assert started.wait(5)
            summary,others=pool.submit(h.snapshot).result(timeout=2)
            assert len(json.loads(summary))==2
            assert pool.submit(lambda:others[trace_id('old')]).result(timeout=2)
        finally:release.set()
        loading.result(timeout=5)


def test_removed_root_not_served_from_cache(setup):
    h,a,b=setup;_,entries=h.snapshot();entries[trace_id('new')]
    h.registry.write_text(json.dumps({'project_root':str(a.parent),'roots':[str(a)]}))
    with pytest.raises(KeyError):h.lookup(trace_id('new'))
    _,entries=h.snapshot()
    assert trace_id('new') not in entries


def test_racing_write_returns_readable_snapshot_without_stable_cache(setup,monkeypatch):
    from agent_trace.adapters import browsergym
    h,a,b=setup;original=browsergym.project
    def project(directory,**kwargs):
        group=original(directory,**kwargs)
        (directory/'evaluation.json').write_text('{"safe_success":true}')
        return group
    monkeypatch.setattr(browsergym,'project',project)
    _,entries=h.snapshot()
    body,revision=entries[trace_id('new')]
    assert json.loads(body)['id']==trace_id('new')
    assert revision.startswith('live-')
    assert revision!=entries.entries[trace_id('new')]['revision']
    assert not h.bodies
    assert entries.entries[trace_id('new')]['summary']['summary_pending']
    monkeypatch.setattr(browsergym,'project',original)
    entry=h.lookup(trace_id('new'));body,settled_revision=h.load(entry)
    assert settled_revision!=revision and not settled_revision.startswith('live-')
    assert json.loads(body)['evaluation_label']=='safe success'
    assert settled_revision in h.bodies


def test_continuously_appending_trace_loads_on_every_request(setup,monkeypatch):
    from agent_trace.adapters import browsergym
    h,a,b=setup;original=browsergym.project
    def project(directory,**kwargs):
        group=original(directory,**kwargs)
        path=directory/'steps.jsonl'
        rows=[json.loads(line) for line in path.read_text().splitlines()]
        with path.open('a') as stream:stream.write(json.dumps({'step':len(rows),'action':None})+'\n')
        return group
    monkeypatch.setattr(browsergym,'project',project)
    for expected in range(1,5):
        entry=h.lookup(trace_id('new'));body,revision=h.load(entry)
        assert json.loads(body)['model_turn_count']==expected
        assert revision.startswith('live-')
        assert not h.bodies


@pytest.mark.parametrize('racing',[False,True])
def test_http_etag_skips_projection_and_gzip_roundtrips(setup,monkeypatch,racing):
    import gzip,io
    from scripts.trace_hub import make_handler
    from agent_trace.adapters import browsergym
    h,a,b=setup;handler=make_handler(h.registry)
    original=browsergym.project
    if racing:
        def project(directory,**kwargs):
            group=original(directory,**kwargs)
            (directory/'evaluation.json').write_text('{"safe_success":true}')
            return group
        monkeypatch.setattr(browsergym,'project',project)
    def get(path,headers=None):
        request=object.__new__(handler);request.path=path;request.headers=headers or {}
        request.wfile=io.BytesIO();status=[];response_headers={}
        request.send_response=status.append
        request.send_header=lambda key,value:response_headers.update({key:value})
        request.end_headers=lambda:None
        request.send_error=lambda code,*args:status.append(code)
        request.do_GET()
        return status[0],response_headers,request.wfile.getvalue()
    rows=json.loads(get('/api/sessions')[2]);ident=trace_id('new')
    status,headers,body=get('/api/sessions/'+ident,{'Accept-Encoding':'gzip'})
    assert status==200 and headers['Content-Encoding']=='gzip'
    assert json.loads(gzip.decompress(body))['id']==ident
    if racing:
        assert headers['ETag'].startswith('"live-')
        assert headers['Cache-Control']=='no-store'
        monkeypatch.setattr(browsergym,'project',original)
        # A live snapshot must never suppress delivery of the newer stable data.
        status,new_headers,body=get('/api/sessions/'+ident,{'If-None-Match':headers['ETag']})
        assert status==200
        assert json.loads(body)['evaluation_label']=='safe success'
        headers=new_headers
    else:
        assert headers['ETag']=='"'+rows[0]['revision']+'"'
    monkeypatch.setattr(browsergym,'project',lambda *a,**kw:pytest.fail('ETag revalidation projected trace'))
    status,_,body=get('/api/sessions/'+ident,{'If-None-Match':headers['ETag']})
    assert status==304 and body==b''
    assert get('/api/sessions/missing')[0]==404


def test_hub_client_preserves_renderer_and_scroll_behavior():
    from scripts.trace_hub import viewer_html
    html=viewer_html().decode()
    assert 'async function refresh({background=false,navigate=false}={})' in html
    assert 'if(background&&traceRequest)return' in html
    assert 'if(follow)scrollTraceToBottom();else restoreTracePosition(anchor)' in html
    assert 'Max ISL: load trace to view' in html
    assert 'Open trace to load totals' in html


@pytest.mark.parametrize('reason',['max_steps','max_input_tokens','interrupted','user_close'])
def test_lazy_stop_reason_matches_full_trace_without_loading_steps(setup,monkeypatch,reason):
    from agent_trace.adapters import browsergym
    h,a,b=setup
    (b/'new/episode.json').write_text(json.dumps({'stop_reason':reason,'max_steps':24,'max_input_tokens':32000}))
    with monkeypatch.context() as scoped:
        scoped.setattr(h,'project',lambda *args:pytest.fail('Catalog projected full trace'))
        rows=json.loads(h.snapshot()[0])
    row=next(r for r in rows if r['id']==trace_id('new'))
    assert row['summary_pending']
    assert row['episode_end']==dict(reason=reason,source='episode.json',max_steps=24,max_input_tokens=32000)
    body,_=h.load(h.lookup(row['id']))
    assert json.loads(body)['episode_end']==row['episode_end']


def test_lazy_stop_reason_appears_on_completion_without_stale_counters_overwriting_it(setup):
    h,a,b=setup;h.snapshot();h.load(h.lookup(trace_id('new')))
    (b/'new/episode.json').write_text(json.dumps({'stop_reason':'max_steps','max_steps':1}))
    row=next(r for r in json.loads(h.snapshot()[0]) if r['id']==trace_id('new'))
    assert row['summary_stale'] and row['episode_end']['reason']=='max_steps'
