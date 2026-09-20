"""Read-only projection of intent_browser episodes; never rewrites source evidence."""
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import quote


FILES = ('metadata.json', 'episode.json', 'steps.jsonl', 'events.jsonl', 'task.json',
         'evaluation.json', 'external_evaluation.json')


def safe_file(directory, name):
    directory = Path(directory).resolve()
    path = directory / name
    if not path.resolve().is_relative_to(directory):
        raise ValueError('Artifact escapes episode directory')
    return path


def read_json(directory, name):
    path = safe_file(directory, name)
    return json.loads(path.read_text(encoding='utf-8')) if path.is_file() else {}


def asset(root, relative):
    """Only recorded browser media/text/JSON, never arbitrary project files."""
    parts = relative.split('/')
    if len(parts) < 2 or not re.fullmatch(r'[A-Za-z0-9_-]+', parts[0]):
        raise ValueError('Invalid episode')
    directory = safe_file(root, parts[0])
    metadata = read_json(directory, 'metadata.json')
    if 'browsergym_version' not in metadata:
        raise ValueError('Not a BrowserGym episode')
    name = '/'.join(parts[1:])
    if not (name in FILES or re.fullmatch(r'(?:(?:decision|batch_guard)-)?observation-[0-9]+\.(?:png|txt|json\.gz)', name)
            or re.fullmatch(r'image-[0-9]+\.png', name)
            or re.fullmatch(r'video/(task_video|chat_video)/[A-Za-z0-9_-]+\.webm', name)):
        raise ValueError('Artifact not allowed')
    path = safe_file(directory, name)
    types = {'.png': 'image/png', '.webm': 'video/webm', '.json': 'application/json',
             '.gz': 'application/gzip'}
    return path, types.get(path.suffix, 'text/plain; charset=utf-8')


def project(directory):
    from ..trace import read_events

    directory = Path(directory)
    metadata = read_json(directory, 'metadata.json')
    if 'browsergym_version' not in metadata:
        return None
    episode = read_json(directory, 'episode.json')
    task = read_json(directory, 'task.json')
    evaluation = read_json(directory, 'evaluation.json')
    def rows(name):
        path = safe_file(directory, name)
        return read_events(path) if path.is_file() else []
    lifecycle, steps = rows('events.jsonl'), rows('steps.jsonl')
    def timestamp(event, call_id=None, step=None):
        return next((e.get('timestamp') for e in lifecycle if e.get('event') == event
                     and (call_id is None or e.get('call_id') == call_id)
                     and (step is None or e.get('step') == step)), None)
    started = timestamp('episode_started')
    finished = timestamp('episode_finished')
    messages = []
    def add(kind, title, value, source, at=None, **extra):
        messages.append(dict(id=f'{directory.name}:browser:{len(messages)}', kind=kind,
            title=title, text=value if isinstance(value, str) else json.dumps(value, indent=2),
            source=f'{directory.name}/{source}', at=at, provenance='recorded_browser_episode', **extra))
    def attachment(name, label):
        try:
            path, _ = asset(directory.parent, f'{directory.name}/{name}')
            if path.is_file():
                return dict(url='/artifacts/' + quote(f'{directory.name}/{name}', safe='/'),
                            label=label, image=name.endswith('.png'))
        except ValueError:
            pass
        return None
    def attachments(mapping):
        return [item for name, label in mapping if name
                for item in [attachment(name, label)] if item]
    goal = task.get('trusted_policy_goal') or metadata.get('goal') or episode.get('resolved_goal')
    add('user', 'Recorded policy goal', goal or 'Goal not separately recorded; inspect captured input.',
        'task.json' if task else 'metadata.json', started)
    add('note', 'Episode metadata', metadata, 'metadata.json', started, collapsed=True)
    def members(row):
        batch = row.get('batch_calls')
        return [m for m in batch if isinstance(m, dict)] if isinstance(batch, list) else [row]

    def status(member):
        if member.get('not_executed') or (member.get('policy_feedback') or {}).get('execution') == 'not_executed':
            return 'skipped'
        if member.get('error') or member.get('action_error') or member.get('tool_error'):
            return 'failed'
        if member.get('browser_stepped') or 'tool_output' in member:
            return 'completed'
        return 'unknown'

    actions = [member for row in steps for member in members(row) if member.get('action') is not None]
    returned_actions = [m for m in actions if m.get('browser_stepped') is True and status(m) != 'skipped']
    def action_name(row):
        action = row.get('action')
        match = re.match(r'\s*([A-Za-z_][A-Za-z0-9_]*)\s*\(', action) if isinstance(action, str) else None
        return match.group(1) if match else None
    noop_count = sum(action_name(row) == 'noop' for row in returned_actions)
    terminal_count = sum(action_name(row) == 'send_msg_to_user' for row in returned_actions)
    timing_semantics = metadata.get('timing_semantics') or episode.get('timing_semantics')
    timing_totals = episode.get('timing_totals')
    explicit_timing = isinstance(timing_semantics, dict) and bool(timing_semantics)
    timing_note = (
        'Timing totals use the recorded runner semantics below. Request/backend wall time is not '
        'isolated HTTP or model inference time; browser-step time may include observation extraction. '
        'Do not add inference_seconds to request_seconds when it is an alias.'
        if explicit_timing else
        'Timing separation is not recorded. Legacy inference_seconds may include wrapper pacing; '
        'isolated model inference and HTTP latency are unknown. Missing totals remain unknown.'
    )
    summary = {
        'recorded_model_request_attempts': sum(row.get('model_request') is not None for row in steps),
        'request_count_scope': 'Saved request payload records, including failed attempts; not confirmed HTTP dispatches or successful responses. Local/scripted decisions without a request payload are excluded.',
        'recorded_step_rows': len(steps),
        'recorded_tool_calls': {key: sum(status(m) == key for m in actions)
                                for key in ('completed','failed','skipped','unknown')},
        'recorded_tool_call_count': len(actions),
        'executed_tool_calls': sum(status(m) != 'skipped' and (
            m.get('browser_stepped') is True or 'tool_output' in m or
            (m.get('execution_index') is not None and timestamp('tool_started', f"tool-{m['execution_index']:03d}") is not None)
            ) for m in actions),
        'tool_count_scope': 'Batch members counted individually; skipped proposals are not executions. Failed/unknown calls may have effects. Executed count requires a returned browser step, recorded tool output, or dispatch lifecycle event.',
        'returned_browser_actions': {
            'total': len(returned_actions), 'noop': noop_count,
            'terminal_message': terminal_count,
            'other': len(returned_actions) - noop_count - terminal_count,
        },
        'action_rows_without_recorded_browser_return': sum(
            row.get('action') is not None and row.get('kind') != 'search'
            and row.get('browser_stepped') is not True and status(row) != 'skipped' for row in actions),
        'recorded_action_errors': sum(bool(row.get('action_error')) for row in actions),
        'action_count_scope': 'Returned BrowserGym steps include noop and terminal messages. A recorded action or returned step does not establish a server-side commit, task success, provider usage or cost.',
        'episode_reported_counts': {key: episode[key] for key in
            ('step_count', 'browser_step_count', 'action_error_count') if key in episode},
        'timing_totals': timing_totals if isinstance(timing_totals, dict) else None,
        'timing_semantics': timing_semantics if explicit_timing else None,
        'timing_note': timing_note,
    }
    add('note', 'Recorded execution summary', summary, 'steps.jsonl', finished,
        summary_sources=['steps.jsonl', 'episode.json', 'metadata.json'])
    seen_observations = set()
    def observation(value, at, turn, role, **extra):
        if not isinstance(value, dict):
            return
        name = value.get('text')
        if not name or (name, role) in seen_observations:
            return
        seen_observations.add((name, role))
        # Validate against the same artifact whitelist used by HTTP delivery.
        path, _ = asset(directory.parent, f'{directory.name}/{name}')
        text = path.read_text(encoding='utf-8') if path.is_file() else 'Observation text unavailable.'
        titles = {'selected': 'Selected decision observation', 'transition': 'Browser transition observation',
                  'final': 'Final recorded observation',
                  'consolidated': 'Consolidated page update — selected for next request'}
        add('note', titles[role],
            text, name, at, turn=turn, collapsed=True, observation_role=role,
            attachments=attachments([(value.get('screenshot'), 'Screenshot (review artifact)'), (name, 'Observation text')]), **extra)
    consumed_selections = set()
    for position, row in enumerate(steps):
        index = row['step']
        model_id, tool_id = f'model-{index:03d}', f'tool-{index:03d}'
        before = timestamp('model_started', model_id)
        after = timestamp('model_completed', model_id) or timestamp('decision_error', step=index)
        observation(None if position in consumed_selections else row.get('transition_observation'),
                    timestamp('tool_completed', f'tool-{index - 1:03d}') if index else timestamp('environment_reset_completed'),
                    index, 'transition')
        if position not in consumed_selections:
            observation(row.get('observation'), before, index, 'selected')
        request = row.get('model_request')
        if request is not None:
            add('prompt', 'Retained model request payload', request, 'steps.jsonl', before,
                turn=index, collapsed=True)
            messages[-1]['provenance'] = 'retained_request_input'
        elif row.get('messages'):
            add('prompt', 'Selected context; API request not recorded', row['messages'],
                'steps.jsonl', before, turn=index, collapsed=True)
            messages[-1]['provenance'] = 'selected_context'
        if row.get('model_output') is not None:
            add('agent', 'Recorded model / development output', row['model_output'],
                'steps.jsonl', after, turn=index)
        if row.get('model_response') is not None:
            response = row['model_response']
            add('result', 'Raw model response', response, 'steps.jsonl', after, turn=index,
                status='error' if isinstance(response, dict) and response.get('error') else 'returned')
        if row.get('error'):
            add('note', 'Step error', row['error'], 'steps.jsonl', after, turn=index, status='error')
        if isinstance(row.get('batch_calls'), list):
            batch = members(row)
            add('note', f'Batch — {len(batch)} proposed calls',
                {'stop_reason':row.get('batch_stop_reason'),
                 'scope':'Sequential execution within one model turn. Each result below is recorded; completion is not a task-success verdict.'},
                'steps.jsonl', after, turn=index, batch=True)
            for member in batch:
                ordinal = member.get('batch_call')
                execution = member.get('execution_index')
                local_id = f'tool-{execution:03d}' if type(execution) is int else None
                dispatched = timestamp('tool_started', local_id) if local_id else None
                completed = timestamp('tool_completed', local_id) if local_id else None
                state = status(member)
                fields = {'turn':index,'batch_call':ordinal,'tool_call_id':member.get('tool_call_id'),
                          'execution_index':execution,'status':'error' if state == 'failed' else state,
                          'execution_status':state}
                before_ref = member.get('observation') or {}
                after_ref = member.get('next_observation') or {}
                pictures = [(before_ref.get('screenshot'),'Guard snapshot (review only; not model input)')]
                if member.get('browser_stepped'):
                    pictures.append((after_ref.get('screenshot'),'After action (review only)'))
                capture = (member.get('tool_output') or {}) if isinstance(member.get('tool_output'),dict) else {}
                if capture.get('image_id'):
                    pictures.append((capture.get('artifact'),'Requested screenshot (delivery recorded separately)'))
                title = 'Skipped tool call' if state == 'skipped' else 'Browser action' if member.get('kind') == 'browser' else 'Tool call'
                add('tool', title, member.get('action'), 'steps.jsonl', dispatched,
                    attachments=attachments(pictures), **fields)
                add('result', 'Tool result — ' + state,
                    {'result':member.get('policy_feedback',member.get('tool_output')),
                     **{key:member[key] for key in ('error','action_error','tool_error',
                         'not_executed','browser_stepped','terminated','truncated') if key in member}},
                    'steps.jsonl', completed, **fields)
            if row.get('batch_events') is not None:
                add('note', 'Consolidated batch events (historical page evidence)',row['batch_events'],
                    'steps.jsonl', None, turn=index, batch=True)
            # Project the exact next selected AX once, at the batch boundary.
            # Guard and transition snapshots remain attachments, not claimed
            # model inputs. With no next retained request, do not invent delivery.
            if position + 1 < len(steps):
                next_row = steps[position+1]
                req = next_row.get('model_request')
                selected = next_row.get('observation') or {}
                name = selected.get('text')
                if isinstance(req,dict) and name:
                    path, _ = asset(directory.parent, f'{directory.name}/{name}')
                    selected_text = path.read_text(encoding='utf-8') if path.is_file() else None
                    contents = []
                    for message in req.get('messages',[]):
                        if message.get('role') != 'tool': continue
                        if message.get('tool_call_id') not in {m.get('tool_call_id') for m in batch}: continue
                        content = message.get('content')
                        contents.extend([content] if isinstance(content,str) else
                            [part.get('text','') for part in content or [] if isinstance(part,dict) and part.get('type')=='text'])
                    if selected_text and any(selected_text in text for text in contents):
                        observation(selected,timestamp('model_started',f"model-{next_row['step']:03d}"),index,
                                    'consolidated',next_decision=next_row['step'],delivery_scope='retained_request_content')
                        consumed_selections.add(position+1)
            continue
        if row.get('action') is not None:
            dispatched = timestamp('tool_started', tool_id)
            add('tool', 'Browser action' if row.get('kind') == 'browser' else 'Action',
                row['action'], 'steps.jsonl', dispatched, turn=index,
                status='returned' if row.get('browser_stepped') else 'unknown')
            if row.get('browser_stepped'):
                add('result', 'Browser transition', {key: row.get(key) for key in
                    ('reward', 'terminated', 'truncated', 'action_error', 'info')}, 'steps.jsonl',
                    timestamp('tool_completed', tool_id), turn=index,
                    status='error' if row.get('action_error') else 'returned')
        observation(row.get('next_observation'), timestamp('tool_completed', tool_id), index + 1, 'transition')
    final_observation = episode.get('final_observation')
    if isinstance(final_observation, dict) and not any(
            name == final_observation.get('text') for name, _ in seen_observations):
        # A failed decision can leave its selected input as the final artifact;
        # final status alone does not establish that a browser transition ran.
        observation(final_observation, finished, len(steps), 'final')
    if evaluation:
        safe = evaluation.get('safe_success')
        add('note', 'Privileged verifier — not model input', evaluation, 'evaluation.json',
            timestamp('evaluation_completed'), status='returned' if safe is True else
            'error' if safe is False else 'unknown')
    upstream = read_json(directory, 'external_evaluation.json')
    if upstream:
        add('note', 'Raw upstream score — separate from independent verifier', upstream,
            'external_evaluation.json', timestamp('evaluation_completed'), collapsed=True)
    add('note', 'Recorded lifecycle', lifecycle, 'events.jsonl', finished, collapsed=True)
    media = attachments([(v, 'Browser video' if '/task_video/' in v else 'Chat video')
                         for v in episode.get('videos', [])])
    raw = attachments([(name, name) for name in FILES])
    add('note', 'Episode artifacts', 'Original saved files; viewer does not change evaluation labels.',
        'episode.json', finished, attachments=media + raw)
    label = ('safe success' if evaluation.get('safe_success') is True else
             'unsafe / incomplete' if evaluation.get('safe_success') is False else 'outcome unknown')
    case = (metadata.get('calibration_case') or {}).get('case_id')
    title = ' · '.join(str(v) for v in (case, metadata.get('source_task_id') or metadata.get('task'),
                                       metadata.get('driver'), label, directory.name) if v)
    known = [m['at'] for m in messages if m['at']]
    return dict(id=hashlib.sha256(('browsergym:' + directory.name).encode()).hexdigest()[:20],
        title=title, started_at=started, updated_at=max(known) if known else '',
        state='recorded' if episode else 'incomplete', environment='browsergym',
        timestamp_source='Recorded lifecycle timestamps; step order retained; missing times unknown',
        streams=[f'{directory.name}/steps.jsonl'], messages=messages,
        message_count=len(messages), decision_count=0,
        notices=['BrowserGym episode view. Recorded actions have no inferred rationale. Screenshots are review artifacts; their presence does not imply image input to the model.',
                 'Retained request payloads do not prove HTTP dispatch or acknowledgment. Responses and provider-reported usage are shown only where recorded; missing cost is unknown. Verifier evidence is privileged, separate from policy input.',
                 timing_note])
