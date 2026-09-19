"""Build a no-pull isolated Map launch command from successful extraction evidence.

Read-only Docker inspection only. This module never launches or resets a service.
Review and run the returned argv separately after extraction acceptance.
"""
import argparse,hashlib,json
from pathlib import Path
from urllib.parse import urlsplit
from data.curation.expansion.prepare_map_volumes_v2 import cmd,volume_guard

def build(plan_path,extraction_path):
    plan=json.loads(plan_path.read_text());e=json.loads(extraction_path.read_text())
    assert e['schema']=='map-new-volume-extraction-v2' and e['status']=='extracted_not_launched'
    assert e['executed'] is True and e['plan_sha256']==hashlib.sha256(plan_path.read_bytes()).hexdigest()
    assert len(e['volumes'])==len(plan['volumes']) and all(v['completed'] for v in e['volumes'])
    image=json.loads(cmd(['docker','image','inspect',plan['image']]))[0];assert image['Id']==e['image_id']
    name=plan['project']+'-'+e['transaction_id'][:12]
    assert name not in cmd(['docker','ps','-a','--format','{{.Names}}']).splitlines()
    browser=urlsplit(plan['browser_origin']);control=urlsplit(plan['control_origin'])
    assert browser.hostname==control.hostname=='localhost' and browser.port!=control.port
    argv=['docker','run','-d','--pull','never','--name',name,'--label','intent.owner=curation-map-static-v2','--label','intent.extraction-token='+e['transaction_id'],'--memory','8g','--cpus','4','--shm-size','512m','-p',f'127.0.0.1:{browser.port}:8080','-p',f'127.0.0.1:{control.port}:8877','-e','WA_ENV_CTRL_EXTERNAL_SITE_URL='+plan['browser_origin']]
    for v,expected in zip(e['volumes'],plan['volumes']):
        assert v['planned_name']==expected['name'] and v['mount']==expected['mount']
        current=volume_guard(v['name'],e['transaction_id']);assert current==v['volume_identity']
        if expected['source_archive']:
            assert v['streamed_source_sha256']==e['source_assets'][expected['source_archive']]['sha256']
        argv+=['--mount','type=volume,source='+v['name']+',target='+v['mount']]
    argv.append(plan['image'])
    return {'schema':'map-isolated-launch-command-v1','argv':argv,'extraction_sha256':hashlib.sha256(extraction_path.read_bytes()).hexdigest(),'container_name':name,'browser_origin':plan['browser_origin'],'control_origin':plan['control_origin'],'executed':False,'site_ready':False,'network_model_calls':0,'required_runtime_checks':['Search and reverse geocoding','Car, bike and foot routing','Original tile rendering and page assets','Original native task positive/negative pairs with independently sufficient graders'],'limitations':['No flatnode update/import cache; static service only.','This command generator does not certify data correctness or task readiness.','8GiB/4CPU cap needs checking against current host resources before execution.']}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',type=Path,required=True);p.add_argument('--extraction',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    if a.output.exists() or a.output.is_symlink():raise FileExistsError(a.output)
    result=build(a.plan,a.extraction)
    with a.output.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(result,indent=2))
