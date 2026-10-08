"""Recipient/prefix coverage of renderer-native parts from Harness artifacts.

This transport baseline does not manufacture Product assertion IDs. Missing
delivery or source mappings remain unknown; coverage says nothing about recall,
task sufficiency or whether recorded input is an authoritative outcome.
"""
from collections import Counter, defaultdict
import json
from pathlib import Path

from .fact_exposure import (coverage, digest, object_digest, projected_text,
                            receipts, require, utf16_slice)


def _artifact(trace, name):
    path = (trace / name).resolve()
    require(path.is_relative_to(trace), 'Artifact outside trace')
    return json.loads(path.read_text())


def extract(trace, *, step, recipient='main', receipt_index=None, capture_artifacts=None, strict_render=False):
    """Union exact spans, including repeat reads and equivalent render snapshots."""
    require(type(step) is int and step >= 0, 'Nonnegative prefix step required')
    require(isinstance(recipient, str) and recipient, 'Recipient required')
    trace = Path(trace).resolve()
    contents, delivered, diagnostics = receipts(trace, recipient=recipient, step=step,
                                               receipt_index=receipt_index)
    captures, sources = [], {}
    for path in sorted(trace.glob('fact-capture-*.json')):
        if capture_artifacts is not None and path.name not in capture_artifacts:
            continue
        try:
            capture = _artifact(trace, path.name)
            require(capture['schema'] == 'ax-fact-provenance-v1' and
                    capture['offset_unit'] == 'utf16_code_units', 'Unsupported capture')
            require(type(capture['step']) is int and capture['step'] >= 0, 'Invalid capture step')
            if capture['step'] > step:
                continue
            require(capture['private_context'].get('schema') == 'fact-render-occurrence-joins-v1',
                    'No renderer occurrence joins')
            for source in capture['sources']:
                require(source['id'] not in sources and digest(source['text']) == source['sha256'],
                        'Duplicate or stale source')
                require(source['binding']['snapshot_id'] == capture['snapshot_id'] and
                        source['captured_step'] == capture['step'], 'Capture/source mismatch')
            sources.update({s['id']: s for s in capture['sources']})
            captures.append(capture)
        except (OSError, KeyError, TypeError, ValueError):
            diagnostics['invalid_capture'] += 1

    ranges, evidence = defaultdict(list), defaultdict(list)
    for cid, content in contents.items():
        try:
            record = _artifact(trace, content['provenance']['fact_projection_artifact'])
            require(record['schema'] == 'ax-fact-provenance-v1' and
                    record['offset_unit'] == 'utf16_code_units' and
                    record['content_id'] == cid and record['text_sha256'] == content['sha256'],
                    'Projection/content mismatch')
        except (OSError, KeyError, TypeError, ValueError):
            diagnostics['invalid_projection_artifact'] += 1
            continue
        for projection in record['projections']:
            try:
                source = sources[projection['source_id']]
                require(source['captured_step'] <= min(delivered[cid]), 'Future source')
                require(projection['source_sha256'] == source['sha256'] and
                        projection['binding_sha256'] == object_digest(source['binding']), 'Stale binding')
                original = utf16_slice(source['text'], projection['source_start'], projection['source_end'])
                fragment = utf16_slice(projected_text(content['text'], projection['output_path']),
                                       projection['output_start'], projection['output_end'])
                require(projection['encoding'] in ('identity', 'json_string'), 'Unsupported encoding')
                if projection['encoding'] == 'json_string':
                    fragment = json.loads('"' + fragment + '"')
                require(original == fragment, 'Projection text mismatch')
                interval = (projection['source_start'], projection['source_end'])
                ranges[source['id']].append(interval)
                evidence[source['id']].append((*interval, cid, delivered[cid]))
            except (KeyError, IndexError, TypeError, ValueError):
                diagnostics['invalid_projection'] += 1

    groups = {}
    for capture in captures:
        exports = {s['export_id']: s for s in capture['sources']}
        for occurrence in capture['private_context']['occurrences']:
            try:
                state_id = object_digest(occurrence['effective_state'])
                render_scopes = set(); source_spans = []
                parts = defaultdict(lambda: {'length': 0, 'ranges': [], 'text': [], 'mapped': True,
                                              'content_ids': set(), 'steps': set()})
                for part in occurrence['parts']:
                    target = parts[part['part']]
                    require(part['spans'], 'Empty part')
                    for span in part['spans']:
                        start, end = span['start'], span['end']
                        require(type(start) is int and type(end) is int and 0 <= start < end,
                                'Invalid part interval')
                        offset = target['length']; target['length'] += end - start
                        source = exports.get(span['source_id'])
                        if source is None:
                            target['mapped'] = False
                            continue
                        require(any(p == dict(occurrence_id=occurrence['id'], state_id=state_id,
                                              part=part['part'], start=start, end=end)
                                    for p in source['opaque_binding']['parts']), 'Part join mismatch')
                        target['text'].append(utf16_slice(source['text'], start, end))
                        if strict_render:
                            binding = source['binding']
                            revision = source['opaque_binding'].get('render_revision')
                            require(type(revision) is int and revision >= 0, 'Unknown render revision')
                            require(all(isinstance(binding.get(k), str) and binding[k]
                                        for k in ('document_id', 'frame_id')), 'Unknown document/frame')
                            render_scopes.add((binding['document_id'], binding['frame_id'], revision))
                            source_spans.append({'part': part['part'], 'source_id': source['id'],
                                'export_id': source['export_id'], 'source_sha256': source['sha256'],
                                'binding': binding, 'start': start, 'end': end})
                        for a, b in ranges[source['id']]:
                            a, b = max(a, start), min(b, end)
                            if a < b:
                                target['ranges'].append((offset + a - start, offset + b - start))
                        for a, b, cid, steps in evidence[source['id']]:
                            if max(a, start) < min(b, end):
                                target['content_ids'].add(cid); target['steps'].update(steps)
                require(parts, 'Empty occurrence')
                # Cross-snapshot union requires identical native binding, state,
                # conjunctive part set AND complete, identical realized part text.
                # Missing mappings isolate the occurrence rather than guessing.
                identity = {'binding': occurrence['binding'], 'state': occurrence['effective_state'],
                            'parts': {name: ''.join(p['text']) for name, p in sorted(parts.items())}}
                if strict_render:
                    require(len(render_scopes) == 1 and all(p['mapped'] for p in parts.values()),
                            'Ambiguous or missing strict occurrence scope')
                    doc, frame, revision = next(iter(render_scopes))
                    identity['render_scope'] = {'document_id': doc, 'frame_id': frame,
                                                'render_revision': revision}
                if not all(p['mapped'] for p in parts.values()):
                    identity['unmapped_occurrence'] = [capture['id'], occurrence['id']]
                key = object_digest(identity)
                if key not in groups:
                    groups[key] = {'id': key, 'binding': occurrence['binding'],
                                   'effective_state': occurrence['effective_state'], 'state_id': state_id,
                                   'occurrence_ids': [], 'parts': parts}
                    if strict_render:
                        groups[key]['render_scope'] = identity['render_scope']
                        groups[key]['source_spans'] = source_spans
                else:
                    if strict_render:
                        groups[key]['source_spans'].extend(source_spans)
                    for name, part in parts.items():
                        target = groups[key]['parts'][name]
                        target['ranges'].extend(part['ranges'])
                        target['content_ids'].update(part['content_ids']); target['steps'].update(part['steps'])
                groups[key]['occurrence_ids'].append(occurrence['id'])
            except (KeyError, IndexError, TypeError, ValueError):
                diagnostics['invalid_occurrence'] += 1

    results = []
    for group in groups.values():
        parts = {}; content_ids = set(); steps = set()
        for name, part in group['parts'].items():
            seen = coverage(part['ranges'], 0, part['length'])
            status = 'complete' if seen == part['length'] else 'partial' if seen else 'unknown'
            parts[name] = {'status': status, 'observed_utf16': seen, 'required_utf16': part['length'],
                           'observed_fraction_lower_bound': seen / part['length'],
                           'source_mapping_complete': part['mapped']}
            if strict_render and status == 'complete':
                parts[name]['observed_text'] = ''.join(part['text'])
            content_ids.update(part['content_ids']); steps.update(part['steps'])
        statuses = [p['status'] for p in parts.values()]
        group.update(parts=parts, status='complete' if all(s == 'complete' for s in statuses) else
                     'partial' if any(s != 'unknown' for s in statuses) else 'unknown',
                     content_ids=sorted(content_ids), first_delivery_step=min(steps) if steps else None,
                     latest_delivery_step=max(steps) if steps else None)
        results.append(group)
    counts = Counter(r['status'] for r in results)
    part_counts = Counter(p['status'] for r in results for p in r['parts'].values())
    return {'schema': 'native-fact-delivery-features-v1', 'episode_id': trace.name,
            'recipient': recipient, 'prefix_step': step,
            'receipt_index': receipt_index,
            'capture_boundary': ('explicit_request_inventory' if capture_artifacts is not None
                                 else 'step_grouped_diagnostic_not_exact_request_inventory'),
            'scope': 'renderer_native_text_transport_not_semantic_sufficiency_or_recall',
            'strict_render_scope': strict_render,
            'inventory_complete': False, 'producer_qualified': False,
            'features': {'native_state_binding_count': len(results),
                         **{f'native_{s}_count': counts[s] for s in ('complete', 'partial', 'unknown')},
                         **{f'part_{s}_count': part_counts[s] for s in ('complete', 'partial', 'unknown')}},
            'records': sorted(results, key=lambda r: r['id']), 'diagnostics': dict(diagnostics)}
