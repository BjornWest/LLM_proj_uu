"""Deterministic configuration coverage and ordinary saved-task preparation.

Candidate pools are explicit, finite supported configurations. Covered pairs
are measured against that pool, never against every possible task/world.
"""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from hashlib import sha256
from itertools import combinations
import json
import os
from pathlib import Path
from random import Random
import time

VERSION = 'website-task-compatibility-sweep-v1'


def _json(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False,
                      allow_nan=False, separators=(',', ':'))


def _token(name, value):
    return (name, _json(value))


def interactions(factors, strength=2):
    if type(factors) is not dict or any(type(k) is not str or not k for k in factors):
        raise ValueError('Factors require named JSON values')
    if type(strength) is not int or strength not in (1, 2, 3):
        raise ValueError('Coverage strength must be1,2 or3')
    values = sorted(_token(k, v) for k, v in factors.items())
    return set(combinations(values, strength))


def select_cases(candidates, *, limit=200, seed=0, triples=()):
    """Greedy applicable-pair coverage, targeted triples, then seeded diversity."""
    if type(limit) is not int or limit < 1 or type(seed) is not int:
        raise ValueError('Declare finite positive case limit and integer seed')
    if type(candidates) is not list or not candidates:
        raise ValueError('Declare a finite nonempty candidate pool')
    ids, fingerprints = set(), set()
    for row in candidates:
        if type(row) is not dict or set(row) != {'id', 'factors', 'instance'}:
            raise ValueError('Each candidate needs id, factors and instance')
        if type(row['id']) is not str or not row['id'] or row['id'] in ids:
            raise ValueError('Candidate IDs must be unique nonempty strings')
        ids.add(row['id']);_json(row['instance']);interactions(row['factors'])
        # Wording-only copies must not inflate native configuration diversity.
        instance = {k:v for k,v in row['instance'].items() if k != 'user_message'}
        fingerprint = _json(instance)
        if fingerprint in fingerprints:
            raise ValueError('Duplicate semantic/preparation configuration')
        fingerprints.add(fingerprint)
    triples = list(triples)
    if any(type(t) not in (list, tuple) or len(t)!=3 or len(set(t))!=3 for t in triples):
        raise ValueError('Targeted triples require three distinct factor names')
    scores = []
    for row in candidates:
        pairs = interactions(row['factors'])
        targeted = set()
        for names in triples:
            if all(name in row['factors'] for name in names):
                targeted |= interactions({name:row['factors'][name] for name in names},3)
        scores.append((pairs, targeted))
    all_pairs = set().union(*(x[0] for x in scores))
    all_triples = set().union(*(x[1] for x in scores))
    remaining_pairs, remaining_triples = set(all_pairs), set(all_triples)
    random = Random(seed)
    order = list(range(len(candidates)));random.shuffle(order)
    chosen = []
    while order and len(chosen)<limit:
        best = max(order,key=lambda i:len(scores[i][0]&remaining_pairs)+
                   3*len(scores[i][1]&remaining_triples))
        gain = len(scores[best][0]&remaining_pairs)+len(scores[best][1]&remaining_triples)
        if not gain:
            chosen.extend(order[:limit-len(chosen)]);break
        chosen.append(best);order.remove(best)
        remaining_pairs-=scores[best][0];remaining_triples-=scores[best][1]
    covered_pairs = set().union(*(scores[i][0] for i in chosen))
    covered_triples = set().union(*(scores[i][1] for i in chosen))
    encode = lambda values: [[list(pair) for pair in x] for x in sorted(values)]
    return {'schema':VERSION, 'seed':seed, 'requested_limit':limit,
            'candidate_pool_sha256':sha256(_json(candidates).encode()).hexdigest(),
            'candidate_count':len(candidates), 'selected':deepcopy([candidates[i] for i in chosen]),
            'coverage':{'scope':'explicit_supported_candidate_pool',
                        'applicable_pairs':len(all_pairs),'covered_pairs':len(covered_pairs),
                        'uncovered_pairs':encode(all_pairs-covered_pairs),
                        'targeted_triples':len(all_triples),'covered_triples':len(covered_triples),
                        'uncovered_triples':encode(all_triples-covered_triples)}}


def compact_prepared(directory, store):
    """Share exact finished immutable preparation bytes, without mocking freeze.

    Hardlinks preserve every file/path/byte. They do not enforce immutability;
    ordinary manifest/source hash checks remain mandatory before consumption.
    Only a completed fresh preparation may be supplied, never a run directory.
    """
    directory,store=Path(directory).resolve(),Path(store).resolve()
    if not (directory/'prepared-instance.json').is_file():
        raise ValueError('Only completed task-instance preparations can be compacted')
    if directory==store or store.is_relative_to(directory) or directory.is_relative_to(store):
        raise ValueError('Keep the immutable store separate from the prepared recipe')
    store.mkdir(parents=True,exist_ok=True)
    reused=0;shared=0
    for path in directory.rglob('*'):
        if path.is_symlink():
            raise ValueError('Prepared compaction does not admit symbolic links')
        if not path.is_file():continue
        payload=path.read_bytes();digest=sha256(payload).hexdigest();target=store/digest
        try:os.link(path,target)
        except FileExistsError:
            if target.is_symlink() or not target.is_file() or sha256(target.read_bytes()).hexdigest()!=digest:
                raise ValueError('Immutable content store entry changed')
        if path.stat().st_ino!=target.stat().st_ino:
            # Unique same-directory temporary name; atomic replacement never
            # overwrites another case's path or changes the linked bytes.
            temporary=path.with_name(path.name+'.share-'+str(os.getpid()))
            os.link(target,temporary)
            try:os.replace(temporary,path)
            finally:
                if temporary.exists():temporary.unlink()
            reused+=len(payload)
        shared+=1
    return {'files':shared,'reused_duplicate_bytes':reused,
            'source_freeze_was_mocked':False,'hardlinks_enforce_immutability':False}


def run_native(selection, output, *, workers=2, prepare=False, share_assets=False):
    """Use actual constructors/readers and optional real freezer; retain failures.

    No monkeypatched source collection, producer or reference is used here.
    This stage runs no browsers/models. Parallel cases have separate outputs.
    """
    from . import task_instances
    if (type(workers) is not int or not 1<=workers<=4 or type(prepare) is not bool
            or type(share_assets) is not bool or share_assets and not prepare):
        raise ValueError('Use1-4 workers and explicit preparation Boolean')
    if selection.get('schema')!=VERSION or not isinstance(selection.get('selected'),list):
        raise ValueError('Use a selected compatibility case set')
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=False)
    (output/'selection.json').write_text(json.dumps(selection,indent=2,ensure_ascii=False,allow_nan=False)+'\n')

    def one(index,row):
        # Opaque candidate labels never become filesystem paths.
        directory=output/f'{index:04d}';directory.mkdir()
        (directory/'instance.json').write_text(json.dumps(row['instance'],indent=2,ensure_ascii=False,allow_nan=False)+'\n')
        result={'id':row['id'],'factors':deepcopy(row['factors']),'stages':{},
                'browser':'not_run','model_calls':0,'started_monotonic':time.monotonic()}
        stage='native_inspection'
        try:
            native=task_instances.inspect(row['instance'])
            result['stages'][stage]={'status':'passed','task_id':native['task']['task_id'],
                                     'metrics':native['metrics']}
            for name in ('task','reference','setup'):
                (directory/(name+'.json')).write_text(json.dumps(native[name],indent=2,ensure_ascii=False,allow_nan=False)+'\n')
            if prepare:
                stage='unmocked_preparation'
                receipt=task_instances.prepare(row['instance'],directory/'prepared')
                result['stages'][stage]={'status':'passed','receipt':receipt}
                if share_assets:
                    result['shared_immutable_assets']=compact_prepared(directory/'prepared',output/'immutable-files')
            result['status']='passed'
        except Exception as error:
            # A ValueError may be unsupported notation, no saved witness, or
            # infrastructure binding drift. Do not guess from English text.
            result['status']='requires_triage'
            result['stages'][stage]={'status':'error','exception_class':type(error).__name__,
                                     'message':str(error)}
        result['duration_seconds']=round(time.monotonic()-result.pop('started_monotonic'),3)
        (directory/'result.json').write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
        return result

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(one,i,row) for i,row in enumerate(selection['selected'])]
        results=[future.result() for future in futures]
    report={'schema':VERSION,'selection_sha256':sha256(_json(selection).encode()).hexdigest(),
            'configuration_count':len(results),'passed':sum(x['status']=='passed' for x in results),
            'requires_triage':sum(x['status']=='requires_triage' for x in results),
            'results':results,'design_coverage':selection['coverage'],'browsers':0,'models':0,
            'limitations':['Native/preparation acceptance does not establish browser/automatic-grade/HTTP acceptance.',
                           'Coverage is measured against the finite declared candidate pool only.']}
    attempted=set().union(*(interactions(row['factors']) for row in results))
    native_passed=set().union(*(interactions(row['factors']) for row in results
                               if row['stages'].get('native_inspection',{}).get('status')=='passed'))
    prepared=set().union(*(interactions(row['factors']) for row in results
                          if row['stages'].get('unmocked_preparation',{}).get('status')=='passed'))
    report['observed_stage_pair_coverage']={
        'native_inspection':{'attempted_pairs':len(attempted),'passed_pairs':len(native_passed)},
        'unmocked_preparation':{'attempted_pairs':len(attempted) if prepare else 0,'passed_pairs':len(prepared)}}
    (output/'report.json').write_text(json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
    return report
