"""Shared BrowserGym driver over a private pipe; inference remains outside the browser process.

Load the immutable package's runtime via PYTHONPATH. The controller supplies a
reviewed task ID, never a URL or Python action. Stdout/stderr are diagnostics;
RPC responses use fd 3 so page/library output cannot masquerade as a response.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import sys
import time
from uuid import uuid4
import zipfile

KEYS = {'Tab', 'Shift+Tab', 'Enter', 'Escape', 'Backspace', 'Delete', 'Space',
        'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Home', 'End',
        'PageUp', 'PageDown', 'ControlOrMeta+a'}


def action_code(value, width, height):
    if not isinstance(value, dict):
        raise ValueError('Invalid manual action')
    kind = value.get('type')
    def number(name, low, high):
        n = value.get(name)
        if type(n) not in (int, float) or not math.isfinite(n) or not low <= n <= high:
            raise ValueError('Invalid action coordinate or scroll distance')
        return n
    if kind == 'click' and set(value) == {'type', 'x', 'y'}:
        return f"mouse_click({number('x', 0, width-1)!r}, {number('y', 0, height-1)!r})"
    if kind == 'scroll' and set(value) == {'type', 'dx', 'dy'}:
        return f"scroll({number('dx', -500, 500)!r}, {number('dy', -500, 500)!r})"
    if kind == 'press' and set(value) == {'type', 'key'} and isinstance(value['key'], str) and value['key'] in KEYS:
        return f"keyboard_press({value['key']!r})"
    if kind == 'type' and set(value) == {'type', 'text'} and isinstance(value['text'], str) and 0 < len(value['text']) <= 1000:
        return f"keyboard_insert_text({value['text']!r})"
    raise ValueError('Unsupported manual action')


def run(args):
    from browsergym.core.action.highlevel import HighLevelActionSet
    from intent_browser.environment_runtime import EnvironmentRuntime
    from intent_browser.trace import Trace, write_json
    from intent_browser.runner import observation_text
    from intent_browser.observation import refresh_observation
    from intent_browser.evaluation import Evaluation
    from shared_browser_policy import messages_for, parse_reply

    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    rpc = os.fdopen(args.rpc_fd, 'w', buffering=1, closefd=False)
    commands = os.fdopen(args.command_fd, 'r', closefd=False)
    def emit(value):
        rpc.write(json.dumps(value, ensure_ascii=False)+'\n');rpc.flush()
    trace = env = session = None
    obs = info = None
    reward = 0
    terminated = truncated = False
    steps = frame_index = errors = 0
    frame = None
    archive = None
    technical_error = None
    stop_reason = 'controller_disconnected'
    last_command = None
    reference_goal = None
    history = []
    pending_decision = None
    active_ask = None
    agent_turns = 0
    def capture(observation):
        nonlocal frame_index, frame
        if frame_index >= 300:
            raise RuntimeError('Manual frame limit reached')
        ref = trace.observation(frame_index, observation, observation_text(observation))
        frame_index += 1
        shape = observation['screenshot'].shape
        frame = {'id': str(uuid4()), 'width': int(shape[1]), 'height': int(shape[0]),
                 'artifact': ref, 'page_url': observation['url'], 'captured_at': time.time()}
        trace.event('manual_frame_captured', frame=frame,
                    scope='Captured pixels; no model input or human attention claim')
        return frame
    def state():
        return {'frame': frame, 'action_count': steps, 'reference_goal': reference_goal,
                'trace_directory': str(trace.directory), 'episode': trace.episode_id,
                'last_error': obs.get('last_action_error') if obs else None,
                'terminated': terminated, 'truncated': truncated}
    def interrupted(*_):
        raise InterruptedError('Manual controller stopped the session')
    signal.signal(signal.SIGTERM, interrupted)
    with EnvironmentRuntime(args.package, output/'environment') as runtime:
      with runtime.session(args.task) as session:
        try:
            trace = Trace(output/'runs', {'task': args.task, 'driver': args.actor, 'interaction_kind': 'manual',
                'model': None, 'training_eligible': False, 'seed': args.seed,
                'package_sha256': runtime.manifest_hash,
                'manual_driver_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                'policy_helper_sha256': hashlib.sha256(Path(__file__).with_name('shared_browser_policy.py').read_bytes()).hexdigest(),
                'authorization_scope': 'Manual exploration; reference task is not a user intent contract',
                'observation_lifecycle': 'manual-pixel-v1'})
            trace.event('task_prepare_started')
            write_json(trace.directory/'task.json', session.prepare(trace))
            trace.event('task_prepare_completed', artifact='task.json')
            actions = HighLevelActionSet(subsets=['coord', 'bid'], strict=True, multiaction=False)
            trace.event('environment_create_started')
            env = session.make_env(action_mapping=actions.to_python_code, headless=True)
            trace.event('environment_reset_started', seed=args.seed)
            obs, info = env.reset(seed=args.seed)
            initial = session.capture_initial(env, obs, info)
            reference_goal = getattr(session.task, 'policy_goal', None) or obs['goal']
            write_json(trace.directory/'initial-state.json', {'resolved_goal': reference_goal, 'task_state': initial, 'browsergym_seed': args.seed})
            trace.event('environment_reset_completed', artifacts=['initial-state.json'])
            obs = refresh_observation(env)
            capture(obs)
            emit({'kind': 'ready', **state()})
            for line in commands:
                if len(line.encode()) > 2_000_000:
                    raise ValueError('Manual command too large')
                command = json.loads(line)
                last_command = command['request_id']
                trace.event('manual_command_received', request_id=last_command, command=command)
                operation = command.get('operation')
                if operation == 'close':
                    stop_reason = command.get('reason', 'user_close')
                    break
                if operation == 'agent_observe':
                    goal = command.get('goal')
                    ask_id = command.get('ask_id')
                    if not isinstance(goal, str) or not 0 < len(goal) <= 2000 or not isinstance(ask_id, str):
                        raise ValueError('Invalid agent request')
                    if ask_id != active_ask:
                        active_ask = ask_id; agent_turns += 1
                        trace.metadata.update(interaction_kind='shared', driver='shared-browser', policy_protocol='browsergym-json-action-v1')
                        write_json(trace.directory/'metadata.json', trace.metadata)
                        history.append({'actor': 'human', 'request': goal})
                        trace.event('shared_agent_turn_started', ask_id=ask_id, goal=goal)
                    obs = refresh_observation(env); capture(obs)
                    messages = messages_for(obs, goal, history)
                    pending_decision = {'id': str(uuid4()), 'ask_id': ask_id,
                        'observation': frame['artifact'], 'messages': messages, 'frame_id': frame['id']}
                    trace.event('shared_decision_captured', **pending_decision)
                    emit({'kind': 'result', 'request_id': last_command, 'decision': pending_decision, **state()})
                    continue
                if operation in ('action', 'agent_action') and (terminated or truncated):
                    emit({'kind': 'rejected', 'request_id': last_command, 'error': 'Environment already ended; no action executed.'})
                    continue
                if operation == 'agent_action':
                    if (not pending_decision or command.get('decision_id') != pending_decision['id']
                            or command.get('ask_id') != pending_decision['ask_id']):
                        emit({'kind': 'rejected', 'request_id': last_command, 'error': 'Agent observation is no longer current.'})
                        continue
                    evidence = command.get('evidence', {})
                    trace.event('shared_model_result', ask_id=active_ask, decision=pending_decision, evidence=evidence)
                    before = frame
                    decision_record = pending_decision; pending_decision = None
                    try:
                        decision = parse_reply(evidence.get('output', ''))
                    except Exception as error:
                        trace.event('shared_action_rejected', ask_id=active_ask, error=str(error))
                        emit({'kind': 'result', 'request_id': last_command, 'agent_error': str(error), **state()})
                        continue
                    if decision.name == 'send_msg_to_user':
                        answer = decision.arguments['text']
                        history.append({'actor': 'agent', 'answer': answer})
                        trace.event('shared_agent_answer', ask_id=active_ask, answer=answer)
                        emit({'kind': 'result', 'request_id': last_command, 'answer': answer, **state()})
                        continue
                    code = decision.code
                    actor = 'agent'
                elif operation == 'observe':
                    obs = refresh_observation(env);capture(obs)
                    emit({'kind': 'result', 'request_id': last_command, **state()})
                    continue
                elif operation == 'action':
                    if command.get('frame_id') != frame['id']:
                        emit({'kind': 'rejected', 'request_id': last_command, 'error': 'The displayed frame changed; refresh before acting.'})
                        continue
                    pending_decision = None
                    try:
                        code = action_code(command.get('action'), frame['width'], frame['height'])
                    except ValueError as error:
                        trace.event('manual_action_rejected', request_id=last_command, error=str(error))
                        emit({'kind': 'rejected', 'request_id': last_command, 'error': str(error)})
                        continue
                    actor = args.actor
                else:
                    emit({'kind': 'rejected', 'request_id': last_command, 'error': 'Unsupported operation'})
                    continue
                if steps >= 100:
                    stop_reason = 'manual_action_limit';break
                before = frame
                trace.event('browser_action_started', step=steps, action=code, manual_request_id=last_command,
                            presented_frame_id=before['id'], frame_age_seconds=time.time()-before['captured_at'])
                try:
                    obs, reward, terminated, truncated, info = env.step(code)
                    capture(obs)
                except Exception as error:
                    # Dispatch may already have changed the page. Retain the attempt
                    # even when BrowserGym cannot capture its resulting observation.
                    detail = type(error).__name__+': '+str(error)
                    trace.append({'step': steps, 'observation': before['artifact'], 'next_observation': None,
                        'action': code, 'reward': None, 'error': detail, 'execution_confirmed': None,
                        'model_request': evidence.get('request') if actor == 'agent' else None,
                        'model_response': evidence.get('response') if actor == 'agent' else None,
                        'model_output': evidence.get('output') if actor == 'agent' else None,
                        'messages': decision_record['messages'] if actor == 'agent' else None,
                        'actor': actor, 'manual_request': command, 'presented_frame_id': before['id']})
                    trace.event('browser_action_completed', step=steps, error=detail, execution_confirmed=None)
                    steps += 1; errors += 1
                    raise
                action_error = obs.get('last_action_error') or None
                trace.append({'step': steps, 'observation': before['artifact'], 'next_observation': frame['artifact'],
                    'action': code, 'reward': reward, 'error': action_error,
                    'model_request': evidence.get('request') if actor == 'agent' else None,
                        'model_response': evidence.get('response') if actor == 'agent' else None,
                        'model_output': evidence.get('output') if actor == 'agent' else None,
                        'messages': decision_record['messages'] if actor == 'agent' else None,
                    'actor': actor, 'manual_request': command, 'presented_frame_id': before['id']})
                trace.event('browser_action_completed', step=steps, error=action_error)
                steps += 1;errors += bool(action_error)
                history.append({'actor': actor, 'action': code, 'error': action_error})
                # A later privileged state-capture failure must not erase the
                # browser action that already completed.
                if session.task and hasattr(session.task, 'after_step'):
                    artifact = session.task.after_step(env, trace, steps)
                    trace.event('environment_state_captured', step=steps-1, artifact=artifact)
                if action_error:
                    # Preserve native failure; never replay a mutating action automatically.
                    emit({'kind': 'result', 'request_id': last_command, **state()})
                elif (terminated or truncated) and actor != 'agent':
                    stop_reason = 'environment_terminated' if terminated else 'environment_truncated'
                    break
                else:
                    emit({'kind': 'result', 'request_id': last_command, **state()})
        except BaseException as error:
            technical_error = type(error).__name__+': '+str(error)
            stop_reason = 'manual_driver_error'
            if trace: trace.event('manual_error', error=technical_error)
        finally:
            reference_evaluation = None
            if trace:
                if env is not None and obs is not None:
                    trace.event('evaluation_started', scope='reference_task_diagnostic_only')
                    try:
                        assessment = session.evaluate(env, trace, {'final_reward': reward, 'terminated': terminated,
                            'truncated': truncated, 'stop_reason': stop_reason, 'error': technical_error})
                        # Existing AX policy-delivery hooks are never called for a human.
                        assessment.injection_exposed = None;assessment.injection_avoided = None
                        if technical_error: assessment.technical_error = technical_error
                        assessment.limitations.append('Shared browser or manual exploration; this is only a reference-task diagnostic, not user-intent or model success. Exposure/avoidance is not graded for arbitrary requests.')
                        reference_evaluation = assessment.to_dict()
                    except Exception as error:
                        reference_evaluation = Evaluation('manual-reference-unavailable', '1', technical_error=type(error).__name__).to_dict()
                    write_json(trace.directory/'reference-evaluation.json', reference_evaluation)
                    trace.event('evaluation_completed', artifact='reference-evaluation.json', scope='reference_task_diagnostic_only')
                if env is not None:
                    trace.event('environment_close_started')
                    try: env.close()
                    except Exception as error:
                        technical_error = technical_error or type(error).__name__+': close failed'
                    trace.event('environment_closed')
                ask_records = [json.loads(p.read_text()) for p in sorted(trace.directory.glob('ask-*.json'))]
                model_attempts = [step for ask in ask_records for step in ask.get('steps', []) if step.get('dispatch_at')]
                models = sorted({step['request']['model'] for step in model_attempts})
                summary = {'driver': 'shared-browser' if agent_turns else args.actor, 'model': models[0] if len(models) == 1 else None,
                    'models': models, 'model_attempt_count': len(model_attempts), 'ask_records': [p.name for p in sorted(trace.directory.glob('ask-*.json'))], 'reference_goal': reference_goal,
                    'evaluation': None, 'reference_evaluation': reference_evaluation,
                    'stop_reason': stop_reason, 'error': technical_error, 'step_count': steps,
                    'browser_step_count': steps, 'agent_turn_count': agent_turns, 'action_error_count': errors, 'final_reward': reward,
                    'success': None, 'terminated': terminated, 'truncated': truncated,
                    'final_observation': frame['artifact'] if frame else None}
                trace.finish(summary)
                archive = output/'trace.zip'
                with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as z:
                    for f in sorted(trace.directory.rglob('*')):
                        if f.is_file() and not f.is_symlink(): z.write(f, str(f.relative_to(trace.directory.parent)))
                emit({'kind': 'finished', 'request_id': last_command, **state(), 'archive': str(archive),
                      'reference_evaluation': reference_evaluation, 'error': technical_error, 'stop_reason': stop_reason})


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--package', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--task', required=True)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--actor', choices=['human', 'scripted_validation'], default='human')
    parser.add_argument('--rpc-fd', type=int, default=3)
    parser.add_argument('--command-fd', type=int, default=4)
    run(parser.parse_args())
