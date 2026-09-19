"""Inspect completed tile TAR headers and PostgreSQL control data, read-only.

Does not restore/start PostgreSQL, create Docker volumes, or download anything.
The full archive hash is attributed to the completed downloader; this audit reads
all headers and selected small control files, not all file payloads.
"""
import argparse,hashlib,json,subprocess,tarfile
from collections import Counter
from pathlib import Path
from data.curation.expansion.prepare_map_volumes import member_allowed
ROOT=Path(__file__).resolve().parents[3]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def identity(p):
 s=p.stat();return [s.st_dev,s.st_ino,s.st_size,s.st_mtime_ns,s.st_ctime_ns]
def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 planpath=ROOT/'data/curation/expansion/map-setup-plan-v2.json';plan=json.loads(planpath.read_text());volume=next(v for v in plan['volumes'] if v['source_archive']=='osm_tile_server.tar')
 directory=ROOT/'.local/curation-expansion/downloads-static-v2';ledgerpath=directory/'ranges-ledger.json';ledger=json.loads(ledgerpath.read_text());asset=ledger['assets']['osm_tile_server.tar']
 assert asset['status']=='complete';archivepath=directory/'osm_tile_server.tar';before=identity(archivepath);assert before[2]==asset['expected_bytes']
 rows=[];counts=Counter();small={};prefix=volume['source_prefix'];header_hash=hashlib.sha256()
 with tarfile.open(archivepath,'r:') as archive:
  for m in archive:
   selected=member_allowed(m,prefix);counts['all_members']+=1
   row={'name':m.name,'size':m.size,'type':m.type.decode(),'offset':m.offset,'selected':selected}
   header_hash.update(json.dumps(row,sort_keys=True).encode()+b'\n')
   if selected:
    counts['selected_members']+=1;counts['selected_payload_bytes']+=m.size;rows.append(row)
    rel=str(Path(m.name).relative_to(prefix))
    if rel.startswith('postgres/') and rel.removeprefix('postgres/') in ('PG_VERSION','global/pg_control','postmaster.pid','backup_label','backup_manifest'):
     rel=rel.removeprefix('postgres/')
     assert m.isfile() and m.size<1024*1024
     data=archive.extractfile(m).read();out=a.output/'control'/rel;out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(data)
     small[rel]={'path':str(out),'sha256':sha(out),'bytes':len(data)}
 assert identity(archivepath)==before
 assert (a.output/'control/PG_VERSION').read_text().strip()=='15'
 assert 'global/pg_control' in small
 image=plan['image'];argv=['docker','run','--rm','--pull','never','--network','none','--memory','256m','--cpus','1','--entrypoint','/usr/lib/postgresql/15/bin/pg_controldata','--mount','type=bind,source='+str((a.output/'control').resolve())+',target=/audit,readonly',image,'/audit']
 command=subprocess.run(argv,capture_output=True,text=True,check=True)
 (a.output/'pg_controldata.txt').write_text(command.stdout);(a.output/'pg_controldata.stderr.txt').write_text(command.stderr)
 fields=dict(line.split(':',1) for line in command.stdout.splitlines() if ':' in line);fields={k:v.strip() for k,v in fields.items()}
 result={'schema':'map-tile-archive-header-control-audit-v2','plan_sha256':sha(planpath),'image':image,'archive':str(archivepath),'archive_identity':before,'downloader_reported_sha256':asset['sha256'],'full_payload_rehashed_in_this_audit':False,'header_records_sha256':header_hash.hexdigest(),'counts':dict(counts),'small_files':small,'pg_control':fields,'pg_control_argv':argv,'stderr_sha256':sha(a.output/'pg_controldata.stderr.txt'),'control_output_sha256':sha(a.output/'pg_controldata.txt'),'audit_script_sha256':sha(Path(__file__)),'site_ready':False,'task_acceptance':False,'database_started':False,'downloads':0,'model_calls':0}
 (a.output/'inventory.json').write_text(json.dumps(rows,indent=2)+'\n');result['inventory_sha256']=sha(a.output/'inventory.json')
 (a.output/'report.json').write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps({'counts':dict(counts),'postgres_state':fields.get('Database cluster state'),'postgres_version':15,'stderr':command.stderr,'site_ready':False}))
if __name__=='__main__':main()
