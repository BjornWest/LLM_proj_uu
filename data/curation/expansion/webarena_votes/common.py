import json,subprocess
NAME='curation-webarena-biography-v1';ORIGIN='http://localhost:19099';USER='MarvelsGrantMan136'
IMAGE='am1n3e/webarena-verified-reddit@sha256:0594908059a03e5f610005689440a95c05e776e734006197c7b1eba12734cb46'
def command(*args):return subprocess.check_output(args,text=True).strip()
def inspect():
 d=json.loads(command('docker','inspect',NAME))[0]
 assert d['Config']['Labels'].get('intent.owner')=='curation-biography' and not d['Mounts']
 assert d['HostConfig']['PortBindings']['80/tcp']==[{'HostIp':'127.0.0.1','HostPort':'19099'}]
 return {k:d[k]for k in ['Id','Image','Created','Mounts']}
def sql(query):inspect();return command('docker','exec','--user','postgres',NAME,'psql','-d','postmill','-Atc',query)
def rows(query):return [json.loads(x)for x in sql('SELECT row_to_json(q) FROM ('+query+')q').splitlines()if x]
def db_state(target):
 assert type(target)is int
 return {'target':rows(f'SELECT id,forum_id,title,timestamp,net_score FROM submissions WHERE id={target}'), 'vote':rows(f"SELECT v.submission_id,v.upvote,u.username FROM submission_votes v JOIN users u ON u.id=v.user_id WHERE v.submission_id={target} AND u.username='{USER}'"),'ui_newest':rows(f'SELECT id,timestamp,title FROM submissions WHERE forum_id=(SELECT forum_id FROM submissions WHERE id={target}) ORDER BY id DESC LIMIT 1'),'timestamp_newest':rows(f'SELECT id,timestamp,title FROM submissions WHERE forum_id=(SELECT forum_id FROM submissions WHERE id={target}) ORDER BY timestamp DESC,id DESC LIMIT 1')}
