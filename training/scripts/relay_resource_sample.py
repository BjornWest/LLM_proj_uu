#!/usr/bin/env python3
"""Relay one resource mailbox atomically with rsync, optionally over existing SSH.

No SSH setup, polling daemon or database transport. Use a process supervisor/timer
on the source host. A failed relay leaves the destination's last sample to age.
"""
import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from browser_training.outcomes import require,validate
from browser_training.monitoring_io import load_snapshot
from browser_training.publication import publication_run_id
from browser_training.monitoring_files import atomic_json


def command(source,target,host=None):
    target=str(target)
    require(target.startswith('/') and '\n' not in target and '\0' not in target,'Absolute destination directory required')
    argv=['rsync','--protect-args','--delay-updates','--timeout=15','--chmod=F600']
    if host:
        require(re.fullmatch(r'(?:[A-Za-z0-9_-]+@)?[A-Za-z0-9][A-Za-z0-9.-]*',host) is not None,'Use a plain SSH host or user@host')
        argv+=['-e','ssh -oBatchMode=yes -oConnectTimeout=5']
    return [*argv,'--',str(source),f'{host+":" if host else ""}{target.rstrip("/")}/']


def relay(source,identity_snapshot,target,*,host=None,dry_run=False):
    envelope=json.loads(Path(source).read_text())
    value=load_snapshot(identity_snapshot)
    require(set(envelope) in ({'run_id','synthetic','event'}, {'run_id','synthetic','event','publication_run_id'}),
            'Resource envelope only; do not relay snapshots/databases here')
    require(envelope['run_id']==value['run_id'] and envelope['synthetic'] is value['synthetic'] and
            envelope.get('publication_run_id',envelope['run_id'])==publication_run_id(value),'Source execution mismatch')
    event=envelope['event'];validate(event)
    role=event['producer']
    require(event['kind']=='telemetry' and role in {'browser','trainer','rollout'},'Resource event required')
    with tempfile.TemporaryDirectory(prefix='resource-relay-') as temporary:
        sample=Path(temporary)/f'{role}.json'
        atomic_json(sample,envelope)
        argv=command(sample,target,host)
        if not dry_run:
            subprocess.run(argv,check=True,capture_output=True,timeout=25)
        return dict(role=role,event_id=event['id'],publication_run_id=publication_run_id(value),
                    destination_host=host,transport='rsync-ssh' if host else 'rsync-local',dry_run=dry_run,
                    note='Receiver validates against its current snapshot; SSH network delivery requires host qualification.')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sample',required=True,type=Path)
    p.add_argument('--identity-snapshot',required=True,type=Path,help='Copied immutable snapshot from the receiving execution')
    p.add_argument('--target',required=True,help='Existing absolute monitoring/resources directory on receiver')
    p.add_argument('--ssh-host')
    p.add_argument('--dry-run',action='store_true')
    a=p.parse_args()
    print(json.dumps(relay(a.sample,a.identity_snapshot,a.target,host=a.ssh_host,dry_run=a.dry_run),indent=2))
