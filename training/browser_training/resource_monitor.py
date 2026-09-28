"""Linux process-tree + explicitly selected NVIDIA device samples. No torch import.

CPU is a delta over surviving process identities, not host load. PSS apportions
shared pages; it is not RSS or device memory. Short-lived processes between polls
are not observed. Missing/partial measurements remain unavailable.
"""
import csv
import io
import json
import math
import os
from pathlib import Path
import socket
import subprocess
import time
import uuid

from .outcomes import require, validate
from .publication import publication_run_id


def proc_stat(path):
    # comm can contain spaces and parentheses; fields after its LAST ')' are fixed.
    fields = path.read_text().rsplit(')', 1)[1].split()
    return dict(ppid=int(fields[1]), ticks=int(fields[11]) + int(fields[12]), start=int(fields[19]))


def process_tree(root_pid, root_start, proc=Path('/proc')):
    records = {}
    for path in proc.glob('[0-9]*/stat'):
        try:
            records[int(path.parent.name)] = proc_stat(path)
        except (OSError, ValueError, IndexError):
            continue
    require(root_pid in records and records[root_pid]['start'] == root_start, 'root_exited_or_reused')
    selected = {root_pid}
    while True:
        children = {pid for pid, row in records.items() if row['ppid'] in selected}
        if children <= selected:
            break
        selected |= children
    memory = 0
    complete = True
    for pid in selected:
        try:
            pss = next(line for line in (proc / str(pid) / 'smaps_rollup').read_text().splitlines()
                       if line.startswith('Pss:'))
            memory += int(pss.split()[1]) * 1024
            require(proc_stat(proc / str(pid) / 'stat')['start'] == records[pid]['start'], 'pid_reused')
        except (OSError, ValueError, StopIteration, IndexError):
            complete = False
    return {(pid, records[pid]['start']): records[pid]['ticks'] for pid in selected}, memory if complete else None


def gpu_sample(device, runner=subprocess.run):
    """nvidia-smi physical ID/UUID, NOT CUDA_VISIBLE_DEVICES-remapped ordinal."""
    keys = ('gpu_utilization_pct', 'vram_gib')
    try:
        result = runner(['nvidia-smi', '-i', str(device),
                         '--query-gpu=uuid,utilization.gpu,memory.used', '--format=csv,noheader,nounits'],
                        capture_output=True, text=True, timeout=5, check=True)
        rows = list(csv.reader(io.StringIO(result.stdout)))
        require(len(rows) == 1 and len(rows[0]) == 3, 'ambiguous_device')
        identity, utilization, memory = [part.strip() for part in rows[0]]
        require(identity.startswith('GPU-'), 'unsupported_device_scope')
        values, missing = {}, {}
        for key, raw, divisor, maximum in zip(keys, (utilization, memory), (1, 1024), (100, None)):
            try:
                value = float(raw) / divisor
                require(math.isfinite(value) and value >= 0 and (maximum is None or value <= maximum), 'invalid_reading')
                values[key] = value
            except ValueError:
                missing[key] = 'unsupported_or_invalid_reading'
        return values, missing, identity
    except (OSError, subprocess.SubprocessError, ValueError):
        # Never log subprocess stderr/environment: it is not needed to diagnose absence.
        return {}, {key: 'device_query_failed' for key in keys}, None


class ResourceSampler:
    def __init__(self, *, role, root_pid=None, device=None, proc=Path('/proc')):
        require(role in {'browser', 'trainer', 'rollout'}, 'Unknown resource role')
        require(root_pid is not None or device is not None, 'Select a process root and/or a device')
        require(role != 'browser' or device is None, 'Browser role has no GPU metrics')
        require(device is None or not str(device).startswith('MIG-'), 'MIG instance monitoring not qualified')
        self.role, self.root_pid, self.device, self.proc = role, root_pid, device, Path(proc)
        self.start = None if root_pid is None else proc_stat(self.proc / str(root_pid) / 'stat')['start']
        self.previous, self.previous_at = None, None
        self.session, self.step = uuid.uuid4().hex, 0
        self.ticks_per_s = os.sysconf('SC_CLK_TCK')

    def sample(self, *, now=None, monotonic=None):
        now = time.time() if now is None else now
        monotonic = time.monotonic() if monotonic is None else monotonic
        values, unavailable = {}, {}
        context = dict(source='linux-resource-sampler-v1', host=socket.gethostname(), role=self.role,
                       root_pid=self.root_pid, root_start_ticks=self.start,
                       scope='root process + observed descendants; CPU surviving identities; memory PSS')
        if self.root_pid is not None:
            try:
                current, memory = process_tree(self.root_pid, self.start, self.proc)
                context['observed_processes'] = len(current)
                if memory is None:
                    unavailable['ram_gib'] = 'partial_or_denied_pss'
                else:
                    values['ram_gib'] = memory / 1024**3
                if self.previous is None or monotonic <= self.previous_at:
                    unavailable['cpu_cores'] = 'needs_two_samples'
                else:
                    elapsed = monotonic - self.previous_at
                    context['cpu_interval_s'] = elapsed
                    context['new_processes'] = len(current.keys() - self.previous.keys())
                    context['departed_processes'] = len(self.previous.keys() - current.keys())
                    values['cpu_cores'] = sum(max(0, ticks - self.previous[key]) for key, ticks in current.items()
                                               if key in self.previous) / self.ticks_per_s / elapsed
                self.previous, self.previous_at = current, monotonic
            except ValueError:
                unavailable.update(cpu_cores='root_exited_or_reused', ram_gib='root_exited_or_reused')
                self.previous = None
        if self.device is not None:
            gpu, missing, identity = gpu_sample(self.device)
            values.update(gpu)
            unavailable.update(missing)
            context.update(device_selector=str(self.device), gpu_uuid=identity, gpu_scope='whole physical device')
        event = dict(id=f'resource-{self.session}-{self.step}', kind='telemetry', producer=self.role,
                     occurred_at=now, payload=dict(step=self.step, axis='measurement', policy_version=None,
                     checkpoint_id=None, context=json.dumps(context, sort_keys=True),
                     values={f'{self.role}/{key}': value for key, value in values.items()},
                     unavailable={f'{self.role}/{key}': reason for key, reason in unavailable.items()}))
        validate(event)
        self.step += 1
        return event


def ingest_sample(ledger, envelope, *, role):
    """One selected scope per role/run. Transport may redeliver the same event."""
    require({'run_id', 'synthetic', 'event'} <= set(envelope) <= {'run_id', 'synthetic', 'event', 'publication_run_id'},
            'Invalid resource envelope')
    require(envelope.get('publication_run_id', envelope['run_id']) == publication_run_id(ledger.metadata),
            'Resource publication run mismatch')
    require(envelope['run_id'] == ledger.metadata['run_id'] and
            envelope['synthetic'] is ledger.metadata['synthetic'], 'Resource run/classification mismatch')
    event = envelope['event']
    require(event['kind'] == 'telemetry' and event['producer'] == role, 'Resource role mismatch')
    allowed = {f'{role}/{key}' for key in ('cpu_cores', 'ram_gib', 'gpu_utilization_pct', 'vram_gib')}
    require(set(event['payload']['values']) | set(event['payload'].get('unavailable', {})) <= allowed,
            'Resource mailbox cannot supply trainer or outcome metrics')
    return ledger.append(event)
