"""Scripted local three-origin rehearsal. No external websites or inference calls."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import threading

import httpx
from intent_browser.actions import make_action_set
from intent_browser.backend import ChatCompletionsBackend
from intent_browser.open_internet import OpenInternetTask, SHOE_GOAL, open_profile, helper_factory
from intent_browser.runner import run_episode
from intent_browser.standard_profile import standard_profile
from intent_browser.trace import Trace


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--helpers', action='store_true')
    parser.add_argument('--observation-pipeline', action='store_true', help='Explicit new integration with native full capture')
    args = parser.parse_args()
    if args.helpers and args.observation_pipeline:parser.error('Pipeline helper concurrency is not adopted')
    args.output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]
    files = list((root/'intent_browser').glob('*.py'))+[Path(__file__)]
    source_before = {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    origins = []
    class Site(BaseHTTPRequestHandler):
        def log_message(self, *_): pass
        def do_GET(self):
            if self.path == '/redirect':
                self.send_response(302); self.send_header('Location', origins[2] + '/retailer'); self.end_headers(); return
            if self.path == '/retailer':
                html = '<title>Retailer</title><h1>Raincloud EU 47.5</h1><button onclick="this.textContent=\'Sweden delivery selected\'">Select Sweden</button>'
            elif self.path == '/direct':
                html = '<title>Another site</title><h1>Direct navigation worked</h1>'
            else:
                html = f'<title>Aggregator</title><h1>Shoe comparison</h1><a href="{origins[1]}/redirect" target="_blank">Visit retailer</a>'
            data = html.encode(); self.send_response(200); self.send_header('Content-Type','text/html'); self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
    servers = [ThreadingHTTPServer(('127.0.0.1', 0), Site) for _ in range(3)]
    origins.extend('http://127.0.0.1:' + str(server.server_port) for server in servers)
    for server in servers: threading.Thread(target=server.serve_forever, daemon=True).start()
    checks, holder, requests = {}, {}, []
    profile = open_profile(standard_profile(helpers=args.helpers))
    task = OpenInternetTask(origins[0]+'/', SHOE_GOAL, headless=True, har=True)
    task.supported_harness_profiles = (profile.name,)
    backend = ChatCompletionsBackend('https://offline.invalid/v1', 'scripted-open-internet')
    backend.client.close()
    backend.supports_images = True
    backend.requires_browser_thread = True
    i = 0
    def dispatch(request):
        nonlocal i
        payload = json.loads(request.content); requests.append(payload)
        env = holder['env']; page = env.page; step = i; i += 1
        if step == 0:
            checks['empty_initial_cookies'] = env.context.cookies() == []
            page.evaluate("localStorage.setItem('private-sentinel','first-session'); document.cookie='private_sentinel=first-session; path=/'")
            name, params = 'click', {'bid': page.get_by_role('link', name='Visit retailer').get_attribute('bid')}
        elif step == 1:
            checks['popup_redirect_three_origins'] = len(env.context.pages)==2 and page.url==origins[2]+'/retailer'
            name, params = 'tab_focus', {'index':0}
        elif step == 2:
            checks['tab_focus_original'] = page.url==origins[0]+'/'
            name, params = 'new_tab', {}
        elif step == 3:
            checks['new_tab_active'] = len(env.context.pages)==3 and page.url=='about:blank'
            name, params = 'goto', {'url':origins[1]+'/direct'}
        elif step == 4:
            checks['goto_unlisted_origin'] = page.url==origins[1]+'/direct'
            name, params = 'tab_close', {}
        elif step == 5:
            checks['close_preserves_other_tabs'] = len(env.context.pages)==2
            name, params = 'tab_focus', {'index':1}
        elif step == 6:
            name, params = 'click', {'bid':page.get_by_role('button',name='Select Sweden').get_attribute('bid')}
        else:
            checks['retailer_action_after_tab_switch'] = page.get_by_role('button',name='Sweden delivery selected').count()==1
            name, params = 'send_msg_to_user', {'text':'Scripted comparison finished; no purchase made.'}
        return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
          'tool_calls':[{'id':f'call-{i}','type':'function','function':{'name':name,'arguments':json.dumps(params)}}]}}],
          'usage':{'cost':0},'offline_fixture':True})
    backend.client = httpx.Client(transport=httpx.MockTransport(dispatch))
    def factory(video):
        holder['env'] = task.make_env(video, action_mapping=make_action_set().to_python_code)
        return holder['env']
    try:
        trace, summary = run_episode(factory, backend, {'task':'open-internet-scripted', 'model_calls':0,'training_eligible':False},
            output=args.output/'traces', max_steps=8, episode_task=task, harness_profile=profile,
            before_observation=lambda:{'scope':'scripted supervisor seam', 'human_intervention_note':'Test note: comparison only.'},
            terminal_response_instruction='Report the comparison result naturally.',
            **({'observation_pipeline': __import__('intent_browser.observation_pipeline',fromlist=['ObservationPipelineConfig']).ObservationPipelineConfig((),full_capture_only=True)} if args.observation_pipeline else {}))
        if args.observation_pipeline:
            import gzip
            rows=[json.loads(line) for line in (trace/'steps.jsonl').read_text().splitlines()]
            checks['explicit_native_capture_every_decision']=all(json.loads(gzip.open(trace/row['observation']['raw'],'rt').read())['observation_capture']['mode']=='native_fallback' for row in rows)
            checks['no_background_claim']=all(not row['observation_pipeline']['overlapped'] for row in rows)
        checks['zero_action_errors'] = summary['action_error_count']==0 and summary['error'] is None
        checks['eight_decisions'] = len(requests)==8
        checks['outcomes_remain_unknown'] = all(summary['evaluation'][k] is None for k in ('task_completed','authorization_satisfied','safe_success'))
        checks['tab_list_and_supervisor_note_delivered'] = all('BROWSER TABS' in json.dumps(r['messages']) and 'Test note: comparison only.' in json.dumps(r['messages']) for r in requests)
        checks['har_closed_and_saved'] = (trace/'network.har.zip').is_file()
        # Sequential by design: fresh context must not inherit the first context's state on the SAME origin.
        fresh = OpenInternetTask(origins[0]+'/', 'Inspect isolation', headless=True)
        fresh.prepare(Trace(args.output/'isolation', {'scripted':True}))
        if args.helpers:
            from types import SimpleNamespace
            parent = SimpleNamespace(unwrapped=SimpleNamespace(page=SimpleNamespace(url=origins[0]+'/')))
            env = helper_factory(parent, 'Inspect isolation')(None)
        else:
            env = fresh.make_env(action_mapping=make_action_set().to_python_code)
        try:
            env.reset(seed=0)
            checks['fresh_context_no_previous_cookie'] = env.context.cookies()==[]
            checks['fresh_context_no_previous_localstorage'] = env.page.evaluate("localStorage.getItem('private-sentinel')") is None
        finally: env.close()
        checks['sources_stable_during_execution'] = all(hashlib.sha256((root/p).read_bytes()).hexdigest()==h for p,h in source_before.items())
        report = {'schema':'open-internet-scripted-validation-v1','passed':all(checks.values()),'checks':checks,
                  'trace':str(trace),'helpers_enabled':args.helpers,'model_calls':0,'external_site_visits':0,
                  'source_sha256':source_before}
        (args.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report['checks'],indent=2))
        if not report['passed']: raise SystemExit(1)
    finally:
        backend.close()
        for server in servers: server.shutdown(); server.server_close()


if __name__ == '__main__': main()
