"""Publication identity for checkpoint continuations; no W&B dependency.

The logical run stays stable for ledger/sampler provenance. Every model-checkpoint
restore gets its own publication run, so old remote history is never rolled back.
Uploader restarts within that execution keep the same publication identity.
"""
import math
import re


def validate_publication(value, logical_run_id):
    required = {'run_id', 'parent_run_id', 'checkpoint_name', 'checkpoint_snapshot_id',
                'checkpoint_state_sha256', 'inherited_watermark', 'checkpoint_policy_version', 'resumed_at'}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError('Invalid publication lineage fields')
    for key in ('run_id', 'parent_run_id'):
        if not isinstance(value[key], str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value[key]):
            raise ValueError('Invalid publication run identity')
    if value['run_id'] in {value['parent_run_id'], logical_run_id}:
        raise ValueError('Checkpoint continuation needs a new publication identity')
    for key in ('checkpoint_snapshot_id', 'checkpoint_state_sha256'):
        if not isinstance(value[key], str) or not re.fullmatch(r'[a-f0-9]{64}', value[key]):
            raise ValueError('Invalid checkpoint checksum in publication lineage')
    for key in ('inherited_watermark', 'checkpoint_policy_version'):
        if type(value[key]) is not int or value[key] < 0:
            raise ValueError('Invalid checkpoint counter in publication lineage')
    if not isinstance(value['checkpoint_name'], str) or not value['checkpoint_name']:
        raise ValueError('Checkpoint name required')
    if type(value['resumed_at']) not in (int, float) or not math.isfinite(value['resumed_at']) or value['resumed_at'] < 0:
        raise ValueError('Invalid continuation timestamp')
    return value


def publication_run_id(snapshot):
    lineage = snapshot.get('publication')
    if lineage is None:
        return snapshot['run_id']  # Existing root-run files remain valid.
    return validate_publication(lineage, snapshot['run_id'])['run_id']


def publication_config(snapshot):
    return dict(logical_run_id=snapshot['run_id'], publication_run_id=publication_run_id(snapshot),
                publication_lineage=snapshot.get('publication'))
