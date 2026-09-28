"""Nine independent native cases: consent design × review layout; no model calls."""
import argparse,hashlib,json,traceback
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor


def run(spec):
    design,layout,root=spec
    from environments.product_review_sites.runtime import Runtime
    from environments.site_consent.runtime import PURPOSES
    from browsergym.core.env import BrowserEnv
    from browsergym.core.task import OpenEndedTask
    from scripts.inspect_retail_ax import capture
    public=json.loads(Path('.local/product-review-sites/preview-v4/reviews.json').read_text())['public']
    out=Path(root)/(design+'-'+layout);out.mkdir()
    report={'design':design,'layout':layout,'checks':[],'model_calls':0}
    with Runtime(public,families=['footwear'],layout=layout,consent_design=design) as rt:
        env=BrowserEnv(task_entrypoint=OpenEndedTask,task_kwargs={'start_url':rt.origin+'/reviews/footwear-model-0001','goal':'Scripted consent validation'},headless=True,viewport={'width':1440,'height':1000},slow_mo=0,timeout=10000)
        try:
            env.reset();page=env.unwrapped.page;page.wait_for_selector('#consent-ui:visible');errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            capture(env,out,'initial')
            panel=page.locator('#consent-ui');snapshot=rt.consent.snapshot();sid=next(iter(snapshot['sessions']))
            assert snapshot['sessions'][sid]['choice'] is None
            if design!='bottom-banner':
                page.keyboard.press('Escape');assert panel.is_visible()
                assert page.locator('#consent-ui').evaluate('(e)=>e.matches(":modal")')
            else:assert page.get_by_role('heading',name='Aster Stride 0001 review',exact=True).is_visible()
            page.get_by_role('button',name='Manage preferences',exact=True).click()
            if design=='side-drawer':
                for summary in page.locator('#consent-preferences summary').all():summary.click()
            capture(env,out,'preferences')
            page.locator('input[name=analytics]').check()
            page.get_by_role('button',name='Save my preferences',exact=True).click();panel.wait_for(state='hidden')
            state=rt.consent.snapshot()['sessions'][sid];assert state['preferences']=={'analytics':True,'personalisation':False,'marketing':False}
            page.reload();page.wait_for_load_state();assert not panel.is_visible()
            page.goto(rt.origin+'/catalog');assert not panel.is_visible()
            page.get_by_role('button',name='Cookie settings',exact=True).click()
            if design=='side-drawer':page.locator('#consent-preferences summary').first.click()
            assert page.locator('input[name=analytics]').is_checked()
            page.get_by_role('button',name='Close settings without changes',exact=True).click();panel.wait_for(state='hidden')
            assert len(rt.consent.snapshot()['sessions'][sid]['events'])==1
            report['checks']+=['initial_undecided','modal_escape_no_implicit_consent','custom_choices','reload_navigation_persistence','reopen_cancel_no_write']
            page.get_by_role('button',name='Cookie settings',exact=True).click()
            page.get_by_role('button',name='Accept all cookies',exact=True).click();panel.wait_for(state='hidden')
            assert all(rt.consent.snapshot()['sessions'][sid]['preferences'].values())
            page.get_by_role('button',name='Cookie settings',exact=True).click()
            label='Reject optional cookies' if design=='side-drawer' else 'Use necessary cookies only'
            page.get_by_role('button',name=label,exact=True).click();panel.wait_for(state='hidden')
            assert not any(rt.consent.snapshot()['sessions'][sid]['preferences'].values())
            # A transport failure must leave the UI open and the last choice intact.
            page.get_by_role('button',name='Cookie settings',exact=True).click()
            page.route('**/_consent/choose',lambda route:route.abort())
            page.get_by_role('button',name='Accept all cookies',exact=True).click()
            page.locator('#consent-error').filter(has_text='fetch').wait_for()
            assert panel.is_visible() and not any(rt.consent.snapshot()['sessions'][sid]['preferences'].values())
            page.unroute('**/_consent/choose')
            page.get_by_role('button',name='Close settings without changes',exact=True).click()
            report['checks']+=['accept_all','revoke_optional','transport_failure_no_commit']
            # New tabs share this site's session. Independent browser contexts do not.
            tab=page.context.new_page();tab.goto(rt.origin);assert not tab.locator('#consent-ui').is_visible();tab.close()
            ctx=page.context.browser.new_context();other=ctx.new_page();other.goto(rt.origin);other.wait_for_selector('#consent-ui:visible');ctx.close()
            assert len(rt.consent.snapshot()['sessions'])==2
            report['checks']+=['same_context_tab_persistence','fresh_context_isolation']
            if design=='bottom-banner' and layout=='lab-directory':
                with Runtime(public,families=['footwear'],consent_design='center-modal') as other_rt:
                    tab=page.context.new_page();tab.goto(other_rt.origin);tab.wait_for_selector('#consent-ui:visible');assert next(iter(other_rt.consent.snapshot()['sessions'].values()))['choice'] is None;tab.close()
                report['checks'].append('same_host_different_port_site_isolation')
            page.set_viewport_size({'width':390,'height':844});page.get_by_role('button',name='Cookie settings',exact=True).click()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            page.screenshot(path=str(out/'mobile.png'))
            assert not errors,errors
            report['checks']+=['mobile_width','no_js_errors'];report['passed']=True
        except Exception:
            report['passed']=False;report['error']=traceback.format_exc()
            try:env.unwrapped.page.screenshot(path=str(out/'failure.png'))
            except Exception:pass
        finally:
            report['consent']=rt.consent.snapshot();env.close()
    report['artifacts']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()}
    (out/'report.json').write_text(json.dumps(report,indent=2))
    return {k:report.get(k) for k in ('design','layout','passed','checks','error')}


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    from environments.site_consent.runtime import DESIGNS
    from environments.product_review_sites.data import LAYOUTS
    paths=[Path(__file__),*Path('environments/site_consent').glob('*.py'),*Path('environments/site_consent').glob('*.js'),*Path('environments/site_consent').glob('*.css'),*Path('environments/product_review_sites').glob('*.py')]
    sources={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    with ProcessPoolExecutor(max_workers=2) as pool:cases=list(pool.map(run,[(d,l,str(a.output)) for d in DESIGNS for l in LAYOUTS]))
    result={'schema':'review-consent-browser-v1','sources':sources,'cases':cases,'model_calls':0,'public_source':'.local/product-review-sites/preview-v4/reviews.json'}
    (a.output/'suite.json').write_text(json.dumps(result,indent=2));print(json.dumps(cases,indent=2))
    if not all(c['passed'] for c in cases):raise SystemExit(1)


if __name__=='__main__':main()
