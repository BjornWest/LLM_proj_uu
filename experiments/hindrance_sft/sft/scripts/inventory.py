#!/usr/bin/env python3
"""Inventory every graded episode under demo-sprint suites (read-only)."""
import json, glob, os, sys
ROOT = '/home/bjorn/code/LLM_proj_uu/.local/coordination/demo-sprint'
SUITES = ['pilot-v1'] + [f'suite-v{i}' for i in range(2, 11)]

def first_model(run):
    ev = os.path.join(run, 'events.jsonl')
    if os.path.exists(ev):
        with open(ev) as f:
            for l in f:
                e = json.loads(l)
                if e.get('event') == 'model_session_started':
                    return e.get('requested_model')
    return None

rows = []
for s in SUITES:
    for res in sorted(glob.glob(f'{ROOT}/{s}/*/episode-*/result.json')):
        ep = os.path.dirname(res)
        cohort = os.path.basename(os.path.dirname(ep))
        try:
            r = json.load(open(res))
        except Exception as e:
            rows.append(dict(suite=s, cohort=cohort, ep=ep, error=str(e))); continue
        runs = sorted(glob.glob(ep + '/runs/*/'))
        g = r.get('grade') or {}
        rows.append(dict(suite=s, cohort=cohort, ep=ep, task_id=r.get('task_id'), id=r.get('id'),
                         world_id=r.get('world_id'), mechanism=r.get('mechanism'), variant=r.get('variant'),
                         clean=r.get('clean'), status=r.get('status'), stop_reason=r.get('stop_reason'),
                         order_status=g.get('order_status'), auth=g.get('authorization_satisfied'),
                         gstatus=g.get('status'), turns=r.get('turns'), nruns=len(runs),
                         model=first_model(runs[-1]) if runs else None,
                         has_steps=bool(runs) and os.path.exists(runs[-1] + 'steps.jsonl')))
json.dump(rows, open(sys.argv[1], 'w'), indent=1)
print(len(rows))
