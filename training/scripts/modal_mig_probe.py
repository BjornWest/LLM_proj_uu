#!/usr/bin/env python3
"""Read-only RTX PRO MIG availability probe. Never changes GPU configuration."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import re
import subprocess
import time
import xml.etree.ElementTree as ET

import modal

SOURCE = Path(__file__).resolve()
ROOT = SOURCE.parents[1]
image = (modal.Image.debian_slim(python_version='3.12')
    .env({'PYTHONPATH': '/opt/probe'})
    .add_local_file(SOURCE, '/opt/probe/modal_mig_probe.py'))
app = modal.App('browser-training-rtx-mig-probe', image=image, include_source=False)


def classify(xml, listing, cap_eff):
    """Fail closed: physical support alone is not usable MIG access."""
    tree = ET.fromstring(xml)
    gpus = []
    for gpu in tree.findall('gpu'):
        gpus.append({'name': gpu.findtext('product_name'),
            'uuid': gpu.findtext('uuid'), 'mig_mode': gpu.findtext('mig_mode/current_mig')})
    ids = re.findall(r'\(UUID: (MIG-[^)]+)\)', listing)
    admin = bool(int(cap_eff, 16) & (1 << 21))
    enabled = any(g['mig_mode'] == 'Enabled' for g in gpus)
    available = enabled and len(set(ids)) >= 2
    return {'gpus': gpus, 'mig_uuids': list(dict.fromkeys(ids)),
        'cap_sys_admin': admin, 'two_mig_devices_exposed': available,
        'status': 'NEEDS_CUDA_CHECK' if available else 'ABORT_MIG_UNAVAILABLE',
        'reason': ('Two enabled MIG devices are exposed; CUDA access still needs checking.' if available else
            'Fewer than two enabled MIG devices are exposed. No GPU reconfiguration attempted.'),
        'driver': tree.findtext('driver_version')}


@app.function(gpu='RTX-PRO-6000', cpu=1, memory=1024, timeout=45,
              startup_timeout=30, max_containers=1, retries=0, scaledown_window=2)
def probe(deadline):
    if time.time() >= deadline:
        raise RuntimeError('Probe deadline expired')
    started = time.time()
    commands = {}
    for name, argv in [('xml', ['nvidia-smi','-q','-x']),
                       ('devices', ['nvidia-smi','-L']),
                       ('profiles', ['nvidia-smi','mig','-lgip']),
                       ('instances', ['nvidia-smi','mig','-lgi'])]:
        remaining = min(5, deadline-time.time())
        if remaining <= 0:
            raise TimeoutError('Probe deadline expired')
        result = subprocess.run(argv, capture_output=True, text=True, timeout=remaining)
        commands[name] = {'command': argv, 'returncode': result.returncode,
            'stdout': result.stdout, 'stderr': result.stderr}
    status_text = Path('/proc/self/status').read_text()
    cap = re.search(r'^CapEff:\s+(\w+)', status_text, re.MULTILINE).group(1)
    if commands['xml']['returncode'] == 0 and commands['devices']['returncode'] == 0:
        report = classify(commands['xml']['stdout'], commands['devices']['stdout'], cap)
    else:
        report = {'status': 'ABORT_MIG_UNAVAILABLE', 'reason': 'NVIDIA inspection commands failed'}
    report.update(commands=commands, elapsed_seconds=time.time()-started,
        configuration_changed=False, training_started=False, model_downloads=False)
    if report.get('two_mig_devices_exposed'):
        # Each interpreter sees one MIG UUID, just as the independent processes
        # in the proposed trainer/server topology would. No CUDA allocations.
        code = '''
import ctypes,json
c=ctypes.CDLL('libcuda.so.1')
assert c.cuInit(0)==0
n=ctypes.c_int(); assert c.cuDeviceGetCount(ctypes.byref(n))==0 and n.value==1
d=ctypes.c_int(); assert c.cuDeviceGet(ctypes.byref(d),0)==0
size=ctypes.c_size_t(); assert c.cuDeviceTotalMem_v2(ctypes.byref(size),d)==0
name=ctypes.create_string_buffer(256); assert c.cuDeviceGetName(name,256,d)==0
print(json.dumps(dict(name=name.value.decode(),memory_gib=size.value/2**30)))
'''
        report['cuda_devices'] = []
        for uuid in report['mig_uuids'][:2]:
            done = subprocess.run(['python','-c',code], capture_output=True, text=True,
                env=dict(os.environ,CUDA_VISIBLE_DEVICES=uuid), timeout=min(5,max(0.1,deadline-time.time())))
            result = {'uuid':uuid,'returncode':done.returncode,'stdout':done.stdout,'stderr':done.stderr}
            if done.returncode == 0:
                result.update(json.loads(done.stdout))
            report['cuda_devices'].append(result)
        ready = all(d['returncode']==0 and d.get('memory_gib',0)>=40 for d in report['cuda_devices'])
        report['status'] = 'MIG_ACCESS_READY' if ready else 'ABORT_MIG_UNUSABLE'
        report['reason'] = ('Two independent CUDA-visible slices of at least 40 GiB verified; model/kernels untested.'
            if ready else 'Exposed MIG devices failed independent CUDA access or capacity checks.')
    report['elapsed_seconds'] = time.time()-started
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dry-run',action='store_true')
    args=p.parse_args()
    if args.dry_run:
        print(json.dumps({'gpu':'RTX-PRO-6000','count':1,'client_deadline_seconds':90,
            'function_timeout_seconds':45,'configuration_changes':False,'downloads':False}))
        return
    from dotenv import dotenv_values
    for key,value in dotenv_values(ROOT.parent/'.env').items():
        if key in ('MODAL_TOKEN_ID','MODAL_TOKEN_SECRET') and value:
            os.environ.setdefault(key,value)
    if not all(os.environ.get(k) for k in ('MODAL_TOKEN_ID','MODAL_TOKEN_SECRET')):
        raise SystemExit('Modal token pair missing from project .env')
    output=ROOT/'outputs/modal'/time.strftime('rtx-mig-%Y%m%d-%H%M%S')
    output.mkdir(parents=True)
    (output/'source.py').write_bytes(SOURCE.read_bytes())
    with modal.enable_output(), app.run():
        deadline=time.time()+90
        call=probe.spawn(deadline)
        (output/'app.json').write_text(json.dumps({'app_id':app.app_id,'call_id':call.object_id,
            'url':app.get_dashboard_url(),'deadline':deadline}))
        try:
            report=call.get(timeout=max(1,deadline-time.time()))
            (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
            print(json.dumps({k:v for k,v in report.items() if k!='commands'},indent=2))
        finally:
            call.cancel(terminate_containers=True)
    print('Artifacts:',output)


if __name__=='__main__':
    main()
