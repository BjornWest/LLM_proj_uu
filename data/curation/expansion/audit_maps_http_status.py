"""Offline native-checker fault injection: expected URL with HTTP 404/500.

No browser, server or model requests. Synthetic evidence is never task execution.
Use the separate pinned WebArena Verified virtual environment.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
from webarena_verified.api import WebArenaVerified
from webarena_verified.types.config import WebArenaVerifiedConfig

ROOT = Path(__file__).resolve().parents[3]
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--output', type=Path, required=True); a = p.parse_args()
    a.output.mkdir(parents=True, exist_ok=False)
    source = ROOT / '.local/webarena-verified/dataset.json'
    template = ROOT / '.local/expansion-webarena/maps-native-root-gate-audit-v1/synthetic-root.har'
    source_tasks = json.loads(source.read_text()); base = json.loads(template.read_text())
    api = WebArenaVerified(config=WebArenaVerifiedConfig(environments={'__MAP__':{'urls':['http://localhost:13030']}}))
    rows = []
    for task in source_tasks:
        if task['task_id'] not in range(369,374): continue
        expected = task['eval'][1]['expected']['url'].replace('__MAP__','http://localhost:13030')
        for status in (200,404,500):
            for match in (True,False):
                har = copy.deepcopy(base); entry = har['log']['entries'][0]; har['log']['entries'] = [entry]
                entry['request'] = {'method':'GET','url':expected if match else 'http://localhost:13030/unrelated',
                    'httpVersion':'HTTP/1.1','cookies':[],'headers':[{'name':'Accept','value':'text/html'}], 'queryString':[], 'headersSize':-1,'bodySize':0}
                body = '<html><body>SYNTHETIC TEST: no place description</body></html>'
                entry['response'] = {'status':status,'statusText':{200:'OK',404:'Not Found',500:'Internal Server Error'}[status],
                    'httpVersion':'HTTP/1.1','cookies':[],'headers':[], 'redirectURL':'',
                    'headersSize':-1,'bodySize':len(body), 'content':{'size':len(body),'mimeType':'text/html','text':body}}
                har['log']['pages'] = []; entry.pop('pageref', None)
                path = a.output / f'{task["task_id"]}-{status}-{match}.har'
                path.write_text(json.dumps(har))
                response = {'task_type':'navigate','status':'SUCCESS','retrieved_data':None}
                grade = api.evaluate_task(task_id=task['task_id'], agent_response=response, network_trace=path).model_dump(mode='json')
                rows.append({'task_id':task['task_id'],'goal':task['intent'],'http_status':status,
                             'expected_url_requested':match,'synthetic_har':str(path),'har_sha256':sha(path),'native_grade':grade})
    assert all(row['native_grade']['score']==(1.0 if row['expected_url_requested'] and row['http_status']==200 else 0.0) for row in rows)
    report = {'schema':'maps-native-http-status-fault-injection-v2',
              'scope':'Synthetic HAR only; no actual Maps page or browser execution. Empty description even for HTTP 200.',
              'source_sha256':sha(source),'reviewer_sha256':sha(Path(__file__)),
              'cases':rows,'model_calls':0,'browser_runs':0,
              'incorrect_acceptances':sum(row['native_grade']['score']==1 for row in rows),
              'interpretation':'Native status default rejects404/500, but acceptsHTTP200 empty description at matchingURL. Full rendering/content still requires site validation.',
              'training_eligible':False}
    (a.output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='cases'},indent=2))

if __name__ == '__main__': main()
