"""Read-only audit of saved shared-browser container acceptance, no model/browser."""
import hashlib,json,sys,zipfile
from pathlib import Path
root=Path(sys.argv[1]);report=json.loads((root/'report.json').read_text());checks=files=0
for case in report['cases']:
    archive=root/case['archive'];data=archive.read_bytes()
    assert hashlib.sha256(data).hexdigest()==case['archive_sha256'];checks+=1
    directory=Path(case['trace'])
    originals={str(p.relative_to(directory.parent)):p for p in directory.rglob('*') if p.is_file() and not p.is_symlink() and not p.name.endswith('.tmp')}
    with zipfile.ZipFile(archive) as z:
        assert len(z.namelist())==len(set(z.namelist()));assert set(z.namelist())==set(originals);checks+=2
        for name,p in originals.items():assert z.read(name)==p.read_bytes();files+=1
    episode=json.loads((directory/'episode.json').read_text());assert episode['evaluation'] is None and episode['model_attempt_count']==2;checks+=1
    steps=[json.loads(line) for line in (directory/'steps.jsonl').read_text().splitlines()]
    assert [s['actor'] for s in steps]==['scripted_validation','agent','scripted_validation'];checks+=1
    turn=json.loads(next(directory.glob('ask-*.json')).read_text());assert turn['status']=='complete' and turn['evaluation'] is None;checks+=1
    for step in turn['steps']:
        assert step['request']['messages']==step['decision']['messages'];assert step['request']['session_id']==case['id']
        assert json.loads(step['response_text'])==step['response'];assert step['usage']['cost']==0.0001;assert step['reservation']['amount_usd']>0;checks+=5
    events=[json.loads(line)['event'] for line in (directory/'events.jsonl').read_text().splitlines()]
    assert events.index('evaluation_completed')<events.index('environment_close_started');checks+=1
print(json.dumps({'passed':True,'cases':len(report['cases']),'checks':checks,'exact_original_files':files,'report_sha256':hashlib.sha256((root/'report.json').read_bytes()).hexdigest(),'model_calls':0}))
