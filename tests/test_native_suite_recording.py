"""Optional suite callback controls: no providers, worlds or browser startup."""
from copy import deepcopy
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from training.browser_training import native_suite_recording as recording


def profile():
    return SimpleNamespace(ax_config=SimpleNamespace(incremental=True),
        delivery_tracking=True,tools=SimpleNamespace(),agent_limits=None)


def runner(calls, error=None):
    def run(factory, backend, metadata, *, record_fact_provenance=False,
            fact_source_provider=None, fact_capture_observer=None, **options):
        calls.append((factory, backend, metadata, record_fact_provenance,
                      fact_source_provider, fact_capture_observer, options))
        if error:
            raise error
        return 'original result'
    return run


def test_disabled_returns_original_without_reading_or_installing():
    original = runner([])
    with patch.object(recording, 'package_pins', side_effect=AssertionError), \
         patch.object(recording, 'NativeSuiteProvider', side_effect=AssertionError):
        assert recording.recording_runner(original) is original
    with pytest.raises(TypeError):recording.recording_runner(original, enabled=1)


def test_enabled_keeps_task_grading_profile_and_once_only_dispatch(tmp_path):
    calls=[]; native=runner(calls); factory=object(); task=object(); grade=object()
    metadata={'tags':['scripted','integration'], 'native_task_id':'same'}
    options={'automatic_grading':grade,'episode_task':task,'harness_profile':profile(),
             'observation_pipeline':'native','output':tmp_path}
    before=deepcopy(metadata)
    with patch.object(recording, 'recording_env_factory', return_value='wrapped') as install:
        hook=recording.recording_runner(native,enabled=True,expected_sources=recording.package_pins(),
            report=tmp_path/'status.json')
        assert hook(factory,'backend',metadata,**options)=='original result'
        assert install.call_args.args[0].make_env is factory
    assert len(calls)==1 and metadata==before
    call=calls[0]
    assert call[0]=='wrapped' and call[1]=='backend' and call[3] is True
    assert call[6]['automatic_grading'] is grade and call[6]['episode_task'] is task
    assert call[6]['harness_profile'] is options['harness_profile']
    assert call[6]['observation_pipeline'] is None
    assert call[5]==call[4].observe
    assert json.loads((tmp_path/'status.json').read_text())['enabled'] is True
    with pytest.raises(ValueError,match='single-episode'):hook(factory,'backend',metadata)


@pytest.mark.parametrize('options', [{},{'fact_source_provider':'existing'}])
def test_rejected_optional_setup_calls_unchanged_runner_once(tmp_path, options):
    calls=[];factory=object();metadata={'tags':['scripted']}
    hook=recording.recording_runner(runner(calls),enabled=True,
        expected_sources={'foreign':'hash'},report=tmp_path/'status.json')
    assert hook(factory,'backend',metadata,**options)=='original result'
    assert len(calls)==1 and calls[0][0] is factory and calls[0][2] is metadata
    assert json.loads((tmp_path/'status.json').read_text())['enabled'] is False


def test_runner_failure_is_not_retried_or_replaced_by_report_error(tmp_path):
    calls=[];primary=RuntimeError('original failure')
    hook=recording.recording_runner(runner(calls,primary),enabled=True,
        expected_sources=recording.package_pins(),report=tmp_path/'missing/status.json')
    with patch.object(recording,'recording_env_factory',return_value='wrapped'):
        with pytest.raises(RuntimeError) as failure:hook(object(),'backend',{})
    assert failure.value is primary and len(calls)==1
    assert hook.recording_status['report_error']=='FileNotFoundError'


def test_probe_and_install_failure_preserve_original_capture_once():
    p=recording.NativeSuiteProvider(enabled=True)
    p.page=SimpleNamespace(url='https://shop.test/',
        evaluate=lambda *a:(_ for _ in ()).throw(ValueError('missing public fields')))
    calls=[];obs={}
    assert p.observe(lambda:(calls.append(1) or obs)) is obs
    assert calls==[1] and p.result(obs) is None
    assert 'missing public fields' in p.failures[0]['detail']
    p.page.context=SimpleNamespace(new_cdp_session=lambda *_:(_ for _ in ()).throw(RuntimeError('CDP unavailable')))
    p.install()
    assert p.enabled is False
    assert p.observe(lambda:obs) is obs


def test_native_probe_does_not_invoke_async_producer_refresh():
    js=(recording.ASSETS/'native_fact_probe.js').read_text()
    assert 'quotes.quote(structuredClone(draft.cart),structuredClone(draft)' in js
    # Explicitly no producer fetch/refresh/ensure call; names in comments are harmless.
    import re
    assert not re.search(r'(?:fetch|ensureProduct|ensureQuote|refresh)\s*\(',js)


@pytest.mark.parametrize('changed',[{}, {'ax_config':None}, {'delivery_tracking':False},
    {'tools':SimpleNamespace(human_handover_tools=True)}, {'agent_limits':{'workers':1}}])
def test_unsupported_profile_falls_back_without_changing_native_options(changed):
    calls=[];p=profile();p.__dict__.update(changed)
    if not changed:p=None
    factory=object();metadata={};options={'harness_profile':p,'observation_pipeline':'native'}
    hook=recording.recording_runner(runner(calls),enabled=True,expected_sources=recording.package_pins())
    assert hook(factory,'backend',metadata,**options)=='original result'
    assert len(calls)==1 and calls[0][0] is factory and calls[0][2] is metadata
    assert calls[0][3] is False and calls[0][6]==options
    assert hook.recording_status['enabled'] is False


@pytest.mark.parametrize('extra',[{'checkpoint_control':object()}, {'agent_runtime':object()},
    {'observation_pipeline':object()}])
def test_unqualified_capture_mode_preserves_original_runner(extra):
    calls=[];factory=object();metadata={};options={'harness_profile':profile(),**extra}
    hook=recording.recording_runner(runner(calls),enabled=True,expected_sources=recording.package_pins())
    assert hook(factory,'backend',metadata,**options)=='original result'
    assert len(calls)==1 and calls[0][0] is factory and calls[0][3] is False


def test_nonclass_entrypoint_returns_original_env_without_close_or_retry():
    calls=[];env=SimpleNamespace(task_entrypoint=lambda:None,close=lambda:calls.append('close'))
    p=recording.NativeSuiteProvider(enabled=True)
    original=lambda video:(calls.append(video) or env)
    factory=recording.recording_env_factory(SimpleNamespace(make_env=original),p)
    assert factory('video') is env and calls==['video'] and p.enabled is False
    assert 'not a class' in p.failures[0]['detail']


def test_native_install_has_no_page_global_and_uses_pinned_attestation():
    calls=[];p=recording.NativeSuiteProvider(enabled=True)
    p.page=SimpleNamespace(context=SimpleNamespace(new_cdp_session=lambda page:(calls.append(page) or 'cdp')))
    p.install()
    assert calls==[p.page] and p.cdp=='cdp' and p.enabled is True
    assert 'function renderAttestation(root)' in p.attestation_function


def test_exact_asset_read_bytes_are_checked():
    pins=recording.package_pins()
    pins[str((recording.ASSETS/'native_fact_probe.js').resolve())]='0'*64
    with pytest.raises(ValueError,match='evaluated inspection asset'):
        recording.NativeSuiteProvider(enabled=True,expected_sources=pins)


def test_positional_native_options_supported_once():
    calls=[]
    def native(factory,backend,metadata,output,max_steps,*,harness_profile,
               record_fact_provenance=False,fact_source_provider=None,fact_capture_observer=None,**kwargs):
        calls.append((factory,output,max_steps,record_fact_provenance));return 'same'
    hook=recording.recording_runner(native,enabled=True,expected_sources=recording.package_pins())
    with patch.object(recording,'recording_env_factory',return_value='wrapped'):
        assert hook(object(),'b',{},'output',5,harness_profile=profile())=='same'
    assert calls==[('wrapped','output',5,True)]



def test_probe_identity_and_selected_intervals_use_exact_producer_grammar():
    import subprocess, shutil
    if shutil.which('node') is None:pytest.skip('Node required for producer-JS controls')
    js=(recording.ASSETS/'native_fact_probe.js').read_text()
    result=subprocess.run(['node','-e',js+"""
      const id='footwear-brand-09/footwear.walking_sandals/02';
      if(nativeReviewProductId(['reviews',encodeURIComponent(id)],null)!==id)throw Error('route');
      if(nativeReviewProductId(['activity'],'/reviews/'+encodeURIComponent(id)+'?q=1')!==id)throw Error('link');
      const selected=nativeSelectedParts({options:[{key:'a',label:'Long Size'},{key:'b',label:'Size'}]},
        {selection:{a:'42',b:'2'}});
      if(selected.text!=='Selected: Long Size 42 · Size 2')throw Error('grammar');
      for(const row of selected.parts) {
        const value=row.parts.find(p=>p.part==='value');
        if(selected.text.slice(value.start,value.end)!==row.value)throw Error('interval');
      }
      const second=selected.parts[1].parts[0];
      if(selected.text.slice(second.start,second.end)!=='Size'||second.start!==25)throw Error('suffix');
    """],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr


@pytest.mark.parametrize('shape',['variadic','positional_only'])
def test_unqualified_positional_shapes_fall_back_without_losing_arguments(shape):
    calls=[]
    if shape=='variadic':
        def native(factory,backend,metadata,*rest,record_fact_provenance=False,
                   fact_source_provider=None,fact_capture_observer=None,**options):
            calls.append((rest,record_fact_provenance));return 'same'
        args=('out',5)
    else:
        def native(factory,backend,metadata,output,/,record_fact_provenance=False,
                   fact_source_provider=None,fact_capture_observer=None,**options):
            calls.append(((output,),record_fact_provenance));return 'same'
        args=('out',)
    hook=recording.recording_runner(native,enabled=True,expected_sources=recording.package_pins())
    assert hook(object(),'b',{},*args,harness_profile=profile())=='same'
    assert calls==[(args,False)] and hook.recording_status['enabled'] is False


def test_native_capture_receives_eager_attestation_without_late_asset_read():
    from training.browser_training import fact_source_provider as sources
    p=recording.NativeSuiteProvider(enabled=True);p.page=SimpleNamespace(evaluate=lambda *args:None)
    obs={'axtree_object':{'nodes':[]}};export={'revision':1}
    with patch.object(p,'_attest',return_value=export),patch.object(sources,'capture',return_value={'normalized':{}}) as capture:
        assert p.observe(lambda:obs) is obs
    assert capture.call_args.kwargs['attestation_function']==p.attestation_function


def summary_probe(*,path='/reviews/p',query='?sku=s',empty=False,mutation=None,legacy=False):
    """Execute the actual probe branch with an inert recorder and exact DOM grammar."""
    import subprocess
    script=(recording.ASSETS/'native_fact_probe.js').read_text()+r'''
      const cfg=JSON.parse(require('fs').readFileSync(0,'utf8'));
      const modelLabel=cfg.legacy?'Customer rating summary':'Model-wide customer rating summary';
      function panel(label,mean,count,outer=null) {
        const avg={textContent:mean};const p={textContent:count};
        return {label,getAttribute:()=>label,
          closest:s=>s==='section[aria-label="Option-specific rating summary"]'?outer:null,
          querySelectorAll:s=>s==='.rating-value'?[avg]:s===':scope > p'?[avg,p]:[],
          querySelector:s=>s==='.rating-value'?avg:null};
      }
      const skuLabel={textContent:'SKU: s'};
      const outer={querySelectorAll:s=>s===':scope > p'?[skuLabel]:[]};
      const model=panel(modelLabel,'3.6 / 5','100 ratings; 27 written reviews, 73 ratings without comments.');
      const option=panel('Option-specific customer rating summary',cfg.empty?'Mean rating undefined (no ratings)':'4.50 / 5',
        cfg.empty?'0 ratings; 0 written reviews, 0 ratings without comments.':'2 ratings; 0 written reviews, 2 ratings without comments.',outer);
      const link={getAttribute:()=>'/reviews/p?sku=s'};
      let panels=cfg.path.startsWith('/variants/')?[option]:[model,option];
      if(cfg.legacy)panels=[model];
      let links=[link];
      if(cfg.mutation==='missing_label')outer.querySelectorAll=()=>[];
      if(cfg.mutation==='duplicate_label')outer.querySelectorAll=()=>[skuLabel,skuLabel];
      if(cfg.mutation==='wrong_label')skuLabel.textContent='SKU: other';
      if(cfg.mutation==='unknown_panel')option.getAttribute=()=>'';
      if(cfg.mutation==='missing_link')links=[];
      if(cfg.mutation==='foreign_link')link.getAttribute=()=> 'https://other.example/reviews/p?sku=s';
      if(cfg.mutation==='wrong_link_sku')link.getAttribute=()=>'/reviews/p?sku=other';
      if(cfg.mutation==='ambiguous_product')links=[link,{getAttribute:()=>'/reviews/other?sku=s'}];
      if(cfg.mutation==='wrong_counts')option.querySelectorAll=s=>s==='.rating-value'?[{textContent:'4.50 / 5'}]:
        s===':scope > p'?[{textContent:'2 ratings; 1 written reviews, 2 ratings without comments.'}]:[];
      if(cfg.mutation==='wrong_empty')option.querySelectorAll=s=>s==='.rating-value'?[{textContent:'Mean rating undefined (no ratings)'}]:
        s===':scope > p'?[{textContent:'2 ratings; 0 written reviews, 2 ratings without comments.'}]:[];
      if(['zero_numeric','low_mean','high_mean','duplicate_mean','duplicate_counts'].includes(cfg.mutation)) {
        const mean={textContent:cfg.mutation==='low_mean'?'0.99 / 5':cfg.mutation==='high_mean'?'5.01 / 5':'4.50 / 5'};
        const count={textContent:cfg.mutation==='zero_numeric'?'0 ratings; 0 written reviews, 0 ratings without comments.':'2 ratings; 0 written reviews, 2 ratings without comments.'};
        option.querySelectorAll=s=>s==='.rating-value'?(cfg.mutation==='duplicate_mean'?[mean,mean]:[mean]):
          s===':scope > p'?(cfg.mutation==='duplicate_counts'?[count,count]:[count]):[];
      }
      const root={tagName:'MAIN',id:'main',
        querySelectorAll:s=>s==='.rating-panel'?panels:s==='a[href]'?links:[]};
      global.location={origin:'https://reviews.example',href:'https://reviews.example'+cfg.path+cfg.query,
        pathname:cfg.path,search:cfg.query};
      global.document={body:root,querySelector:s=>s==='#app'?null:s==='main'?root:panels[0]||null};
      let records=[];
      global.createFactRecorder=({sink})=>({
        occurrence:(binding,effective_state)=>({binding,effective_state}),
        adopt:(node,occurrence,content)=>records.push({occurrence,content}),
        commit:()=>sink({registrations:records,diagnostics:[]})});
      nativeFactProbe({site_id:'actual-review-site',revision:1}).then(result=>process.stdout.write(JSON.stringify(result)));
    '''
    result=subprocess.run(['node','-e',script],input=json.dumps(dict(path=path,query=query,
        empty=empty,mutation=mutation,legacy=legacy)),capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr
    return json.loads(result.stdout)


def test_actual_default_probe_distinguishes_model_and_option_values_without_relabelling():
    result=summary_probe();records=result['registrations']
    assert len(records)==8 and not result['diagnostics']
    for grain,total,written,silent,mean in [('model',100,27,73,3.6),('sku',2,0,2,4.5)]:
        group=[r for r in records if r['occurrence']['binding']['grain']==grain]
        values={r['occurrence']['binding']['field']:r['occurrence']['binding']['value'] for r in group}
        assert values==dict(rating_count=total,written_review_count=written,rating_only_count=silent,average_rating=mean)
        assert all(r['occurrence']['effective_state']['grain']==grain and
                   r['occurrence']['binding']['product_id']=='p' for r in group)
        assert all(('sku_id' in r['occurrence']['binding'])==(grain=='sku') for r in group)
    sku=next(r for r in records if r['occurrence']['binding']['grain']=='sku' and
             r['occurrence']['binding']['field']=='average_rating')
    assert sku['occurrence']['binding']['rendered_value']=='4.50'
    assert sku['occurrence']['binding']['value_basis']=='rounded_public_mean'
    assert sku['content']['parts']==[{'part':'value','start':0,'end':4},
                                     {'part':'scale','start':7,'end':8}]


def test_actual_default_probe_option_route_joins_public_review_link_instead_of_splitting_sku():
    result=summary_probe(path='/variants/s',query='')
    assert len(result['registrations'])==4 and not result['diagnostics']
    assert all(r['occurrence']['binding']['sku_id']=='s' and
               r['occurrence']['binding']['product_id']=='p' for r in result['registrations'])


def test_actual_default_probe_empty_mean_has_status_without_numeric_value_or_scale():
    result=summary_probe(path='/variants/s',query='',empty=True)
    assert len(result['registrations'])==4 and not result['diagnostics']
    avg=next(r for r in result['registrations'] if r['occurrence']['binding']['field']=='average_rating')
    assert avg['occurrence']['binding']['value'] is None
    assert avg['occurrence']['binding']['value_status']=='undefined_no_ratings'
    assert [p['part'] for p in avg['content']['parts']]==['status']
    assert all(r['occurrence']['binding']['value']==0 for r in result['registrations'] if r is not avg)


@pytest.mark.parametrize('mutation',['missing_label','duplicate_label','wrong_label','unknown_panel','wrong_counts','wrong_empty',
                                    'zero_numeric','low_mean','high_mean','duplicate_mean','duplicate_counts'])
def test_actual_default_probe_unknown_option_scope_never_falls_back_to_product(mutation):
    result=summary_probe(mutation=mutation)
    assert len(result['registrations'])==4 and result['diagnostics']
    assert all(r['occurrence']['binding']['grain']=='model' for r in result['registrations'])


@pytest.mark.parametrize('mutation',['missing_link','foreign_link','ambiguous_product','wrong_label','wrong_link_sku'])
def test_actual_default_probe_unresolved_option_route_records_diagnostic_not_guess(mutation):
    result=summary_probe(path='/variants/s',query='',mutation=mutation)
    assert not result['registrations'] and result['diagnostics']


def test_actual_default_probe_legacy_model_panel_remains_all_options_even_with_sku_query():
    result=summary_probe(legacy=True)
    assert len(result['registrations'])==4 and not result['diagnostics']
    assert all(r['occurrence']['binding']['grain']=='model' and
               r['occurrence']['binding']['basis']=='all_recorded_ratings_all_options_including_silent'
               for r in result['registrations'])


@pytest.mark.parametrize('query',['?sku=other','?sku=s&sku=s'])
def test_actual_default_probe_conflicting_or_duplicate_query_cannot_establish_sku(query):
    result=summary_probe(query=query)
    assert len(result['registrations'])==4 and result['diagnostics']


def test_actual_default_probe_variant_route_must_equal_visible_sku_label():
    result=summary_probe(path='/variants/other',query='')
    assert not result['registrations'] and result['diagnostics']


def test_actual_default_probe_collection_reports_one_unmapped_inventory_diagnostic():
    result=summary_probe(path='/search',query='')
    assert not result['registrations']
    assert result['diagnostics']==[{'reason':'native_review_collection_summaries_unmapped','panel_count':2}]
