"""Finite saved-world copied-asset browser validation, not a model evaluation.

Launch through run_bounded_job.py only after the current resource hold is released.
Uses packet-pinned modules before project imports and intercepts copied HTTP asset
bytes inside private browser contexts. No Website files, grades or recipes change.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
LOCAL_LIBRARIES=ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu'
if LOCAL_LIBRARIES.is_dir():
    os.environ['LD_LIBRARY_PATH']=str(LOCAL_LIBRARIES)+':'+os.environ.get('LD_LIBRARY_PATH','')


def read(path):
    return json.loads(Path(path).read_text())


def pinned(record):
    path=Path(record['path'])
    if sha256(path.read_bytes()).hexdigest()!=record['sha256']:
        raise ValueError(f'Pinned input changed: {path}')
    return path


def worker(packet_path, output, case, archive_override=None, journey='product', capture_mode='cdp'):
    if capture_mode not in {'cdp','browsergym'}:raise ValueError('Unknown capture mode')
    packet=read(packet_path)
    # Frozen modules resolve their own ROOT to the accepted source archive;
    # import live new Inspection code only after that archive on sys.path.
    archive=archive_override or pinned(packet['source_archive']['environments/website_drafts/shop.js']).parents[2]
    sys.dont_write_bytecode=True
    for record in packet['source_archive'].values():pinned(record)
    sys.path[:]=[str(archive),str(ROOT),*[p for p in sys.path if p not in (str(ROOT),str(archive))]]
    from environments.website_world.catalog_branch_runtime import BranchRuntime
    from types import SimpleNamespace
    from environments.website_world import generation, runtime
    from training.browser_training.fact_render_overlay import instrument_shop, ASSET
    from training.browser_training.fact_source_provider import FactSourceProvider
    from training.browser_training import fact_source_provider, fact_render_capture, fact_render_overlay
    for module in (fact_source_provider, fact_render_capture, fact_render_overlay):
        if not Path(module.__file__).resolve().is_relative_to(ROOT):
            raise ValueError('Inspection imports escaped owned source root')
    from playwright.sync_api import sync_playwright
    if capture_mode=='browsergym':
        from browsergym.core.observation import (_pre_extract, _post_extract,
            extract_dom_snapshot, extract_merged_axtree)
    if generation.ROOT.resolve()!=archive or runtime.ROOT.resolve()!=archive:
        raise ValueError('Runtime imports escaped pinned archive')
    recipe=pinned(packet['artifacts']['recipe/manifest.json']).parent
    generation.load(recipe)
    original_product=read(pinned(packet['artifacts'][f'validation-v2/browser-cases/{case}/public-product.private.json']))
    output.mkdir(parents=True,exist_ok=False)
    summaries={};observations={};source_receipts={}
    # Each mode owns a separate Runtime, browser session and output. These
    # paired comparisons are sequential within a case to bound parallelism;
    # independent cases run in parallel (two processes maximum).
    for enabled in (False,True):
        mode='on' if enabled else 'off';errors=[]
        with BranchRuntime(recipe/'pin',presentation=read(recipe/'presentation.json'),
                surrounding=read(recipe/'surrounding.private.json'),basket_plan=read(recipe/'basket-plan.private.json'),
                checkout_domain=read(recipe/'checkout-domain.private.json'),
                delivery_plan=read(recipe/'delivery-plan.private.json') if (recipe/'delivery-plan.private.json').exists() else None,
                readable_origins=read(recipe/'episode.json').get('readable_origins',False),lazy_publication=True) as rt, sync_playwright() as pw:
            episode=SimpleNamespace(runtime=rt)
            if rt.compositions != read(recipe/'compositions.private.json'):raise ValueError('Sampled composition changed')
            browser=pw.chromium.launch(headless=True)
            context=browser.new_context()
            page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
            provider=FactSourceProvider(page,enabled=enabled);provider.install()
            if enabled:
                def copied_asset(route):
                    response=route.fetch();body=response.body();text,receipt=instrument_shop(body.decode(),enabled=True)
                    expected=episode.runtime.asset_hashes['shop.js']
                    if receipt['source_sha256']!=expected:raise ValueError('Served asset hash differs from Runtime manifest')
                    source_receipts[mode]=receipt
                    (output/'shop.served-original.js').write_bytes(body)
                    (output/'shop.served-overlay.js').write_text(text)
                    route.fulfill(response=response,body=text,content_type='text/javascript')
                context.route('**/shop.js',copied_asset)
                context.route('**/fact-recorder.js',lambda route:route.fulfill(body=ASSET.read_bytes(),content_type='text/javascript'))
            native=original_product['variants'][0]
            binding=episode.runtime.bindings['retailer_offers'][native['offerId']]
            origin=episode.runtime.origins[binding['retailer_id']] if 'retailer_id' in binding else binding['url'].split('/#')[0]
            url=binding['url'].split('?')[0]
            if episode.runtime.origin_map is not None:
                url=episode.runtime.origin_map.to_transport(url)
            # Use the native Runtime's physical preview host. No DNS/hosts or
            # origin-bridge/harness files are changed by this validation.
            page.goto(url);page.wait_for_selector('[data-form="add"]')
            cdp=context.new_cdp_session(page)
            def settle():
                page.wait_for_load_state('networkidle')
                if enabled:
                    provider._attest()
                if errors:raise AssertionError(errors)
            def observation_operation():
                if capture_mode=='browsergym':
                    # Run the installed native marking/extraction functions, not
                    # a hand-made approximation. No action/capture retry here.
                    _pre_extract(page)
                    try:
                        dom=extract_dom_snapshot(page)
                        ax=extract_merged_axtree(page)
                    finally:
                        _post_extract(page)
                    return {'axtree_object':ax,'dom_object':dom}
                return {'axtree_object':{'nodes':cdp.send('Accessibility.getFullAXTree')['nodes']}}
            def save_stage(stage):
                settle()
                observation=provider.observe(observation_operation)
                html=page.locator('#app').evaluate('n=>n.outerHTML')
                ax=observation['axtree_object']['nodes']
                values=[]
                for node in ax:
                    if not node.get('ignored',False):
                        properties={p['name']:p['value'].get('value') for p in node.get('properties',[]) if 'value' in p['value']}
                        values.append({'role':node.get('role',{}).get('value'),'name':node.get('name',{}).get('value'),
                                       'value':node.get('value',{}).get('value'),'properties':properties})
                state=page.evaluate('(key)=>JSON.parse(localStorage.getItem(key))',f'website-drafts.state.{binding["retailer_id"]}' if 'retailer_id' in binding else f'website-drafts.state.{native["offerId"].split("/")[0]}')
                observations[(mode,stage)]={'html':html,'ax':values,'state':state}
                if enabled:
                    result=provider.result(observation)
                    if result is None:raise ValueError(f'Unpaired observation: {provider.diagnostics}')
                    result['provider_packet']=provider(None,observation,{'snapshot_id':f'{case}-{stage}','step':len(summaries),'coverage':'full'})
                    normalized=result['normalized']
                    assert (normalized['occurrences'] or stage=='quote_unvalidated') and not normalized['delivery_evidence']
                    assert not page.locator('[data-fr-occurrence]').count()
                    for occurrence in normalized['occurrences']:
                        if occurrence['binding']['authority']=='renderer_native_selection':
                            assert occurrence['effective_state']['variant_key']==page.locator('[data-form="add"]').get_attribute('data-key')
                    (output/f'{stage}.capture.private.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
                    summaries[stage]={'occurrences':len(normalized['occurrences']),'dom_runs':len(normalized['runs']),
                        'direct_ax_sources':len(normalized['ax_sources']),'unknown_ax_runs':len(normalized['ax_diagnostics']),
                        'diagnostics':normalized['diagnostics'],'state_only_not_delivery':True}
                    return result
                return None
            save_stage('default')
            # Use actual controls, not guessed reconstruction of default state.
            for option in original_product['options']:
                key=option['key'];value=str(option['values'][-1])
                select=page.locator(f'select[data-selection="{key}"]')
                radio=page.locator(f'input[type=radio][data-selection="{key}"][value="{value}"]')
                button=page.locator(f'button[data-selection-button="{key}"][data-value="{value}"]')
                if select.count():select.select_option(value)
                elif radio.count():radio.check()
                elif button.count():button.click()
                else:raise ValueError('Expected actual variant control')
            save_stage('variant')
            # Opening existing disclosures changes AX availability, not facts.
            for details in page.locator('main details').all():
                if details.get_attribute('open') is None and details.locator(':scope > summary').is_visible():details.locator(':scope > summary').click()
            # The copied disclosure hook records a fresh capture revision while
            # retaining the same bound text nodes; this performs no page render.
            save_stage('disclosures')
            if journey=='quote':
                page.locator('[data-form="add"] button').click()
                page.goto(url.split('/#')[0]+'/#/checkout?step=1')
                page.wait_for_selector('[data-form="address"]')
                # Enter the existing saved-world home fixture through ordinary
                # controls. This is scripted input, not a model discovery or a
                # repair to the world, form defaults or task/grader contract.
                home=read(recipe/'pin/world.private.json')['address_context']['addresses'][0]['address']
                address={'name':'Recording first recipient','street':(home['street']+' '+home['house_number']).strip(),
                         'unit':home['unit'],'postcode':home['postcode'],'city':home['city']}
                for key,value in address.items():page.locator(f'[data-form="address"] [name="{key}"]').fill(value)
                page.locator('[data-form="address"] button').click()
                page.goto(url.split('/#')[0]+'/#/checkout?step=2')
                def ready_quote():
                    page.locator('[aria-label="Current quote"] dd').first.wait_for(state='attached')
                ready_quote()
                first=save_stage('quote_default')
                for details in page.locator('main details').all():
                    if details.get_attribute('open') is None and details.locator(':scope > summary').is_visible():details.locator(':scope > summary').click()
                radios=page.locator('input[data-service-group]:not(:checked)')
                if not radios.count():raise ValueError('Fixture has no alternative public delivery choice')
                chosen=radios.first.get_attribute('value')
                # Freeze identity before clicking: :not(:checked) changes after
                # each render and a check() on that selector follows another row.
                page.locator(f'input[data-service-group][value={json.dumps(chosen)}]').click()
                ready_quote();second=save_stage('quote_service')
                if enabled:
                    def selected(result):
                        return [o for o in result['normalized']['occurrences'] if o['binding'].get('field')=='selected_service']
                    assert selected(first) and selected(second),'Selected service registration missing'
                    assert selected(first)[0]['effective_state']!=selected(second)[0]['effective_state'],'Service state was reused'
                    # Basket-choice IDs and individual shipment-service IDs
                    # are different namespaces. Bind the actual selected draft.
                    assert page.locator('input[data-service-group]:checked').first.get_attribute('value')==chosen
                    assert selected(second)[0]['effective_state']['draft'].get('basketSelection')
                page.goto(url.split('/#')[0]+'/#/checkout?step=1')
                page.wait_for_selector('[data-form="address"]')
                page.locator('[data-form="address"] [name="name"]').fill('Recording revised recipient')
                # A changed but unsaved input invalidates the old quote. No old
                # quote/recipient occurrence may survive in the current DOM.
                page.goto(url.split('/#')[0]+'/#/checkout?step=2')
                invalid=save_stage('quote_unvalidated')
                if enabled:
                    assert not any(o['binding']['authority'].startswith('renderer_native_quote') or
                                   o['binding']['authority'] in ('renderer_native_recipient','renderer_native_shipment_selection','renderer_native_shipment_scalar')
                                   for o in invalid['normalized']['occurrences'])
                page.goto(url.split('/#')[0]+'/#/checkout?step=1')
                page.locator('[data-form="address"] button').click()
                page.goto(url.split('/#')[0]+'/#/checkout?step=2')
                ready_quote();revised=save_stage('quote_revalidated')
                if enabled:
                    recipients=[o for o in revised['normalized']['occurrences'] if o['binding']['authority']=='renderer_native_recipient']
                    assert recipients and all(o['effective_state']['draft']['address']['name']=='Recording revised recipient' for o in recipients)
            provider.close()
            context.close();browser.close()
    parity={}
    for stage in [stage for mode,stage in observations if mode=='off']:
        left,right=observations['off',stage],observations['on',stage]
        parity[stage]={name:left[name]==right[name] for name in ('html','ax','state')}
        if not all(parity[stage].values()):raise AssertionError((case,stage,parity[stage]))
    for record in packet['source_archive'].values():pinned(record)
    for role in ('recipe/manifest.json',f'validation-v2/browser-cases/{case}/public-product.private.json'):pinned(packet['artifacts'][role])
    result={'passed':True,'case':case,'parity':parity,'captures':summaries,'served_asset':source_receipts,
            'archive':str(archive),'journey':journey,'capture_mode':capture_mode,
            'models':0,'world_draws':0,'grader_calls':0,'live_website_adoption':False,
            'actual_runner_invoked':False}
    (output/'result.json').write_text(json.dumps(result,indent=2));return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--packet',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--case',choices=['alternate','winner'])
    parser.add_argument('--archive',type=Path)
    parser.add_argument('--journey',choices=['product','quote'],default='product')
    parser.add_argument('--capture-mode',choices=['cdp','browsergym'],default='cdp')
    parser.add_argument('--browser-workers',type=int,choices=[1,2],default=2,
                        help='Use 1 for a demonstrated browser/PID resource dependency')
    args=parser.parse_args()
    if args.case:
        print(json.dumps(worker(args.packet.resolve(),args.output.resolve(),args.case,args.archive.resolve() if args.archive else None,args.journey,args.capture_mode)));return
    args.output.mkdir(parents=True,exist_ok=False)
    packet=read(args.packet)
    archive=args.archive.resolve() if args.archive else args.output/'source'
    if not args.archive:archive.mkdir()
    for relative,record in packet['source_archive'].items():
        target=archive/relative
        if not target.resolve().is_relative_to(archive.resolve()):raise ValueError('Archive path escapes staging root')
        target.parent.mkdir(parents=True,exist_ok=True)
        if args.archive:
            pinned({'path':str(target),'sha256':record['sha256']})
        else:shutil.copyfile(pinned(record),target)
    # Transitive data pins exist in the frozen registry but were omitted from
    # source_archive. Supply exact matching bytes only to our separate copy.
    role='environments/product_world/data/product_feature_policies/catalogue_v2/manifest.json'
    catalogue=read(pinned(packet['source_archive'][role]));supplement=[]
    for entry in catalogue['concepts'].values():
        relative=str(Path(role).parent/entry['file']);target=archive/relative
        if target.exists():
            pinned({'path':str(target),'sha256':entry['sha256']})
        else:
            source=pinned({'path':str(ROOT/relative),'sha256':entry['sha256']})
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
            supplement.append({'path':relative,'sha256':entry['sha256'],'authority':'frozen_catalogue_manifest'})
    (args.output/'archive-supplement.json').write_text(json.dumps(supplement,indent=2))
    def launch(case):
        completed=subprocess.run([sys.executable,__file__,'--packet',str(args.packet.resolve()),'--output',str(args.output.resolve()/case),'--case',case,'--archive',str(archive.resolve()),'--journey',args.journey,'--capture-mode',args.capture_mode],text=True,capture_output=True)
        (args.output/f'{case}.stdout').write_text(completed.stdout);(args.output/f'{case}.stderr').write_text(completed.stderr)
        return {'case':case,'exit_code':completed.returncode}
    # A one-worker pool retains isolated cases while running their browser
    # sessions serially under the demonstrated 256-PID startup limitation.
    with ThreadPoolExecutor(max_workers=args.browser_workers) as pool:results=list(pool.map(launch,['alternate','winner']))
    (args.output/'terminal.json').write_text(json.dumps({'cases':results,
        'browser_workers':args.browser_workers,'passed':all(r['exit_code']==0 for r in results)},indent=2))
    if any(r['exit_code']!=0 for r in results):raise SystemExit(1)


if __name__=='__main__':main()
