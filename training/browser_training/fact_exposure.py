"""Offline coverage features over normalized fact spans and retained AX delivery.

The adapter format here is NOT a producer schema or semantic inventory. It expects
already resolved AX source fields and projection runs; no DOM text search, oracle,
browser, critic, policy-memory claim or inferred variant state is involved.
"""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

VERSION = 'fact-exposure-features-v1'
INPUT_VERSION = 'normalized-fact-exposure-v1'
# These wrappers may contain AX text; only explicit AX projections earn credit.
KINDS = {'page_observation', 'ax_result', 'search_result', 'batch_result',
         'browser_feedback', 'browser_update'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def object_digest(value):
    return digest(json.dumps(value, ensure_ascii=False, sort_keys=True,
                             separators=(',', ':'), allow_nan=False))


def utf16_length(text):
    return len(text.encode('utf-16-le')) // 2


def utf16_slice(text, start, end):
    require(type(start) is int and type(end) is int and
            0 <= start < end <= utf16_length(text), 'Invalid UTF-16 interval')
    try:
        return text.encode('utf-16-le')[2*start:2*end].decode('utf-16-le')
    except UnicodeDecodeError as error:
        raise ValueError('Interval splits a surrogate pair') from error


def indexed(rows, name):
    result = {}
    for row in rows:
        key = row['id']
        require(isinstance(key, str) and key and key not in result, f'Duplicate/invalid {name} ID')
        result[key] = row
    return result


def coverage(intervals, start, end):
    """Union intersections; repeat delivery and overlap cannot inflate coverage."""
    clipped = sorted((max(start, a), min(end, b)) for a, b in intervals
                     if max(start, a) < min(end, b))
    total, previous = 0, start
    for a, b in clipped:
        total += max(0, b - max(a, previous))
        previous = max(previous, b)
    return total


def projected_text(content, path):
    """Locate output structurally, including a full-node JSON string if complete.

    Path strings/indexes traverse parsed tool JSON. {'decode_json': true} parses
    an inner JSON string. No arbitrary evaluation or substring relocation.
    """
    value = content if not path else json.loads(content)
    for item in path:
        if isinstance(item, dict) and item == {'decode_json': True}:
            value = json.loads(value)
        elif isinstance(item, str) and isinstance(value, dict):
            value = value[item]
        elif type(item) is int and item >= 0 and isinstance(value, list):
            value = value[item]
        else:
            raise ValueError('Unsupported projection path')
    require(isinstance(value, str), 'Projection must identify text')
    return value


def receipts(trace, *, recipient, step, receipt_index=None):
    """Recheck saved delivery against exact retained request, without trace writes."""
    trace = Path(trace).resolve()
    if not all((trace/name).is_file() for name in ('steps.jsonl', 'policy-delivery.jsonl')):
        return {}, {}, Counter(missing_delivery_artifacts=1)
    raw_rows = [json.loads(line) for line in (trace/'steps.jsonl').read_text().splitlines()]
    rows = indexed([dict(row, id=str(row['step'])) for row in raw_rows], 'step')
    contents, delivered, diagnostics = {}, {}, Counter()
    request_hashes, artifacts = {}, {}
    if receipt_index is not None:
        require(type(receipt_index) is int and receipt_index >= 0, 'Invalid receipt ordinal')
    for ordinal, line in enumerate((trace/'policy-delivery.jsonl').read_text().splitlines()):
        if receipt_index is not None and ordinal > receipt_index:
            break
        event = json.loads(line)
        if event['recipient'] != recipient or event['step'] > step:
            continue
        for item in event['items']:
            if not item['confirmed'] or item['kind'] not in KINDS:
                continue
            try:
                require(event['scope'] == 'retained_request_completion' and
                        event['backend_completion_returned'] is True and item['aligned'] is True,
                        'Unconfirmed retained completion')
                row = rows[str(event['step'])]
                messages = row['model_request']['messages']
                request_step = event['step']
                if request_step not in request_hashes:
                    request_hashes[request_step] = object_digest(messages)
                require(request_hashes[request_step] == event['messages_sha256'], 'Request hash mismatch')
                artifact = (trace/item['artifact']).resolve()
                require(artifact.is_relative_to(trace), 'Artifact outside trace')
                if artifact not in artifacts:
                    content = json.loads(artifact.read_text())
                    require(digest(content['text']) == content['sha256'], 'Content hash mismatch')
                    artifacts[artifact] = content
                content = artifacts[artifact]
                require(content['id'] == item['content_id'] and content['kind'] == item['kind'] and
                        content['sha256'] == item['sha256'], 'Content hash mismatch')
                require(type(content['created_step']) is int and content['created_step'] <= event['step'],
                        'Future content')
                span = item['message_span']
                require(span['content_id'] == item['content_id'], 'Binding identity mismatch')
                require(type(span['message_index']) is int and span['message_index'] >= 0 and
                        type(span['start']) is int and type(span['end']) is int and
                        0 <= span['start'] < span['end'], 'Invalid request binding')
                text = messages[span['message_index']]['content']
                if isinstance(text, list):
                    require(text and text[0]['type'] == 'text', 'Missing text message')
                    text = text[0]['text']
                require(isinstance(text, str) and span['end'] <= len(text) and
                        text[span['start']:span['end']] == content['text'], 'Request alignment mismatch')
                require(content['id'] not in contents or contents[content['id']] == content,
                        'Conflicting content identity')
                contents[content['id']] = content
                delivered.setdefault(content['id'], set()).add(event['step'])
            except (KeyError, IndexError, TypeError, ValueError, OSError):
                diagnostics['invalid_receipt'] += 1
    return contents, delivered, diagnostics


def extract(manifest, trace, *, recipient='main', step, fact_ids=None):
    require(type(step) is int and step >= 0, 'Nonnegative prefix step required')
    require(isinstance(recipient, str) and recipient, 'Recipient required')
    require(manifest['schema'] == INPUT_VERSION, 'Unsupported normalized adapter schema')
    require(manifest['episode_id'] == Path(trace).name, 'Annotation/trace episode mismatch')
    require(manifest['offset_unit'] == 'utf16_code_units', 'Explicit UTF-16 offsets required')
    states = indexed(manifest['states'], 'state')
    sources = indexed(manifest['sources'], 'source')
    facts = indexed(manifest['facts'], 'fact')
    publications = indexed(manifest['publications'], 'publication')
    selected = set(facts) if fact_ids is None else set(fact_ids)
    require(selected <= facts.keys(), 'Unknown requested fact instance')
    for state in states.values():
        require(isinstance(state['values'], dict), 'Effective state object required')
        require(object_digest(state['values']) == state['sha256'], 'Effective state hash mismatch')
        require(type(state['recorded_step']) is int and state['recorded_step'] >= 0, 'State capture step required')
    invalid_sources = set()
    for source in sources.values():
        require(type(source['captured_step']) is int and source['captured_step'] >= 0, 'Source capture step required')
        require(isinstance(source['binding'], dict) and
                set(('snapshot_id', 'document_id', 'frame_id', 'node_id', 'field')) <= source['binding'].keys(),
                'Resolved AX binding required')
        require(source['binding']['field'] in ('name', 'value'), 'Normalized source must be an AX field')
        require(all(isinstance(source['binding'][key], str) and source['binding'][key]
                    for key in ('snapshot_id', 'document_id', 'frame_id', 'node_id')), 'Scoped source identity required')
        if digest(source['text']) != source['sha256']:
            invalid_sources.add(source['id'])
    resolved = {}
    for publication in publications.values():
        require(publication['mapping_status'] in ('complete', 'unmapped'), 'Producer mapping status required')
        require(isinstance(publication['formulation_id'], str) and publication['formulation_id'],
                'Chosen formulation/realization identity required')
        require(all(isinstance(publication[key], str) and len(publication[key]) == 64 and
                    all(c in '0123456789abcdef' for c in publication[key])
                    for key in ('metadata_sha256', 'source_sha256')), 'Producer source pins required')
        resolved[publication['id']] = indexed(publication['assertions'], 'resolved assertion')
    for fact in facts.values():
        require(fact['state_id'] in states, 'Authoritative fact state required')
        assertion = fact['assertion']
        require(assertion['kind'] in ('field_value', 'catalog_predicate', 'customer_experience') and
                assertion['authority'] in ('catalog_fact', 'attributed_experience'), 'Producer assertion kind/authority required')
        require(all(isinstance(assertion[key], str) and assertion[key] for key in ('id', 'subject_id')),
                'Producer semantic and bound subject identity required')
        require(type(fact['mapping_complete']) is bool and fact['required_parts'] and
                all(isinstance(part, str) and part for part in fact['required_parts']) and
                len(set(fact['required_parts'])) == len(fact['required_parts']), 'Fact mapping/parts required')
    occurrences = defaultdict(list)
    for occurrence in indexed(manifest['occurrences'], 'occurrence').values():
        fact = facts[occurrence['fact_id']]
        publication = publications[occurrence['publication_id']]
        require(publication['mapping_status'] == 'complete' and
                resolved[publication['id']].get(fact['assertion']['id']) == fact['assertion'],
                'Occurrence assertion is not declared by its chosen producer formulation')
        require(occurrence['part'] in fact['required_parts'] and occurrence['spans'], 'Declared fact part required')
        for span in occurrence['spans']:
            source = sources[span['source_id']]
            utf16_slice(source['text'], span['start'], span['end'])
            require(source['captured_step'] >= states[fact['state_id']]['recorded_step'],
                    'Source predates effective state')
        occurrences[(fact['id'], occurrence['part'])].append(occurrence)
    contents, delivered, diagnostics = receipts(trace, recipient=recipient, step=step)
    diagnostics['invalid_source_hash'] += len(invalid_sources)
    ranges, range_steps = defaultdict(list), defaultdict(list)
    uncertain_sources = set(invalid_sources)
    for projection in manifest['projections']:
        source_id, content_id = projection['source_id'], projection['content_id']
        require(source_id in sources, 'Unknown projected source')
        if content_id not in delivered:
            continue
        source = sources[source_id]
        try:
            require(source_id not in invalid_sources, 'Invalid source')
            require(source['captured_step'] <= min(delivered[content_id]), 'Source captured after delivery')
            require(projection['source_sha256'] == source['sha256'] and
                    projection['binding_sha256'] == object_digest(source['binding']), 'Stale source binding')
            original = utf16_slice(source['text'], projection['source_start'], projection['source_end'])
            output = projected_text(contents[content_id]['text'], projection['output_path'])
            fragment = utf16_slice(output, projection['output_start'], projection['output_end'])
            encoding = projection.get('encoding', 'identity')
            require(encoding in ('identity', 'json_string'), 'Unsupported text transformation')
            if encoding == 'json_string':
                fragment = json.loads('"' + fragment + '"')
            require(original == fragment, 'Projection text mismatch')
            interval = projection['source_start'], projection['source_end']
            ranges[source_id].append(interval)
            range_steps[source_id].append((*interval, content_id, delivered[content_id]))
        except (KeyError, IndexError, TypeError, ValueError):
            diagnostics['invalid_projection'] += 1
            uncertain_sources.add(source_id)
    inventory_step = manifest['projection_complete_through_step'].get(recipient)
    inventory_complete = (type(inventory_step) is int and inventory_step >= step and
                          not diagnostics['invalid_receipt'] and not diagnostics['missing_delivery_artifacts'])
    results = []
    for fact_id in sorted(selected):
        fact = facts[fact_id]
        state = states[fact['state_id']]
        require(state['recorded_step'] <= step, 'Target fact state is after prefix cutoff')
        parts, evidence_steps, evidence_ids = {}, set(), set()
        for part in fact['required_parts']:
            options = occurrences[(fact_id, part)]
            best, complete = 0.0, False
            measured = bool(options) and fact['mapping_complete'] and inventory_complete
            for occurrence in options:
                length, seen = 0, 0
                eligible = all(sources[s['source_id']]['captured_step'] <= step for s in occurrence['spans'])
                if not eligible:
                    measured = False
                    continue
                for span in occurrence['spans']:
                    source_id = span['source_id']
                    length += span['end'] - span['start']
                    seen += coverage(ranges[source_id], span['start'], span['end'])
                    if source_id in uncertain_sources:
                        measured = False
                    for start, end, content_id, steps in range_steps[source_id]:
                        if max(start, span['start']) < min(end, span['end']):
                            evidence_steps.update(steps); evidence_ids.add(content_id)
                best = max(best, seen / length)
                complete |= seen == length
            status = 'complete' if complete else 'partial' if best else 'unseen' if measured else 'unknown'
            parts[part] = dict(status=status, observed_utf16_fraction=best if status != 'unknown' else None,
                               measurement_complete=measured)
        statuses = [part['status'] for part in parts.values()]
        status = ('complete' if all(s == 'complete' for s in statuses) else
                  'partial' if any(s in ('partial', 'complete') for s in statuses) else
                  'unseen' if all(s == 'unseen' for s in statuses) else 'unknown')
        assertion = fact['assertion']
        results.append(dict(fact_id=fact_id, assertion_id=assertion['id'], subject_id=assertion['subject_id'],
                            authority=assertion['authority'], assertion_sha256=object_digest(assertion), site_id=fact['site_id'],
                            entity_id=fact['entity_id'], state_id=fact['state_id'], state_sha256=state['sha256'],
                            status=status, parts=parts, content_ids=sorted(evidence_ids),
                            first_delivery_step=min(evidence_steps) if evidence_steps else None,
                            latest_delivery_step=max(evidence_steps) if evidence_steps else None))
    counts = Counter(f['status'] for f in results)
    by_site = defaultdict(list)
    for fact in results:
        by_site[fact['site_id']].append(fact)
    part_counts = Counter(p['status'] for f in results for p in f['parts'].values())
    features = dict(target_fact_count=len(results), target_site_count=len(by_site),
                    target_state_count=len({f['state_id'] for f in results}),
                    **{f'fact_{s}_count': counts[s] for s in ('complete', 'partial', 'unseen', 'unknown')},
                    fact_complete_fraction=counts['complete']/len(results) if results else None,
                    fact_any_exposure_fraction=(counts['complete']+counts['partial'])/len(results) if results else None,
                    **{f'part_{s}_count': part_counts[s] for s in ('complete', 'partial', 'unseen', 'unknown')},
                    sites_with_any_exposure=sum(any(f['status'] in ('complete', 'partial') for f in v) for v in by_site.values()),
                    sites_with_all_targets_complete=sum(all(f['status'] == 'complete' for f in v) for v in by_site.values()),
                    sites_with_unknown_mapping=sum(any(p['status'] == 'unknown' for f in v for p in f['parts'].values())
                                                   for v in by_site.values()))
    return dict(schema=VERSION, episode_id=manifest['episode_id'], recipient=recipient, prefix_step=step,
                scope='annotated_ax_text_only_not_semantic_sufficiency_or_recall',
                annotation_sha256=object_digest(manifest), projection_inventory_complete=inventory_complete,
                features=features, facts=results, diagnostics=dict(sorted((k, v) for k, v in diagnostics.items() if v)))
