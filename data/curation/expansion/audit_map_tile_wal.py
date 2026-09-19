"""Read a copied checkpoint WAL segment; no database startup or recovery writes."""
import argparse,hashlib,json,subprocess,tarfile
from pathlib import Path
from data.curation.expansion.audit_map_tile_archive import identity
ROOT=Path(__file__).resolve().parents[3]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser();p.add_argument('--control-report',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 r=json.loads(a.control_report.read_text());archivepath=Path(r['archive']);assert identity(archivepath)==r['archive_identity']
 wal=r['pg_control']["Latest checkpoint's REDO WAL file"];redo=r['pg_control']["Latest checkpoint's REDO location"]
 assert len(wal)==24 and all(c in '0123456789ABCDEF' for c in wal)
 target='projects/ogma3/docker/volumes/osm-data/_data/postgres/pg_wal/'+wal
 with tarfile.open(archivepath,'r:') as archive:
  member=archive.getmember(target);assert member.isfile() and member.size==16777216
  data=archive.extractfile(member).read();(a.output/wal).write_bytes(data)
 assert identity(archivepath)==r['archive_identity']
 argv=['docker','run','--rm','--pull','never','--network','none','--memory','256m','--cpus','1','--entrypoint','/usr/lib/postgresql/15/bin/pg_waldump','--mount','type=bind,source='+str(a.output.resolve())+',target=/audit,readonly',r['image'],'--path=/audit','--start='+redo,'--limit=5']
 run=subprocess.run(argv,capture_output=True,text=True)
 (a.output/'stdout.txt').write_text(run.stdout);(a.output/'stderr.txt').write_text(run.stderr)
 result={'schema':'map-tile-checkpoint-wal-audit-v1','control_report':str(a.control_report),'control_report_sha256':sha(a.control_report),'archive_identity_unchanged':True,'wal_segment':wal,'segment_sha256':sha(a.output/wal),'redo_location':redo,'argv':argv,'returncode':run.returncode,'stdout_sha256':sha(a.output/'stdout.txt'),'stderr_sha256':sha(a.output/'stderr.txt'),'record_lines':len(run.stdout.splitlines()),'database_started':False,'site_ready':False,'task_acceptance':False,'model_calls':0,'downloads':0,'script_sha256':sha(Path(__file__)),'limitation':'Five records from retained checkpoint segment only. Does not establish full recovery, consistency of all database pages or service readiness.'}
 (a.output/'report.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps({'returncode':run.returncode,'record_lines':result['record_lines'],'stderr':run.stderr,'site_ready':False}))
 raise SystemExit(run.returncode)
if __name__=='__main__':main()
