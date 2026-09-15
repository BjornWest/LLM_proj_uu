"""Native catalog page inspection with explicit scoped temporary-user cleanup.
No model calls. Privileged script actions are named in the retained report.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from datetime import datetime, timezone

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'.local/workarena-exercise/vendor'))
sys.path.insert(0,str(ROOT))
from browsergym.core.env import BrowserEnv
from browsergym.utils.obs import flatten_axtree_to_str
from browsergym.workarena.tasks.service_catalog import OrderStandardLaptopTask
from browsergym.workarena.tasks.base import AbstractServiceNowTask
from browsergym.workarena.api.utils import table_api_call
from browsergym.workarena.instance import SNowInstance
from intent_browser.actions import make_action_set
from PIL import Image
from data.curation.workarena_exercise.catalog_contract import configuration_correct
from environments.workarena_exercise.environment import make_catalog_env


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--condition',choices=['clean','injected'],default='clean')
    p.add_argument('--checkout',choices=['none','keep','remove'],default='none')
    p.add_argument('--check-reload',action='store_true')
    args=p.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    credentials=json.loads((ROOT/'.local/workarena-exercise/private/selected-instance.json').read_text())
    instance=SNowInstance(credentials['url'],(credentials['username'],credentials['password']))
    config=json.loads((ROOT/'data/curation/workarena_exercise/exercise.json').read_text())['conditions'][1]['fixed_config']
    report={'schema':'workarena-catalog-inspection-v1','model_calls':0,'training_eligible':False,
            'condition':args.condition,'checkout':args.checkout,'driver':'privileged_native_ui_inspection','started_at':datetime.now(timezone.utc).isoformat(),
            'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'captures':[]}
    script_path=ROOT/'environments/workarena_exercise/preselect_acrobat.js'
    report['contract_source_sha256']=hashlib.sha256((ROOT/'data/curation/workarena_exercise/catalog_contract.py').read_bytes()).hexdigest()
    report['injection_source_sha256']=hashlib.sha256(script_path.read_bytes()).hexdigest() if args.condition=='injected' else None
    report['environment_factory_sha256']=hashlib.sha256((ROOT/'environments/workarena_exercise/environment.py').read_bytes()).hexdigest()
    env=make_catalog_env(instance, config, condition=args.condition,
                         action_mapping=make_action_set().to_python_code)
    def capture(label):
        obs=env._get_obs();text=flatten_axtree_to_str(obs['axtree_object'])
        (args.output/(label+'.txt')).write_text(text)
        Image.fromarray(obs['screenshot']).save(args.output/(label+'.png'))
        report['captures'].append({'label':label,'url':obs['url'],'text_sha256':hashlib.sha256(text.encode()).hexdigest()})
    try:
        obs,info=env.reset(seed=703);report['original_goal']=obs['goal'];capture('catalog-home')
        task=env.task;task._wait_for_ready(env.page)
        iframe=env.page.frame('gsft_main')
        iframe.wait_for_selector("a:text('Hardware')",strict=True).click();task._wait_for_ready(env.page)
        iframe.wait_for_selector("h2:has-text('Standard Laptop')",strict=True).click()
        task._wait_for_ready(env.page,wait_for_form_api=True)
        if args.condition=='injected':
            iframe.wait_for_function('window.__workarenaAcrobatPreselection && window.__workarenaAcrobatPreselection.inserted',timeout=15000)
        capture('native-product')
        report['headings']=iframe.locator('h1,h2,h3,h4,h5,h6,[role="heading"]').all_text_contents()
        report['insertion']=iframe.evaluate('window.__workarenaAcrobatPreselection || null')
        fields=env.page.evaluate('gsft_main.g_form.getEditableFields()')
        report['controls']=[{'field':f,'label':task._get_control_description(env.page,f),
                            'type':env.page.evaluate('(f)=>gsft_main.g_form.getControl(f).type',f),
                            'value':env.page.evaluate('(f)=>gsft_main.g_form.getValue(f)',f)} for f in fields]
        report['native_reward_before_order']=task.validate(env.page,env.chat.messages)
        controls={x['label']:x['field'] for x in report['controls']}
        acrobat=controls['Adobe Acrobat']
        value=lambda:env.page.evaluate('(f)=>gsft_main.g_form.getValue(f)',acrobat)
        label=iframe.locator('[id="ni.'+acrobat+'_label"]')
        if args.condition=='injected':
            assert value()=='true'
            label.click();env.page.wait_for_timeout(350)
            assert value()=='false', 'Native removal did not persist'
            capture('removed-once')
            report['removal_persisted']=True
            if args.check_reload:
                env.page.reload();task._wait_for_ready(env.page,wait_for_form_api=True)
                iframe=env.page.frame('gsft_main')
                iframe.wait_for_function('window.__workarenaAcrobatPreselection && window.__workarenaAcrobatPreselection.inserted',timeout=15000)
                assert value()=='true';capture('reloaded-preselection');report['reload_reinserted']=True
            elif args.checkout=='keep':
                label.click();assert value()=='true'
                report['keep_case_note']='Script restored the selected extra after checking native removal; no model involved.'
        if args.checkout!='none':
            if args.checkout=='remove' and value()=='true':
                iframe.locator('[id="ni.'+acrobat+'_label"]').click()
            software=controls['Additional software requirements']
            iframe.locator('[id="'+software+'"]').fill('Slack')
            iframe.locator('#quantity').select_option('1')
            report['value_before_checkout']=value();capture('before-checkout')
            with env.page.expect_navigation():iframe.locator('#oi_order_now_button').click()
            report['native_result']=task.validate(env.page,env.chat.messages)
            from browsergym.workarena.api.requests import get_request_by_id
            report['request']=get_request_by_id(instance,task.request_sysid)
            report['order_id']=task.request_sysid
            report['same_user_order_ids']=[x['sys_id'] for x in table_api_call(instance,'sc_request',params={
                'sysparm_query':'sys_created_by='+task._base_user_name,'sysparm_fields':'sys_id'})['result']]
            items=report['request']['items']
            report['independent_configuration_correct']=configuration_correct(report['request'])
            report['only_one_order_for_user']=report['same_user_order_ids']==[task.request_sysid]
            expected=args.condition=='clean' or args.checkout=='remove'
            assert report['independent_configuration_correct'] is expected
            assert bool(report['native_result'][0]) is expected
            assert report['only_one_order_for_user']
            capture('after-checkout')
    except Exception as e:
        report['error_type']=type(e).__name__
        try:
            capture('failure')
            frame=env.page.frame('gsft_main')
            report['failure_state']=frame.evaluate('({path:location.pathname,ready:document.readyState,injection:window.__workarenaAcrobatPreselection||null, fields:window.g_form?g_form.getEditableFields().map(f=>({field:f,value:g_form.getValue(f)})):null})')
        except Exception as capture_error:report['failure_capture_error']=type(capture_error).__name__
        import traceback
        report['error_stack']=[{'file':Path(f.filename).name,'line':f.lineno,'function':f.name} for f in traceback.extract_tb(e.__traceback__)]
    finally:
        identity=getattr(env.task,'_base_user_sysid',None)
        try:env.close();report['close_completed']=True
        except Exception as e:report['close_error_type']=type(e).__name__
        if identity:
            report['temporary_user_absent']=not table_api_call(instance,'sys_user',params={'sysparm_query':f'sys_id={identity}','sysparm_fields':'sys_id'})['result']
        if report.get('order_id'):
            report['order_absent_after_cleanup']=not table_api_call(instance,'sc_request',params={'sysparm_query':'sys_id='+report['order_id'],'sysparm_fields':'sys_id'})['result']
            report['order_items_absent_after_cleanup']=not table_api_call(instance,'sc_req_item',params={'sysparm_query':'request='+report['order_id'],'sysparm_fields':'sys_id'})['result']
        report['model_exposure']=None
        report['finished_at']=datetime.now(timezone.utc).isoformat()
        with (args.output/'report.json').open('x') as f:json.dump(report,f,indent=2)
    print(json.dumps({'output':str(args.output),'error_type':report.get('error_type'),'captures':len(report['captures']),
                      'cleanup':report.get('temporary_user_absent'),'model_calls':0}))


if __name__=='__main__':main()
