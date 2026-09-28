"""Read-only real/local retailer AX study. No inference, accounts or purchases."""
import argparse
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import statistics
import time
import traceback


def save(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2))


def capture(env, out, name):
    from intent_browser.ax_context import AXContext
    from intent_browser.standard_profile import standard_profile
    start=time.monotonic();obs=env.unwrapped._get_obs();elapsed=time.monotonic()-start
    context=AXContext(standard_profile(helpers=False,data_tools=False).ax_config)
    context.capture(obs)
    # Full projection is an audit reconstruction, not a single budgeted response.
    projected=[context._project(context.ref(i),False) for i in range(len(context.nodes))]
    nodes=context.nodes;depths=[]
    for n in nodes:
        d=0;parent=n['parent']
        while parent is not None:d+=1;parent=nodes[parent]['parent']
        depths.append(d)
    roles=Counter(n['role'] for n in nodes)
    controls={'button','link','combobox','checkbox','radio','textbox','searchbox','spinbutton','tab','slider','DisclosureTriangle','menuitem','switch'}
    names=Counter((n['role'],n['name']) for n in nodes if n['role'] in controls and n['name'])
    headings=[{'index':i,'depth':depths[i],'name':n['name']} for i,n in enumerate(nodes) if n['role']=='heading']
    outline=[]
    for i,(n,p) in enumerate(zip(nodes,projected)):
        text=p.get('name','')
        outline.append('  '*depths[i]+n['role']+(' '+json.dumps(text,ensure_ascii=False) if text else '')+(' '+json.dumps(p.get('state'),ensure_ascii=False) if p.get('state') else ''))
    overview=context.page_update(verbose=False,repeat=False)
    queries=['iPhone',['Lägg i kundvagn','Add to Cart'],['specifikation','specification'],['leverans','delivery'],'cookie']
    samples=[]
    for q in queries:
        result=context.search(q,limit=5,verbose=False,repeat=True)
        samples.append({'query':q,'result':result})
    stats={'url':obs['url'],'title':env.unwrapped.page.title(),'capture_seconds':elapsed,
           'raw_nodes':context.raw_count,'semantic_nodes':len(nodes),'roles':dict(roles),
           'max_depth':max(depths,default=0),'median_depth':statistics.median(depths) if depths else 0,
           'p90_depth':sorted(depths)[min(len(depths)-1,int(len(depths)*.9))] if depths else 0,
           'max_children':max((len(n['children']) for n in nodes),default=0),
           'interactive_nodes':sum(n['role'] in controls for n in nodes),
           'headings':headings,'repeated_control_labels':[{'role':k[0],'name':k[1],'count':v} for k,v in names.most_common() if v>1],
           'full_nonverbose_projection_tokens':context.tokens(json.dumps(projected,ensure_ascii=False,separators=(',',':'))),
           'overview_tokens':context.tokens(json.dumps(overview,ensure_ascii=False,sort_keys=True)),
           'overview_returned_items':len(overview.get('items',[])),
           'tokenizer':'local Qwen tokenizer: '+context.config.tokenizer_path,
           'tokenizer_sha256':hashlib.sha256(Path(context.config.tokenizer_path).read_bytes()).hexdigest()}
    save(out/(name+'.raw-ax.json'),obs['axtree_object'])
    save(out/(name+'.nonverbose.json'),projected);save(out/(name+'.semantic.json'),nodes)
    save(out/(name+'.overview.json'),overview);save(out/(name+'.queries.json'),samples)
    save(out/(name+'.metrics.json'),stats)
    (out/(name+'.outline.txt')).write_text('\n'.join(outline))
    env.unwrapped.page.screenshot(path=str(out/(name+'.png')),full_page=False,timeout=10000)
    return stats


def run(spec):
    name,url,root,headful=spec;out=Path(root)/name;out.mkdir(exist_ok=False)
    from browsergym.core.env import BrowserEnv
    from browsergym.core.task import OpenEndedTask
    from environments.procedural_commerce.runtime import Runtime
    from environments.procedural_commerce.product_fixture import footwear_fixture
    from environments.procedural_commerce.presentation import SHOWCASE
    rt=None
    if name.startswith('local-'):
        design=name[6:];world,groups=footwear_fixture()
        rt=Runtime(world,retailer_designs={s:design for s in SHOWCASE},product_groups=groups,
                   product_control_styles={'nordhem':{'size_eu':'select','colour':'radio'}})
        url=rt.origins['nordhem']+'/products/shoe-42-black'
    env=BrowserEnv(task_entrypoint=OpenEndedTask,task_kwargs={'start_url':'about:blank','goal':'Read-only page structure inspection.'},
                   headless=not headful,viewport={'width':1440,'height':1000},slow_mo=0,timeout=20000,
                   pw_context_kwargs={'accept_downloads':False,'service_workers':'block'})
    report={'name':name,'requested_url':url,'headful':headful,'actions':[],'captures':[],
            'browsergym_version':version('browsergym-core'),'model_calls':0}
    source_paths=[Path(__file__),*Path('intent_browser').glob('*.py'),*Path('environments/procedural_commerce').glob('*.py')]
    report['sources']={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in source_paths}
    try:
        env.reset();page=env.unwrapped.page;page.set_default_timeout(7000)
        try:
            response=page.goto(url,wait_until='domcontentloaded',timeout=45000)
            report['http_status']=response.status if response else None
        except Exception as e:report['navigation_error']=str(e)
        page.wait_for_timeout(5000 if not rt else 200)
        report['captures'].append(capture(env,out,'initial'))
        if not rt:
            for label in ['Avvisa alla','Reject all','Reject All','Decline','Endast nödvändiga','Fortsätt utan att acceptera','Fortsätt utan att godkänna']:
                target=page.get_by_role('button',name=label,exact=True)
                if target.count()==1 and target.is_visible():
                    target.click();report['actions'].append({'action':'dismiss_optional_cookies','label':label})
                    page.wait_for_timeout(1500);report['captures'].append(capture(env,out,'post-consent'));break
            for _ in range(4):page.mouse.wheel(0,1800);page.wait_for_timeout(350)
            page.mouse.wheel(0,-100000);page.wait_for_timeout(800)
            report['actions'].append({'action':'scroll_down_and_return','pixels_down':7200})
            report['captures'].append(capture(env,out,'scrolled'))
            # Only read-only disclosure/menu controls; no cart, account or
            # delivery-destination mutation. Capture each distinct state.
            labels = {
                'elgiganten': [('specifications','Teknisk specifikation'), ('menu','Meny Meny')],
                'amazon': [('dismiss-location','Dismiss'), ('more-facts','See more'), ('menu','Open All Categories Menu')],
                'ikea': [('materials','Material och skötsel')],
            }.get(name, [])
            for stage,label in labels:
                target=page.get_by_role('button',name=label,exact=True)
                if target.count()==1 and target.is_visible():
                    target.click();page.wait_for_timeout(750)
                    report['actions'].append({'action':'open_readonly_control','label':label})
                    report['captures'].append(capture(env,out,stage))
        report['final_url']=page.url
        # Visible body is diagnostic, never substituted for actual AX.
        (out/'visible-body.txt').write_text(page.locator('body').inner_text(timeout=5000))
    except Exception:report['error']=traceback.format_exc()
    finally:
        env.close()
        if rt:rt.close()
        report['artifacts']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in out.iterdir() if p.is_file()}
        save(out/'report.json',report)
    return {'name':name,'error':report.get('error'),'captures':[(c['title'],c['semantic_nodes']) for c in report['captures']]}


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--urls',type=Path);p.add_argument('--headful',action='store_true');p.add_argument('--local',action='store_true');a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    urls=json.loads(a.urls.read_text()) if a.urls else {}
    if a.local:urls.update({'local-'+d:'' for d in ('department-market','editorial-boutique','technical-catalog')})
    (a.output/'capture-source.py').write_bytes(Path(__file__).read_bytes())
    with ProcessPoolExecutor(max_workers=2) as pool:rows=list(pool.map(run,[(k,v,str(a.output),a.headful) for k,v in urls.items()]))
    save(a.output/'index.json',rows);print(json.dumps(rows,indent=2))
    if any(row['error'] for row in rows):raise SystemExit(1)
if __name__=='__main__':main()
