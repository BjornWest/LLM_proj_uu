"""Owned, exclusive Map extraction. No service launch, deletion or download.

Preserves v1 audit evidence. Transaction-specific names and token inspection gate
all mounts. Reserves the report before work, holds verified source descriptors,
and hashes every streamed source byte. Partial volumes remain on any failure.
"""
import argparse
from contextlib import ExitStack
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import tarfile
import uuid
from data.curation.expansion.prepare_map_volumes import cmd, sha, member_allowed


def validate_plan(plan, assets):
    names=[v['name'] for v in plan['volumes']]
    if len(names)!=len(set(names)):raise ValueError('Duplicate volume names')
    if '@sha256:' not in plan['image'] or not plan['project'].startswith('curation-webarena-map-'):raise ValueError('Unpinned image/project')
    mounts=set()
    for v in plan['volumes']:
        if not v['name'].startswith('curation-map-v2-') or '/' in v['name']:raise ValueError('Invalid volume name')
        if v['mount'] in mounts:raise ValueError('Duplicate mount')
        mounts.add(v['mount'])
        name=v['source_archive']
        if name is None:continue
        if Path(name).name!=name or name not in assets:raise ValueError('Unsafe or unknown archive basename')
        prefix=PurePosixPath(v['source_prefix'])
        if prefix.is_absolute() or '..' in prefix.parts or not prefix.parts:raise ValueError('Unsafe prefix')
        if type(v['strip_components']) is not int or v['strip_components']!=len(prefix.parts):raise ValueError('Strip count must match complete directory prefix')


def identity(stream):
    s=os.fstat(stream.fileno())
    return (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)


def read_hash(stream):
    stream.seek(0);digest=hashlib.sha256()
    while part:=stream.read(4*1024*1024):digest.update(part)
    stream.seek(0);return digest.hexdigest()


def verify_identity(path,stream,expected):
    s=path.lstat()
    if not stat.S_ISREG(s.st_mode) or (s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns)!=expected or identity(stream)!=expected:
        raise ValueError('Input identity changed; preserve partial volumes')


def members(stream,prefix):
    stream.seek(0);rows=[]
    with tarfile.open(fileobj=stream,mode='r:') as archive:
        for m in archive:
            if member_allowed(m,prefix):rows.append({'name':m.name,'bytes':m.size,'directory':m.isdir()})
    stream.seek(0)
    if not any(not m['directory'] for m in rows):raise ValueError('Selected archive contains no files')
    return rows


def volume_guard(name,token):
    info=json.loads(cmd(['docker','volume','inspect',name]))
    if len(info)!=1 or info[0]['Name']!=name:raise ValueError('Unexpected volume identity')
    labels=info[0].get('Labels') or {}
    if labels.get('intent.owner')!='curation-expansion' or labels.get('intent.extraction-token')!=token:
        raise ValueError('Foreign/concurrent volume; will not mount or delete')
    return {k:info[0].get(k) for k in ['Name','Driver','CreatedAt','Mountpoint','Labels']}


def transfer(stream,sink,expected_hash):
    stream.seek(0);digest=hashlib.sha256();count=0
    while part:=stream.read(4*1024*1024):sink.write(part);digest.update(part);count+=len(part)
    actual=digest.hexdigest()
    if actual!=expected_hash:raise ValueError('Streamed source hash mismatch; partial volume is untrusted')
    return {'streamed_source_sha256':actual,'streamed_source_bytes':count}


def prepare(plan_path,download_plan_path,downloads,output,execute=False):
    # open(x) rejects symlinks (including dangling), pre-existing and racing writers.
    with output.open('x+') as report, ExitStack() as stack:
        token=uuid.uuid4().hex
        result={'schema':'map-new-volume-extraction-v2','status':'preflight_in_progress','executed':execute,'transaction_id':token,'volumes':[],'model_calls':0,'site_ready':False,'training_eligible':False}
        def save():
            report.seek(0);json.dump(result,report,indent=2);report.write('\n');report.truncate();report.flush();os.fsync(report.fileno())
        save()
        try:
            lock=stack.enter_context((downloads/'map-extraction.lock').open('a'))
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            plan=json.loads(plan_path.read_text());dplan=json.loads(download_plan_path.read_text());assets={a['filename']:a for a in dplan['assets']}
            validate_plan(plan,assets)
            ledger_path=downloads/'ranges-ledger.json';ledger_bytes=ledger_path.read_bytes();ledger=json.loads(ledger_bytes)
            if ledger['plan_sha256']!=sha(download_plan_path):raise ValueError('Download plan mismatch')
            ledger_snapshot=output.with_name(output.stem+'-download-ledger.json')
            with ledger_snapshot.open('xb') as captured:captured.write(ledger_bytes)
            helper_names=['prepare_map_volumes.py','download_ranges_v3.py','download_assets.py']
            result.update(plan_sha256=sha(plan_path),download_plan_sha256=sha(download_plan_path),ledger_sha256=hashlib.sha256(ledger_bytes).hexdigest(),ledger_snapshot=str(ledger_snapshot),script_sha256=sha(Path(__file__)),helper_sha256={name:sha(Path(__file__).with_name(name)) for name in helper_names})
            image=json.loads(cmd(['docker','image','inspect',plan['image']]))[0];result['image_id']=image['Id']
            listed=cmd(['docker','volume','ls','--format','{{.Name}}']).splitlines()
            for v in plan['volumes']:
                if v['name'] in listed:raise ValueError('Existing planned volume '+v['name'])
            sources={}
            for name in sorted({v['source_archive'] for v in plan['volumes'] if v['source_archive']}):
                entry=ledger['assets'].get(name,{})
                if entry.get('status')!='complete' or not entry.get('sha256'):raise ValueError('Source incomplete '+name)
                path=downloads/name
                fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
                stream=stack.enter_context(os.fdopen(fd,'rb'));s=os.fstat(stream.fileno())
                if not stat.S_ISREG(s.st_mode) or s.st_size!=assets[name]['bytes']:raise ValueError('Bad source file/size')
                ident=identity(stream)
                if read_hash(stream)!=entry['sha256']:raise ValueError('Source content mismatch')
                verify_identity(path,stream,ident)
                sources[name]={'path':path,'stream':stream,'identity':ident,'sha256':entry['sha256']}
            inventories={v['name']:members(sources[v['source_archive']]['stream'],v['source_prefix']) for v in plan['volumes'] if v['source_archive']}
            result['source_assets']={n:{'sha256':s['sha256'],'identity':s['identity']} for n,s in sources.items()}
            result['payload_bytes']=sum(m['bytes'] for rows in inventories.values() for m in rows)
            space=cmd(['docker','run','--rm','--pull','never','--network','none','--entrypoint','df',plan['image'],'-Pk','/']).splitlines()[-1].split()
            result['docker_available_bytes']=int(space[3])*1024
            if result['docker_available_bytes']<result['payload_bytes']+5*1024**3:raise ValueError('Insufficient disk plus5GiB margin')
            result['planned_volumes']=[{'planned_name':v['name'],'name':v['name']+'-'+token[:12],'mount':v['mount'],'members':len(inventories.get(v['name'],[]))} for v in plan['volumes']]
            if not execute:result['status']='preflight_passed';save();return result
            result['status']='extracting';save()
            for v,planned in zip(plan['volumes'],result['planned_volumes']):
                name=planned['name']
                if name in cmd(['docker','volume','ls','--format','{{.Name}}']).splitlines():raise ValueError('Transaction volume unexpectedly exists')
                cmd(['docker','volume','create','--label','intent.owner=curation-expansion','--label','intent.dataset=map-static-v2','--label','intent.extraction-token='+token,name])
                owned=volume_guard(name,token);record={**planned,'source_archive':v['source_archive'],'completed':False,'volume_identity':owned};result['volumes'].append(record);save()
                if v['source_archive']:
                    source=sources[v['source_archive']];verify_identity(source['path'],source['stream'],source['identity']);volume_guard(name,token)
                    log=output.with_name(output.stem+'-'+name+'.stderr.txt');record['extract_log']=str(log);save()
                    command=['docker','run','--rm','--pull','never','--network','none','-i','--entrypoint','tar','-v',name+':/target',plan['image'],'-xpf','-','--no-same-owner','--no-same-permissions','-C','/target','--strip-components='+str(v['strip_components']),v['source_prefix']]
                    with log.open('xb') as logs, subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.DEVNULL,stderr=logs) as proc:
                        try:
                            record.update(transfer(source['stream'],proc.stdin,source['sha256']))
                            if v.get('append_virtual_tar_terminator'):proc.stdin.write(bytes(1024))
                            proc.stdin.close();code=proc.wait()
                            if code:raise RuntimeError('Extraction failed; see '+str(log))
                        except BaseException:proc.terminate();proc.wait();raise
                    verify_identity(source['path'],source['stream'],source['identity']);volume_guard(name,token)
                    record.update(member_count=len(inventories[v['name']]),virtual_end_blocks=bool(v.get('append_virtual_tar_terminator')))
                record['completed']=True;save()
            result['status']='extracted_not_launched';save();return result
        except BaseException as error:
            result.update(status='failed_partial_volumes_preserved',error=repr(error));save();raise


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for field in ['plan','download-plan','downloads','output']:p.add_argument('--'+field,type=Path,required=True)
    p.add_argument('--execute',action='store_true');a=p.parse_args()
    print(json.dumps(prepare(a.plan,a.download_plan,a.downloads,a.output,a.execute),indent=2))
