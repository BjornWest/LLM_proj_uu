"""Explicit checked continuation of unchanged assets into a new approved plan.

Original ledger/parts preserved. Complete chunks are hardlinked after checksum
verification; unfinished prefixes are copied. The source ledger lock must be free.
No network calls. New manifest still accounts for all bytes, including reused ones.
"""
import argparse
import copy
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
from data.curation.expansion.download_ranges_v3 import CHUNK,verify_completed,file_sha
from data.curation.expansion.download_assets import validate_plan,write_state


def migrate(old_plan,new_plan,source,dest):
    old=json.loads(old_plan.read_text());new=json.loads(new_plan.read_text());total=validate_plan(new)
    old_hash=file_sha(old_plan);new_hash=file_sha(new_plan)
    assert new['supersedes_plan']['sha256']==old_hash
    with (source/'ranges.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        original=(source/'ranges-ledger.json').read_bytes();state=json.loads(original)
        assert state['plan_sha256']==old_hash and state['chunk_bytes']==CHUNK
        old_assets={a['filename']:a for a in old['assets']};new_assets={a['filename']:a for a in new['assets']}
        for name,entry in state['assets'].items():
            assert name in new_assets and old_assets[name]==new_assets[name], 'Cannot reuse bytes for changed source or layout'
            for start,item in entry['chunks'].items():
                path=source/(name+'.ranges')/start;size=min(CHUNK,old_assets[name]['bytes']-int(start))
                if item['status']=='complete':verify_completed(path,item,size)
                elif path.exists():assert not path.is_symlink() and path.is_file() and path.stat().st_size<=size
        dest.mkdir(exist_ok=False)
        (dest/'parent-ledger.json').write_bytes(original)
        files=0;reuse_bytes=0
        for name,entry in state['assets'].items():
            target=dest/(name+'.ranges');target.mkdir()
            for start,item in entry['chunks'].items():
                path=source/(name+'.ranges')/start
                if not path.exists():continue
                if item['status']=='complete':os.link(path,target/start)
                else:shutil.copy2(path,target/start)
                files+=1;reuse_bytes+=path.stat().st_size
            if entry['status']=='complete':
                verify_completed(source/name,entry,old_assets[name]['bytes']);os.link(source/name,dest/name)
        migrated=copy.deepcopy(state);migrated.update(plan_sha256=new_hash,reserved_bytes=total,limit_bytes=new['limit_bytes'])
        migrated['continuation']={'source':str(source),'parent_plan_sha256':old_hash,'parent_ledger_sha256':hashlib.sha256(original).hexdigest(),'reused_files':files,'reused_body_bytes':reuse_bytes,'original_bytes_preserved':True,'no_network_calls':True,'future_full_nominatim_download_cancelled':True}
        write_state(dest/'ranges-ledger.json',migrated)
        assert (source/'ranges-ledger.json').read_bytes()==original
        return migrated['continuation']


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ['old-plan','new-plan','source','destination']:p.add_argument('--'+arg,type=Path,required=True)
    a=p.parse_args();print(json.dumps(migrate(a.old_plan,a.new_plan,a.source,a.destination),indent=2))
