"""Six isolated native discovery/read/source-link journeys; no model calls."""
import argparse,hashlib,json,re
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor


def check(args):
    family,root,out=args
    from browsergym.core.env import BrowserEnv
    from browsergym.core.task import OpenEndedTask
    from scripts.inspect_retail_ax import capture
    root=Path(root);out=Path(out)/family;out.mkdir()
    m=json.loads((root/'manifest.json').read_text());corpus=json.loads((root/'product-review-evidence.private.json').read_text())['public']
    # Family is established by the frozen model identity, not an inferred sentiment.
    rows=[r for r in corpus['reviews'] if r['article_id'].startswith(family+'-model-')]
    first=rows[0];rows=[r for r in rows if r['article_id']==first['article_id']]
    env=BrowserEnv(task_entrypoint=OpenEndedTask,task_kwargs={'start_url':m['index_url'],'goal':'Scripted exact-option review discovery'},headless=True,viewport={'width':1440,'height':1000},timeout=10000)
    try:
        env.reset();page=env.unwrapped.page
        page.get_by_role('searchbox',name='Search sites and products',exact=True).fill(first['subject']['id'])
        page.get_by_role('combobox',name='Site type',exact=True).select_option('product_reviews')
        page.get_by_role('button',name='Search',exact=True).click()
        page.locator('main article h3 a').filter(has_text='Reader Panel').first.click()
        page.get_by_role('button',name='Manage preferences',exact=True).click()
        page.get_by_role('button',name=re.compile('^(Use necessary cookies only|Reject optional cookies)$')).click();page.locator('#consent-ui').wait_for(state='hidden')
        panel=page.locator('#reader-panel')
        assert panel.is_visible()
        for shortcut in ('First-hand use','Second-hand account; not tried','Considering this use; not tried','experience_kind','actual_use'):
            assert shortcut not in panel.inner_text()
        assert panel.locator('.panel-report-body').all_text_contents()==[r['body'] for r in rows]
        for r in rows:
            report=page.locator('[id="'+r['review_id']+'"]')
            assert report.get_by_role('link',name='Permanent link to this report').get_attribute('href')=='/reviews/'+r['article_id']+'#'+r['review_id']
        panel.scroll_into_view_if_needed();metrics=capture(env,out,'panel')
        from intent_browser.ax_context import AXContext
        from intent_browser.standard_profile import standard_profile
        context=AXContext(standard_profile(helpers=False,data_tools=False).ax_config)
        context.capture(env.unwrapped._get_obs());reads=[]
        for r in rows:
            node=next(i for i,n in enumerate(context.nodes) if n['role']=='StaticText' and n['name']==r['body'])
            offset=0;parts=[];responses=[]
            while True:
                response=context.read(context.ref(node),view='node',text_offset=offset,verbose=False,repeat=True)
                responses.append(response);parts.append(response['text'])
                offset=response['next_text_offset']
                if offset is None:break
            assert json.loads(''.join(parts))['name']==r['body']
            reads.append({'review_id':r['review_id'],'responses':responses})
        (out/'scoped-reads.json').write_text(json.dumps(reads,ensure_ascii=False,indent=2))
        target=rows[-1];page.locator('[id="'+target['review_id']+'"]').get_by_role('link',name='Permanent link to this report').click()
        assert page.url.endswith('#'+target['review_id'])
        page.reload();assert page.locator('[id="'+target['review_id']+'"]').is_visible()
        page.get_by_role('link',name='Browse exact-option reader experiences').click();assert page.get_by_role('heading',name='Reader Panel',exact=True).is_visible()
        report={'passed':True,'family':family,'reports_verified':len(rows),'source_url':next(s['origin'] for s in m['sites'] if s['site_id']=='reviews-'+family)+'/reviews/'+first['article_id'],'ax_nodes':metrics['semantic_nodes'],'model_calls':0}
        (out/'report.json').write_text(json.dumps(report,indent=2));return report
    except Exception as exc:
        (out/'error.json').write_text(json.dumps({'passed':False,'family':family,'error':str(exc),'exception_type':type(exc).__name__,'url':env.unwrapped.page.url},indent=2))
        try:capture(env,out,'error')
        except Exception:pass
        raise
    finally:env.close()


def main():
    p=argparse.ArgumentParser();p.add_argument('--runtime',required=True,type=Path);p.add_argument('--output',required=True,type=Path);p.add_argument('--family',action='append',choices=['footwear','laptops','cat_food','dog_food','beer','wine']);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
    files=list(Path('environments/connected_shopping').glob('*.py'))+list(Path('environments/product_review_sites').glob('*.py'))
    sources={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    sources[__file__]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    with ProcessPoolExecutor(max_workers=2) as pool:rows=list(pool.map(check,[(f,str(a.runtime),str(a.output)) for f in (a.family or ['footwear','laptops','cat_food','dog_food','beer','wine'])]))
    assert all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in sources.items())
    report={'passed':all(r['passed'] for r in rows),'cases':rows,'sources':sources,'runtime':str(a.runtime),'model_calls':0}
    (a.output/'suite.json').write_text(json.dumps(report,indent=2));print(json.dumps(rows))


if __name__=='__main__':main()
