"""Bounded read-only TAR header survey via exact HTTP ranges; skips file payloads.

This never extracts or marks a dataset ready. Unsupported extended sparse layouts
stop inspection. Metadata bytes count against the approved download allowance.
"""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile
import time
import requests


def survey(asset, *, max_bytes=16*1024*1024, seconds=120, start_offset=0):
    if start_offset<0 or start_offset%512:raise ValueError('Expected TAR header offset')
    start=time.monotonic();offset=start_offset;downloaded=0;rows=[];cache_start=-1;cache=b'';reason=None
    with requests.Session() as session:
        while offset+512<=asset['bytes']:
            if time.monotonic()-start>=seconds:reason='time_budget';break
            if not cache_start<=offset<=cache_start+len(cache)-512:
                end=min(offset+8191,asset['bytes']-1)
                if downloaded+end-offset+1>max_bytes:reason='byte_budget';break
                r=session.get(asset['url'],headers={'Range':f'bytes={offset}-{end}','If-Range':asset['etag'],'Accept-Encoding':'identity'},timeout=(10,30))
                assert r.status_code==206 and r.headers.get('Content-Range')==f'bytes {offset}-{end}/{asset["bytes"]}'
                assert r.headers.get('ETag')==asset['etag'] and len(r.content)==end-offset+1
                cache_start=offset;cache=r.content;downloaded+=len(cache)
            header=cache[offset-cache_start:offset-cache_start+512]
            if header==bytes(512):reason='end_of_archive';break
            info=tarfile.TarInfo.frombuf(header,'utf-8','strict')
            rows.append({'offset':offset,'name':info.name,'bytes':info.size,'type':info.type.decode('ascii')})
            if info.type==tarfile.GNUTYPE_SPARSE:reason='unsupported_extended_sparse_layout';break
            offset+=512+((info.size+511)//512)*512
            if offset>asset['bytes']:raise ValueError('Header extends past pinned source size')
            if len(rows)%100==0:print(json.dumps({'headers':len(rows),'archive_offset':offset,'downloaded':downloaded}),flush=True)
    return {'source':asset,'headers':rows,'inspected_header_count':len(rows),'downloaded_metadata_bytes':downloaded,
            'start_offset':start_offset,'next_offset':offset,'stop_reason':reason,'complete':reason=='end_of_archive',
            'inspector_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            'scope':'Header inventory only; does not verify skipped payloads or approve data omission.'}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',type=Path,required=True);p.add_argument('--asset',required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--start-offset',type=int,default=0);a=p.parse_args()
    if a.output.exists() or a.output.is_symlink():raise FileExistsError(a.output)
    asset=next(x for x in json.loads(a.plan.read_text())['assets'] if x['filename']==a.asset)
    result=survey(asset,start_offset=a.start_offset)
    with a.output.open('x') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k!='headers'}),flush=True)
