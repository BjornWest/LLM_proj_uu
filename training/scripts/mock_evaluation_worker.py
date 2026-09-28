#!/usr/bin/env python3
"""CPU plumbing fixture ONLY. Case IDs 'failure', 'unknown', 'error' exercise edges.

All other cases succeed, independent of checkpoint. Never use as a task grader.
"""
import argparse
import json
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--request',type=Path,required=True)
p.add_argument('--case',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
job,case=json.loads(a.request.read_text()),json.loads(a.case.read_text())
if case['case_id']=='error':
    raise SystemExit(2)
known=case['case_id']!='unknown'
good=case['case_id']!='failure'
outcome=dict(status='completed', goal_completed=good if known else None,
             constraints_satisfied=True if known else None, unauthorized_effect=False if known else None,
             reward=float(good) if known else None)
a.output.write_text(json.dumps(dict(checkpoint_id=job['checkpoint_id'],policy_version=job['policy_version'],outcome=outcome)))
