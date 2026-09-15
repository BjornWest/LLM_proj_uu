"""Export one public asset set for client and native views; no private grader data."""
import argparse, hashlib, json, os, shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser();p.add_argument('--build',type=Path,default=ROOT/'.local/tricky-full-v1');p.add_argument('--output',type=Path,default=ROOT/'environments/inspection_full');a=p.parse_args()
 if os.path.lexists(a.output):raise FileExistsError(a.output)
 build=json.loads((a.build/'build.json').read_text())
 assert build['full_site']
 a.output.mkdir(parents=True)
 for name,h in build['dist_sha256'].items():
  src=a.build/'dist'/name
  assert not src.is_symlink() and '..' not in Path(name).parts
  raw=src.read_bytes();assert hashlib.sha256(raw).hexdigest()==h
  dest=a.output/'dist'/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw)
 manifest={'schema_version':2,'site_revision':build['site_revision'],'source_revision':build['source']['revision'],'source_file_count':len(build['source']['files']),'full_site':True,'files':build['dist_sha256'],'scope':build['scope'],'missing_resources':build['missing_resources'],'absent_upstream_files':build['absent_upstream_files']}
 (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
 print(json.dumps({'files':len(manifest['files']),'site_revision':manifest['site_revision']}))
if __name__=='__main__':main()
