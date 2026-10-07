"""Bounded public sufficiency from source-pinned, actual normalized captures.

This audit consumes DOM/AX evidence, never policy delivery or native truth alone.
Producer field/slot meanings still depend on the separately reviewed renderer
closure. Unsupported semantics, unknown/NA declarations and topic counts remain
unresolved. It does not launch a browser or alter Website modules.
"""
from collections import defaultdict
from copy import deepcopy
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
import json
import math
from pathlib import Path
import subprocess

from .fact_compare_review_features import compile_roles, project
from .fact_exposure import digest, object_digest, require, utf16_slice


def _parts(normalized, occurrence):
    runs = {r['id']: r for r in normalized['runs']}
    require(len(runs) == len(normalized['runs']), 'Duplicate DOM run')
    sources = {s['id']: s for s in normalized['ax_sources']}
    require(len(sources) == len(normalized['ax_sources']), 'Duplicate AX source')
    parts = defaultdict(str)
    for part in occurrence['parts']:
        require(part['spans'], 'Empty part')
        for span in part['spans']:
            run, source = runs[span['source_id']], sources[span['source_id']]
            require(run['text'] == source['text'] and
                    run['sha256'] == source['sha256'] == digest(run['text']),
                    'Changed DOM/AX text')
            require(all(source['binding'][key] == normalized[key]
                        for key in ('snapshot_id', 'document_id', 'frame_id')),
                    'Foreign AX scope')
            require(type(span['start']) is int and type(span['end']) is int and
                    0 <= span['start'] < span['end'], 'Invalid part range')
            parts[part['part']] += utf16_slice(run['text'], span['start'], span['end'])
    require(parts and all(parts.values()), 'Missing public parts')
    return dict(parts)


@lru_cache(maxsize=1024, typed=True)
def _scalar_text(value):
    """Exact catalog_adapter.display followed by the recorder's JS String.

    Float formatting is delegated to JavaScript, avoiding Python/ECMAScript
    shortest-decimal differences. This cached local conversion is audit-only;
    it adds no work to the browser Harness or model context.
    """
    if type(value) is bool:
        return 'Yes' if value else 'No'
    if type(value) is str:
        return value
    if type(value) is int and abs(value) <= 2**53-1:
        return str(value)
    if type(value) in (int, float):
        require(type(value) is int or math.isfinite(value), 'Nonfinite public number')
        result = subprocess.run(['node', '-e',
            "process.stdout.write(String(JSON.parse(require('fs').readFileSync(0,'utf8'))))"],
            input=json.dumps(value, allow_nan=False), text=True, capture_output=True,
            check=True, timeout=3)
        return result.stdout
    raise ValueError('Unsupported scalar display')


def _same_native_scalar(actual, expected):
    # JSON transport may turn a JavaScript integral Number into a Python int.
    # Booleans and strings retain their domains and never coerce to numbers.
    if type(actual) in (int, float) and type(expected) in (int, float):
        return actual == expected
    return type(actual) is type(expected) and actual == expected


def _verified(occurrence, parts, role, reference):
    """Verify rendered values before the existing typed scope/dependency join."""
    binding = occurrence['binding']
    pid = role['product_id']
    if binding.get('product_id') != pid:
        return False
    if role['source_family'] == 'retailer':
        facts = {m['product_id']: m['facts'] for m in reference['comparison']['models']}
        expected = facts[pid][role['field']]
        # Absence is not a public declaration of unknown/NA.
        if expected['status'] != 'known' or not parts.get('label'):
            return False
        if type(expected.get('value')) is int and abs(expected['value']) > 2**53-1:
            return False # Arbitrary-precision native integers need a string-valued producer contract.
        authority = binding.get('authority')
        if authority == 'native_public_field':
            if binding.get('field') != role['field']:
                return False
            value, displayed = expected['value'], binding.get('displayed_value')
            if type(value) is bool:
                if type(displayed) is not str or displayed != _scalar_text(value):
                    return False
            elif type(value) in (int, float):
                if type(displayed) not in (int, float) or displayed != value:
                    return False
            elif type(displayed) is not type(value) or displayed != value:
                return False
            # A direct public row must print the exact scalar and required unit.
            # Qualifier semantics are not bound by this narrow adapter yet.
            return (parts.get('value') == _scalar_text(expected['value']) and
                    parts.get('value') == _scalar_text(binding['displayed_value']) and
                    (expected.get('unit') is None or parts.get('unit') == expected['unit']) and
                    expected.get('basis') is None)
        if authority == 'selected_slot':
            if parts.get('value') != _scalar_text(binding['displayed_value']):
                return False
            # The complete producer slot is the meaning contract; do not infer
            # individual assertions from substring matches or partial reads.
            return any(a.get('field') == role['field'] and
                       a.get('subject') == {'kind': 'product', 'id': pid} and
                       a.get('status') == 'known' and
                       _same_native_scalar(a.get('value'), expected['value']) and
                       a.get('unit') == expected.get('unit') and
                       a.get('qualifiers', {}).get('basis') == expected.get('basis')
                       for a in binding.get('assertions', []))
        return False
    if role.get('operation') != 'rating_summary':
        return False
    summaries = {r['subject']['product_id']: r['summary'] for r in reference['reviews'].values()}
    summary = summaries[pid]
    field = binding.get('field')
    if field == 'star_counts':
        stars = binding.get('stars')
        if type(stars) is not int or stars not in range(1, 6):
            return False
        value = summary['star_counts'][str(stars)]
        if role['field'] == 'summary.mean_rounded':
            count = sum(summary['star_counts'].values())
            if not count:
                return False
            mean = Decimal(sum(int(s) * c for s, c in summary['star_counts'].items())) / count
            if str(mean.quantize(Decimal('.01'), rounding=ROUND_HALF_UP)) != summary['mean_rounded']:
                return False
        return (parts.get('stars') == f'{stars} stars' and parts.get('count') == str(value)
                and type(binding.get('displayed_value')) is int and binding['displayed_value'] == value)
    labels = {'rating_count': ' ratings; ', 'written_review_count': ' written reviews, ',
              'rating_only_count': ' ratings without comments.'}
    if field not in labels:
        return False
    value = summary[field]
    return (parts.get('value') == str(value) and parts.get('label') == labels[field] and
            type(binding.get('displayed_value')) is int and binding['displayed_value'] == value)


def audit_captures(task, reference, capture_paths, *, runtime_binding_sha256):
    """Report exact role evidence; only a complete audit yields sufficient.

    Each file is a fact-render-normalized-v1 object (or capture.result containing
    normalized). The caller owns the source-pinned browser capture and binds its
    actual Runtime digest. This helper cannot establish authenticity of an
    arbitrary authored JSON artifact or promote source controls to live evidence.
    """
    require(reference['task_id'] == task['task_id'], 'Task/reference identity mismatch')
    require(type(runtime_binding_sha256) is str and len(runtime_binding_sha256) == 64 and
            all(c in '0123456789abcdef' for c in runtime_binding_sha256), 'Runtime digest required')
    roles = compile_roles(task)
    files, candidates, diagnostics = {}, [], []
    for filename in capture_paths:
        path = Path(filename).resolve()
        require(str(path) not in files, 'Duplicate capture path')
        raw = path.read_bytes()
        files[str(path)] = digest(raw.decode())
        saved = json.loads(raw)
        normalized = saved.get('normalized', saved)
        require(normalized['schema'] == 'fact-render-normalized-v1', 'Unsupported public capture')
        ids = set()
        for occurrence in normalized['occurrences']:
            require(occurrence['id'] not in ids, 'Duplicate occurrence')
            ids.add(occurrence['id'])
            try:
                parts = _parts(normalized, occurrence)
            except (KeyError, TypeError, ValueError) as exc:
                diagnostics.append({'document': str(path), 'occurrence': occurrence['id'],
                                    'reason': str(exc)})
                continue
            candidates.append((str(path), occurrence, parts))
    rows = []
    for role in roles:
        eligible, evidence = [], {}
        for document, occurrence, parts in candidates:
            if not _verified(occurrence, parts, role, reference):
                continue
            record_id = object_digest({'document': document, 'occurrence': occurrence['id']})
            eligible.append({'id': record_id, 'binding': deepcopy(occurrence['binding']),
                             'effective_state': deepcopy(occurrence['effective_state']), 'status': 'complete'})
            evidence[record_id] = {'document': document, 'occurrence': occurrence['id']}
        # Source availability only. No fabricated delivery receipts are saved.
        projected = project(task, {'schema': 'native-fact-delivery-features-v1',
                                  'recipient': 'public_audit_only', 'prefix_step': 0, 'records': eligible})
        result = next(r for r in projected['roles'] if r['role_id'] == role['role_id'])
        hits = [evidence[r] for r in result['native_record_ids']]
        complete = result['observation_status'] == 'complete'
        rows.append({'role_id': role['role_id'], 'product_id': role['product_id'],
                     'source_family': role['source_family'], 'status': 'known' if complete else 'unresolved',
                     'document': hits[0]['document'] if hits else None,
                     'locator': 'occurrence:' + hits[0]['occurrence'] if hits else None,
                     'evidence': hits, 'reason': None if complete else 'required_public_parts_or_semantics_unresolved'})
    return {'schema': 'website-compare-review-readiness-v1', 'task_id': task['task_id'],
            'runtime_binding_sha256': runtime_binding_sha256, 'files': files, 'roles': rows,
            'status': 'sufficient' if rows and all(r['status'] == 'known' for r in rows) else 'unresolved',
            'diagnostics': diagnostics, 'delivery_evidence': False,
            'qualification': 'bounded_source_pinned_public_capture_audit_not_policy_exposure'}
