"""Bind Prislyktan/current-worker acceptance to observed, unchanged sources.

Requires positive/negative original-task checks and six original Prislyktan
goals. No model, browser or deployed service access. Historical failures stay
outside the selected passing evidence rather than being overwritten.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--report',type=Path,action='append',required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists() or a.output.is_symlink():raise FileExistsError(a.output)
    import sys
    sys.path.insert(0,str(ROOT))
    from intent_browser.hosted_tasks import registry
    from intent_browser.prislyktan import catalog
    wanted={(r['id'],n,False) for r in registry()['tasks'] for n in (False,True)}
    wanted|={(r['id'],False,False) for r in catalog()}
    wanted|={('prislyktan:AG01',True,False),('prislyktan:AG06',True,False),('tricky-p07-clean',False,True)}
    cases={}
    source=None
    for path in a.report:
        value=json.loads(path.read_text())
        if value.get('passed') is not True or value.get('model_calls')!=0 or not all(value['checks'].values()):
            raise ValueError('Passing zero-model acceptance required')
        key=(value['task'],value['negative'],value['backend_failure'])
        if key in cases:raise ValueError('Duplicate case')
        cases[key]={'path':str(path),'sha256':sha(path)}
        if source is None:source=value['source_sha256']
        if value['source_sha256']!=source:raise ValueError('Mixed source closures')
        directory=ROOT/value['trace']
        for name,expected in value['artifact_sha256'].items():
            item=(directory/name).resolve()
            if not item.is_relative_to(directory.resolve()) or sha(item)!=expected:raise ValueError('Artifact changed')
    if set(cases)!=wanted:raise ValueError('Incomplete or extra acceptance coverage')
    for name,expected in source.items():
        path=(ROOT/name).resolve()
        if not path.is_relative_to(ROOT) or sha(path)!=expected:raise ValueError('Accepted source changed: '+name)
    result={'schema':'prislyktan-worker-acceptance-v1','source_sha256':source,
            'tasks':{r['id']:r['revision'] for r in catalog()},'acceptance':list(cases.values()),
            'scope':'Current worker scripted dispatch and publication; not model capability or exposure certification',
            'model_calls':0,'training_eligible':False}
    with a.output.open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps({'cases':len(cases),'sha256':sha(a.output)}))

if __name__=='__main__':main()
