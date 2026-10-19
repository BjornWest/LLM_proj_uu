"""One harness episode per child process; trace events cross a queue to HTTP/SSE."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
MODEL = 'qwen/qwen3.8-27b'


def episode_main(payload, output, events, controls, cdp_url=None, scripted=None):
    os.setsid()
    from dotenv import load_dotenv
    load_dotenv('/home/bjorn/code/LLM_proj_uu/.env', override=False)
    from intent_browser import runner
    from intent_browser.trace import Trace
    from intent_browser.open_internet import OpenInternetTask, open_profile, with_human_handover
    from intent_browser.standard_profile import standard_profile
    from intent_browser.human_handover import HumanHandoverController
    from intent_browser.backend import ChatCompletionsBackend, Completion
    from intent_browser.openrouter import provider_options, DEFAULT_PROVIDERS
    from intent_browser.actions import make_action_set

    sources, seen_tabs = {}, {}
    last_site = None
    final = None
    initial_chat_count = 0
    controller = HumanHandoverController() if cdp_url else None
    env_holder = []

    def emit(kind, **data):
        events.put({'type': kind, **data})

    class LiveTrace(Trace):
        def event(self, kind, **data):
            nonlocal initial_chat_count
            super().event(kind, **data)
            if kind == 'environment_reset_completed':
                initial_chat_count = len(env_holder[0].raven_chat.messages)
            if kind in ('tool_started', 'batch_call_started'):
                args = data.get('arguments', {})
                name = data.get('tool', 'Inspecting page')
                summary = name.replace('_', ' ')
                if args.get('url'):
                    summary += ': ' + args['url']
                emit('step', index=data.get('step', 0), summary=summary[:240])
            if kind == 'human_tab_transition':
                t = data['transition']
                events.put({'_controller': controller.snapshot()})
                if t['event'] == 'handover':
                    emit('handover', tab_id=t['tab_id'], message=t.get('reason') or 'Your help is needed.')

        def observation(self, index, obs, text, **kwargs):
            nonlocal last_site
            ref = super().observation(index, obs, text, **kwargs)
            human = obs.get('human_tabs', {})
            tabs = human.get('tabs', [])
            if not tabs:
                tabs = [dict(tab_id=f'tab-{i+1}', url=url,
                             title=(list(obs.get('open_pages_titles', [])) + [''] * 64)[i], state='agent_controlled')
                        for i, url in enumerate(obs.get('open_pages_urls', []))]
            active = human.get('active_tab_id')
            if not active:
                active = f"tab-{int(obs.get('active_page_index', [0])[0])+1}"
            current = {}
            for t in tabs:
                if t.get('state') == 'closed':
                    continue
                tid = t['tab_id']
                row = dict(tab_id=tid, url=t['url'], title=t.get('title') or '',
                           owner='agent' if t.get('state') == 'agent_controlled' else 'human', active=tid == active)
                current[tid] = row
                if tid not in seen_tabs:
                    emit('tab', action='opened', **{k: v for k, v in row.items() if k != 'active'})
                elif row['active'] and not seen_tabs[tid].get('active'):
                    emit('tab', action='focused', **{k: v for k, v in row.items() if k != 'active'})
            for tid, row in seen_tabs.items():
                if tid not in current:
                    emit('tab', action='closed', **{k: v for k, v in row.items() if k != 'active'})
            seen_tabs.clear()
            seen_tabs.update(current)
            events.put({'_tabs': list(current.values())})
            url = obs.get('url', '')
            title = current.get(active, {}).get('title') or urlsplit(url).hostname or url
            if (url, active) != last_site:
                emit('site', url=url, title=title, favicon=None, tab_id=active)
                last_site = (url, active)
            if url.startswith(('http://', 'https://')):
                # Store only text actually present in the recorded native AX capture.
                nodes = obs.get('axtree_object', {}).get('nodes', [])
                excerpt = '\n'.join(n.get('name', {}).get('value', '') for n in nodes if n.get('name', {}).get('value'))
                if excerpt.strip():
                    sources[url] = dict(id='source-' + str(list(sources).index(url)+1 if url in sources else len(sources)+1),
                        kind='offer', url=url, title=title, siteName=urlsplit(url).hostname,
                        evidence=excerpt[:12000], checkedAt=datetime.now(timezone.utc).isoformat())
            if env_holder and cdp_url:
                env = env_holder[0]
                mapping = {}
                custody = getattr(env._active_page_check, '__self__', None)
                for tid, page in getattr(custody, 'pages', {}).items():
                    if page.is_closed():
                        continue
                    session = env.context.new_cdp_session(page)
                    mapping[tid] = session.send('Target.getTargetInfo')['targetInfo']['targetId']
                    session.detach()
                events.put({'_targets': mapping})
            return ref

    runner.Trace = LiveTrace  # Process-local integration, never mutates another episode.
    def control_loop():
        while True:
            command = controls.get()
            if command.get('action') == 'handback' and controller:
                try:
                    tab = next(t for t in controller.snapshot()['tabs'] if t['tab_id'] == command['tab_id'])
                    if tab['state'] == 'awaiting_human':
                        controller.signal(tab['tab_id'], 'start')
                    controller.signal(tab['tab_id'], 'complete')
                    # Note is delivered through the same trusted chat ingress as native handover UI.
                    if command.get('note') and env_holder:
                        env_holder[0].chat._js_user_message_received_callback(msg=command['note'])
                except Exception as exc:
                    emit('error', message=str(exc))
    threading.Thread(target=control_loop, daemon=True).start()
    profile = open_profile(standard_profile(helpers=False, data_tools=False))
    if cdp_url:
        profile = with_human_handover(profile, wait_for_human=True, compact_tabs=True,
                                     stable_frames=True, capture_timeout_mode='bounded')
    history = '\n'.join(f"{m['who']}: {m['text']}" for m in payload.get('history', []))
    goal = (('Previous conversation (context):\n' + history + '\n\n') if history else '') + payload['text']
    goal += '\n\nAnswer with Markdown links to the pages you actually inspected. Do not purchase or create accounts.'
    task = OpenInternetTask('https://www.google.com/', goal, headless=not bool(cdp_url))
    task.supported_harness_profiles = (profile.name,)
    if cdp_url:
        from apps.raven.shared_browser import SharedBrowserEnv, SharedWebTask
        original_prepare = task.prepare
        def prepare(trace):
            record = original_prepare(trace)
            record['isolation'] = 'Dedicated persistent Raven demo profile, shared visible Chromium over CDP'
            return record
        task.prepare = prepare
    def factory(video):
        actions = make_action_set(profile.tools.names)
        if cdp_url:
            env = SharedBrowserEnv(cdp_url, task_entrypoint=SharedWebTask,
                task_kwargs=dict(start_url=task.start_url, goal=goal), headless=False,
                action_mapping=actions.to_python_code, wait_for_user_message=False)
        else:
            from apps.raven.shared_browser import BackgroundBrowserEnv
            from intent_browser.open_internet import OpenWebTask
            env = BackgroundBrowserEnv(task_entrypoint=OpenWebTask,
                task_kwargs=dict(start_url=task.start_url, goal=goal, record=task.trace.event),
                headless=True, action_mapping=actions.to_python_code, wait_for_user_message=False,
                pw_context_kwargs={'accept_downloads':False, 'service_workers':'block'})
        env_holder.append(env)
        return env
    if scripted is not None:
        class ScriptedBackend:
            supports_background_completion = True
            supports_images = True
            supports_native_tools = True
            def configure_tools(self, options): pass
            def complete(self, messages):
                action = scripted.pop(0)
                return Completion('', {'choices': [{'message': {'role': 'assistant', 'content': None,
                    'tool_calls': [{'id': 'call-' + str(len(scripted)), 'type': 'function', 'function': action}]}, 'finish_reason': 'tool_calls'}]})
            def close(self): pass
        backend = ScriptedBackend()
        backend.model = MODEL
    else:
        backend = ChatCompletionsBackend('https://openrouter.ai/api/v1', MODEL,
            os.environ['OPENROUTER_API_KEY'], supports_images=True,
            request_options=provider_options(os.getenv('OPENROUTER_PROVIDERS') or DEFAULT_PROVIDERS))
        backend.sampling = {'temperature': 0.6}
    metadata = dict(task='openended', goal=goal, model=MODEL if scripted is None else 'scripted',
        driver='llm' if scripted is None else 'scripted', tags=['raven'] if scripted is None else ['raven', 'scripted'],
        source='open-internet-v1', training_eligible=False, headless=not bool(cdp_url),
        generation={'temperature': 0.6}, conversation_id=payload.get('conversation_id'))
    try:
        emit('status', state='working')
        directory, summary = runner.run_episode(factory, backend, metadata, output, 40, episode_task=task,
            harness_profile=profile, human_handover=controller, observation_pipeline='auto', trace_screenshots=False,
            max_input_tokens=100000, allow_ungraded=True, ungraded_reason='Raven supervised live-web demo',
            terminal_response_instruction='Answer the user with findings, Markdown source links and uncertainties using send_msg_to_user.')
        emit('status', state='finishing')
        # The authoritative BrowserGym chat also handles batched terminal actions.
        if env_holder:
            messages = getattr(getattr(env_holder[0], 'raven_chat', None), 'messages', [])
            answers = [m['message'] for m in messages[initial_chat_count:] if m['role'] == 'assistant']
            if answers:
                final = answers[-1]
        if final:
            captured = list(sources.values())
            for source in captured:
                if source['url'] in final:
                    final = final.replace('](' + source['url'] + ')', '](' + source['url'] + ') [[' + source['id'] + ']]')
            emit('final', markdown=final, sources=captured)
        elif summary.get('error'):
            emit('error', message=summary['error'])
        else:
            emit('error', message='The episode ended before the agent supplied an answer.')
        events.put({'_trace': str(directory)})
        emit('done', stop_reason=summary['stop_reason'])
    except Exception as exc:
        emit('error', message=f'{type(exc).__name__}: {exc}')
        emit('done', stop_reason='error')
    finally:
        backend.close()
