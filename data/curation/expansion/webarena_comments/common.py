"""Strictly owned full forum; independent read-only database capture."""
import json, subprocess
NAME='curation-webarena-comments-v1'
ORIGIN='http://localhost:19079'
USER='MarvelsGrantMan136'
IMAGE='am1n3e/webarena-verified-reddit@sha256:0594908059a03e5f610005689440a95c05e776e734006197c7b1eba12734cb46'
def command(*args): return subprocess.check_output(args,text=True).strip()
def inspect():
 d=json.loads(command('docker','inspect',NAME))[0]
 assert d['Config']['Labels'].get('intent.owner')=='curation-comments' and not d['Mounts']
 assert d['Config']['Image']==IMAGE
 for cp,hp in [('80/tcp','19079'),('8877/tcp','19078')]:
  assert d['HostConfig']['PortBindings'][cp]==[{'HostIp':'127.0.0.1','HostPort':hp}]
 return {k:d[k]for k in ['Id','Image','Created','Mounts']}
def sql(q):
 inspect();return command('docker','exec','--user','postgres',NAME,'psql','-v','ON_ERROR_STOP=1','-d','postmill','-Atc',q)
def rows(q): return [json.loads(s)for s in sql('SELECT row_to_json(q) FROM ('+q+')q').splitlines()if s]
def baseline():return {t:[int(s)for s in sql('SELECT id FROM '+t+' ORDER BY id').splitlines()]for t in ['submissions','comments']}
def final(initial):
 current=baseline(); ids={t:sorted(set(current[t])-set(initial[t]))for t in initial}
 posts=[];comments=[]
 if ids['submissions']:
  chosen=','.join(map(str,ids['submissions']))
  posts=rows('SELECT s.id,s.forum_id,f.name AS forum_name,s.user_id,u.username,s.title,s.body,s.url,s.visibility,s.moderated FROM submissions s JOIN forums f ON s.forum_id=f.id JOIN users u ON s.user_id=u.id WHERE s.id IN ('+chosen+') ORDER BY s.id')
 if ids['comments']:
  chosen=','.join(map(str,ids['comments']))
  comments=rows('SELECT c.id,c.submission_id,c.parent_id,c.user_id,u.username,c.body,c.visibility,c.moderated FROM comments c JOIN users u ON c.user_id=u.id WHERE c.id IN ('+chosen+') ORDER BY c.id')
 return {'posts':posts,'comments':comments,'removed_baseline_ids':{t:sorted(set(initial[t])-set(current[t]))for t in initial}}
def post_parent(id):
 assert type(id)is int
 return rows('SELECT s.id,f.name AS forum_name FROM submissions s JOIN forums f ON s.forum_id=f.id WHERE s.id='+str(id))[0]
