"""Snapshot original public media URLs; retain failures rather than invent assets."""
from concurrent.futures import ThreadPoolExecutor
import hashlib,json,re,threading
from pathlib import Path
from urllib.parse import urlparse
import httpx
ROOT=Path(__file__).resolve().parents[1];LOCAL=ROOT/'.local/tricky-full-v1';OUT=LOCAL/'media';LIMIT=64*1024*1024

def main():
 OUT.mkdir(exist_ok=True);urls={}
 for p in (LOCAL/'upstream/src').rglob('*'):
  if p.suffix not in ('.jsx','.js','.css'):continue
  for u in re.findall(r'[\'\"](https?://[^\'\"\s<>]+)[\'\"]',p.read_text()):
   h=urlparse(u).hostname or ''
   if any(x in h for x in ['bensound','unsplash','ui-avatars','duckduckgo','freebiesupply','thefamouspeople','jewishnews','discogs']) or re.search(r'\.(?:png|jpe?g|gif|webp|mp3|ogg)(?:\?|$)',u):urls.setdefault(u,[]).append(str(p.relative_to(LOCAL/'upstream')))
 lock=threading.Lock();used=0
 old=json.loads((LOCAL/'media-manifest.json').read_text())['resources'] if (LOCAL/'media-manifest.json').exists() else {}
 def get(item):
  nonlocal used
  u,sources=item
  if u in old:return u,old[u]
  record={'url':u,'sources':sources,'status':None,'local_path':None}
  try:
   with httpx.stream('GET',u,follow_redirects=True,trust_env=False,timeout=25,headers={'User-Agent':'Mozilla/5.0'}) as r:
    record.update(status=r.status_code,resolved_url=str(r.url),content_type=r.headers.get('content-type','').split(';')[0])
    if r.status_code!=200:return u,record
    if not record['content_type'].startswith(('image/','audio/')):record['error']='Expected image/audio response';return u,record
    parts=[];size=0
    for b in r.iter_bytes():
     size+=len(b)
     with lock:
      used+=len(b)
      if used>LIMIT:raise ValueError('64 MiB total media download ceiling reached')
     if size>12*1024*1024:raise ValueError('12 MiB per-media ceiling reached')
     parts.append(b)
    data=b''.join(parts);suffix={'image/jpeg':'.jpg','image/png':'.png','image/webp':'.webp','image/svg+xml':'.svg','audio/mpeg':'.mp3','audio/mp3':'.mp3','image/gif':'.gif'}.get(record['content_type'],'.bin')
    name=hashlib.sha256(u.encode()).hexdigest()+suffix;(OUT/name).write_bytes(data)
    record.update(local_path='media/'+name,sha256=hashlib.sha256(data).hexdigest(),bytes=len(data))
  except Exception as e:record['error']=f'{type(e).__name__}: {e}'
  return u,record
 with ThreadPoolExecutor(max_workers=4) as pool:resources=dict(pool.map(get,urls.items()))
 report={'schema_version':1,'scope':'Snapshots of exact media URLs present in pinned source; failed requests are not substituted','resources':resources}
 (LOCAL/'media-manifest.json').write_text(json.dumps(report,indent=2));print(json.dumps({'resources':len(resources),'cached':sum(bool(r['local_path']) for r in resources.values()),'bytes':sum(r.get('bytes',0) for r in resources.values()),'failures':[(u,r['status'],r.get('error')) for u,r in resources.items() if not r['local_path']]},indent=2))
if __name__=='__main__':main()
