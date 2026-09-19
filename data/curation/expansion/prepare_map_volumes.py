"""Preflight or extract Map data into NEW explicitly owned Docker volumes.

No service launch, download, deletion or inference. Extraction requires all Map
assets complete and rehashed, a pinned cached image, unused volume names and an
exclusive new report path. Only Nominatim's exact source prefix gets virtual TAR
end blocks; no source bytes are modified and no database tables are dropped.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
from data.curation.expansion.download_ranges_v3 import verify_completed


def cmd(args):return subprocess.run(args,text=True,capture_output=True,check=True).stdout

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def member_allowed(member,prefix):
    path=PurePosixPath(member.name)
    if path.is_absolute() or '..' in path.parts:raise ValueError('Unsafe TAR member path')
    if not (member.isfile() or member.isdir()):raise ValueError('Unsupported TAR member type; do not silently omit')
    base=PurePosixPath(prefix)
    return path==base or base in path.parents

def members_for(path,prefix):
    rows=[]
    with tarfile.open(path,'r:') as archive:
        for m in archive:
            selected=member_allowed(m,prefix)
            if selected:rows.append({'name':m.name,'bytes':m.size,'directory':m.isdir()})
    if not rows:raise ValueError('Expected source prefix absent from TAR')
    return rows


def prepare(plan_path,download_plan_path,downloads,output,execute=False):
    if output.exists() or output.is_symlink():raise FileExistsError(output)
    plan=json.loads(plan_path.read_text());download_plan=json.loads(download_plan_path.read_text())
    ledger_path=downloads/'ranges-ledger.json';ledger=json.loads(ledger_path.read_text())
    assert ledger['plan_sha256']==sha(download_plan_path)
    assert '@sha256:' in plan['image'] and plan['project'].startswith('curation-webarena-map-')
    listed=cmd(['docker','volume','ls','--format','{{.Name}}']).splitlines()
    for v in plan['volumes']:
        assert v['name'].startswith('curation-map-v2-')
        if v['name'] in listed:raise ValueError('Refuse existing volume: '+v['name'])
    image=json.loads(cmd(['docker','image','inspect',plan['image']]))[0]
    assets={a['filename']:a for a in download_plan['assets']}
    unique={v['source_archive'] for v in plan['volumes'] if v['source_archive']}
    for name in sorted(unique):
        entry=ledger['assets'].get(name,{})
        verify_completed(downloads/name,entry,assets[name]['bytes'])
    inventories={v['name']:members_for(downloads/v['source_archive'],v['source_prefix']) for v in plan['volumes'] if v['source_archive']}
    result={'schema':'map-new-volume-extraction-v1','status':'preflight_passed','executed':execute,'plan_sha256':sha(plan_path),
            'download_plan_sha256':sha(download_plan_path),'ledger_sha256':sha(ledger_path),'image_id':image['Id'],
            'script_sha256':sha(Path(__file__)),'payload_bytes':sum(m['bytes'] for rows in inventories.values() for m in rows),
            'source_assets':{n:ledger['assets'][n]['sha256'] for n in sorted(unique)},'volumes':[],
            'model_calls':0,'site_ready':False,'training_eligible':False}
    space=cmd(['docker','run','--rm','--network','none','--entrypoint','df',plan['image'],'-Pk','/']).splitlines()[-1].split()
    result['docker_available_bytes']=int(space[3])*1024
    if result['docker_available_bytes']<result['payload_bytes']+5*1024**3:raise ValueError('Insufficient Docker disk for extraction and5GiB margin')
    if not execute:
        result['planned_volumes']=[{'name':v['name'],'members':len(inventories.get(v['name'],[]))} for v in plan['volumes']]
        with output.open('x') as out:json.dump(result,out,indent=2);out.write('\n')
        return result
    try:
        for v in plan['volumes']:
            cmd(['docker','volume','create','--label','intent.owner=curation-expansion','--label','intent.dataset=map-static-v2',v['name']])
            record={'name':v['name'],'source_archive':v['source_archive'],'completed':False}
            result['volumes'].append(record)
            if v['source_archive']:
                command=['docker','run','--rm','--network','none','-i','--entrypoint','tar','-v',v['name']+':/target',plan['image'],
                         '-xpf','-','--no-same-owner','--no-same-permissions','-C','/target','--strip-components='+str(v['strip_components']),v['source_prefix']]
                log=output.with_name(output.stem+'-'+v['name']+'.stderr.txt')
                record['extract_log']=str(log)
                with log.open('xb') as log_stream, subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=log_stream) as proc:
                    try:
                        with (downloads/v['source_archive']).open('rb') as stream:
                            while part:=stream.read(4*1024*1024):proc.stdin.write(part)
                        if v.get('append_virtual_tar_terminator'):proc.stdin.write(bytes(1024))
                        proc.stdin.close();code=proc.wait();log_stream.flush()
                        if code:raise RuntimeError('TAR extraction failed; see '+str(log))
                    except BaseException:
                        proc.terminate();proc.wait();raise
                record.update(member_count=len(inventories[v['name']]),payload_bytes=sum(m['bytes'] for m in inventories[v['name']]),virtual_end_blocks=bool(v.get('append_virtual_tar_terminator')))
            record['completed']=True
        result['status']='extracted_not_launched'
    except BaseException as error:
        result.update(status='failed_partial_volumes_preserved',error=repr(error));raise
    finally:
        with output.open('x') as out:json.dump(result,out,indent=2);out.write('\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for field in ['plan','download-plan','downloads','output']:p.add_argument('--'+field,type=Path,required=True)
    p.add_argument('--execute',action='store_true');a=p.parse_args()
    print(json.dumps(prepare(a.plan,a.download_plan,a.downloads,a.output,a.execute),indent=2))
