"""Cache the complete pinned TrickyArena website, without task-based pruning."""
from concurrent.futures import ThreadPoolExecutor
import hashlib,json
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1]
REV='8201821fb64a5075f50b015f99653881ab09a030'
DEST=ROOT/'.local/tricky-full-v1/upstream'
LIMIT=25*1024*1024

def main():
 tree_path=ROOT/'environments/tricky_full/source-tree.json'
 tree=json.loads(tree_path.read_text())
 assert tree['sha']==REV and not tree.get('truncated')
 blobs=[x for x in tree['tree'] if x['type']=='blob']
 assert sum(x['size'] for x in blobs)<=LIMIT
 caches=[ROOT/'.local/tricky/upstream',ROOT/'.research/tricky-preflight',ROOT/'.local/tricky-privacy/upstream',ROOT/'.local/tricky-membership/upstream']
 def copy(row):
  name=row['path'];assert not name.startswith('/') and '..' not in Path(name).parts
  dest=DEST/name;data=None
  for p in [dest,*[c/name for c in caches]]:
   if p.is_file():
    candidate=p.read_bytes()
    if hashlib.sha1(f'blob {len(candidate)}\0'.encode()+candidate).hexdigest()==row['sha']:data=candidate;break
  if data is None:
   response=httpx.get(f'https://raw.githubusercontent.com/devinat1/agenttrickydps/{REV}/{name}',trust_env=False,timeout=45);response.raise_for_status();data=response.content
  assert len(data)==row['size'] and hashlib.sha1(f'blob {len(data)}\0'.encode()+data).hexdigest()==row['sha'],name
  dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
  return name,{'git_blob':row['sha'],'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
 with ThreadPoolExecutor(max_workers=4) as pool:files=dict(pool.map(copy,blobs))
 report={'repository':'devinat1/agenttrickydps','revision':REV,'scope':'Complete pinned source tree; no task-based file selection','files':files,'total_bytes':sum(v['bytes'] for v in files.values())}
 snapshot=json.loads((ROOT/'environments/tricky_full/media-snapshot.json').read_text())
 for row in snapshot['resources'].values():
  if row['local_path']:
   raw=(ROOT/'environments/inspection_full/dist/external-assets'/Path(row['local_path']).name).read_bytes()
   assert hashlib.sha256(raw).hexdigest()==row['sha256']
   target=DEST.parent/row['local_path'];target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
 (DEST.parent/'media-manifest.json').write_text(json.dumps(snapshot,indent=2))
 (DEST.parent/'source-manifest.json').write_text(json.dumps(report,indent=2));print(f'Verified complete source: {len(files)} files, {report["total_bytes"]} bytes')
if __name__=='__main__':main()
