"""Scripted native reference-field comparison; no model or search calls.

Privileged setup and state reads are diagnostic, never policy input. Each trial
reopens the list and creates a blank Assigned to filter for the same target.
The tested BrowserGym actions go through the unchanged parser/action mapping.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / '.local/workarena-exercise/vendor'))
sys.path.insert(0, str(ROOT))
from browsergym.core.env import BrowserEnv
from browsergym.utils.obs import flatten_axtree_to_str
from browsergym.workarena.tasks.compositional.warranty_check import GetWarrantyExpirationDateTask
from browsergym.workarena.tasks.utils.form import fill_text
from PIL import Image
from intent_browser.actions import make_action_set, parse_action
from intent_browser.workarena_exercise import native_instance, selected_record


def write(path, obj):
    with path.open('x') as f:
        json.dump(obj, f, indent=2, default=str)
        f.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--rounds', type=int, default=2, choices=[1, 2])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    instance = native_instance()
    report = {'schema': 'workarena-reference-comparison-v1', 'model_calls': 0,
              'driver': 'privileged_scripted', 'training_eligible': False,
              'started_at': datetime.now(timezone.utc).isoformat(),
              'trials': [], 'cleanup': [], 'error_type': None,
              'limitations': ['Same synthetic target and session; fresh list document per trial, not independent sessions.',
                             'Diagnostic reads include hidden reference state; not evidence delivered to a model.',
                             'No broad authorization or model task-success claim.']}
    env = BrowserEnv(task_entrypoint=GetWarrantyExpirationDateTask,
                     task_kwargs={'instance': instance, 'level': 2}, headless=True,
                     slow_mo=250, wait_for_user_message=False,
                     action_mapping=make_action_set().to_python_code)
    cleanup = []

    def capture(directory, label):
        obs = env._get_obs()
        text = flatten_axtree_to_str(obs['axtree_object'])
        (directory / (label + '.txt')).write_text(text)
        Image.fromarray(obs['screenshot']).save(directory / (label + '.png'))
        return text

    def state(row):
        return row.locator('#value input').evaluate_all('''es => es.map(e => ({
          id:e.id,type:e.type,value:e.value,visible:!!e.getClientRects().length,
          expanded:e.getAttribute('aria-expanded'),autocomplete:e.getAttribute('aria-autocomplete'),
          resolving:e.ac && typeof e.ac.isResolving==='function' ? e.ac.isResolving() : null
        }))''')

    def action(trial, code):
        begin = time.time()
        obs, reward, terminated, truncated, info = env.step(parse_action(code))
        trial['actions'].append({'code': code, 'started_epoch': begin,
                                 'finished_epoch': time.time(), 'error': obs['last_action_error']})
        if obs['last_action_error']:
            raise RuntimeError('Scripted BrowserGym action failed')

    try:
        env.reset(seed=706)
        task = env.task
        for attr, table in [('_base_user_sysid', 'sys_user'), ('user_sys_id', 'sys_user'),
                            ('laptop_sys_id', 'alm_hardware')]:
            cleanup.append((table, getattr(task, attr)))
        before = {table + ':' + identity: selected_record(instance, table, identity)
                  for table, identity in cleanup[1:]}
        report['target'] = {'name': task.user_full_name, 'owner_id': task.user_sys_id,
                            'hardware_id': task.laptop_sys_id, 'expected_date': task.warranty_expiration_date}
        filter_task = task.subtasks[1]
        methods = ['plain_fill', 'autocomplete_only', 'autocomplete_select', 'upstream_select']
        for round_index in range(args.rounds):
            for method in methods if round_index == 0 else list(reversed(methods)):
                trial = {'method': method, 'round': round_index + 1, 'actions': []}
                report['trials'].append(trial)
                directory = args.output / f'{round_index + 1}-{method}'
                directory.mkdir()
                # Reload native list without carrying the previous query.
                env.page.goto(instance.snow_url + '/now/nav/ui/classic/params/target/alm_hardware_list.do')
                filter_task._wait_for_ready(env.page)
                iframe, _, _ = filter_task._get_visible_list(env.page)
                if not iframe.locator('.list_filter').first.is_visible():
                    iframe.locator('.list_filter_toggle').click()
                iframe.locator('.list_filter').first.wait_for(state='visible')
                while iframe.locator('.filerTableAction.deleteButton:visible').count():
                    iframe.locator('.filerTableAction.deleteButton:visible').first.click()
                env.page.wait_for_timeout(3000)
                row = iframe.locator('.filter_row').first
                row.locator('select.filerTableSelect').first.select_option('assigned_to')
                row.locator('select.condOperator').select_option('=')
                field = row.locator('#value input:visible').first
                # Native reference initialization happens on focus and replaces
                # the initial input. Establish this common blank precondition
                # before marking/targeting the field in every comparison arm.
                field.click()
                field = row.locator('#value input[aria-autocomplete="list"]:visible')
                field.wait_for(state='visible', timeout=15000)
                capture(directory, 'blank')
                trial['blank_state'] = state(row)
                bid = field.get_attribute('bid')
                assert bid and field.input_value() == ''
                if method == 'upstream_select':
                    fill_text(env.page, field, task.user_full_name, iframe)
                else:
                    suffix = ', enable_autocomplete_menu=True' if method != 'plain_fill' else ''
                    action(trial, f'fill({bid!r}, {task.user_full_name!r}{suffix})')
                trial['after_fill_state'] = state(row)
                capture(directory, 'after-fill')
                if method == 'autocomplete_select':
                    iframe.wait_for_function('''() => {
                      const e=document.querySelector('.filter_row #value input[aria-autocomplete="list"]');
                      return e && e.getAttribute('aria-expanded')==='true' && !e.ac.isResolving();
                    }''', timeout=15000)
                    options = iframe.locator('[id^="ac_option_"]')
                    match = None
                    for index in range(options.count()):
                        option = options.nth(index)
                        main = option.locator('.ac_cell').first if option.locator('.ac_cell').count() else option
                        if (main.text_content() or '').strip().casefold() == task.user_full_name.casefold():
                            match = option
                            break
                    assert match is not None, 'Exact autocomplete option absent'
                    capture(directory, 'options')
                    action(trial, f'click({match.get_attribute("bid")!r})')
                # Keep the delay explicit: plain fill gets ample resolution time too.
                begin = time.time()
                env.page.wait_for_timeout(10000)
                trial['settle_seconds'] = time.time() - begin
                trial['before_run_state'] = state(row)
                capture(directory, 'before-run')
                run = iframe.locator('.filterToolbar').get_by_text('Run', exact=True)
                action(trial, f'click({run.get_attribute("bid")!r})')
                filter_task._wait_for_ready(env.page)
                text = capture(directory, 'after-run')
                info = filter_task._extract_list_info(env.page)
                trial['query'] = info['query']
                trial['exact_target_query'] = info['query'] == 'assigned_to=' + task.user_sys_id
                trial['native_filter_result'] = filter_task.validate(env.page, env.chat.messages)
                trial['target_name_in_result_ax'] = task.user_full_name in text
                trial['expected_date_in_result_ax'] = task.warranty_expiration_date in text
                write(directory / 'result.json', trial)
                print(json.dumps({k: trial[k] for k in ['method', 'round', 'query', 'exact_target_query']}), flush=True)
        after = {table + ':' + identity: selected_record(instance, table, identity)
                 for table, identity in cleanup[1:]}
        report['scoped_records_unchanged'] = before == after
        report['scoped_before'] = before
        report['scoped_after'] = after
    except Exception as exc:
        report['error_type'] = type(exc).__name__
        report['error_stack'] = [{'file': Path(f.filename).name, 'line': f.lineno, 'function': f.name}
                                 for f in traceback.extract_tb(exc.__traceback__)]
        try: capture(args.output, 'failure')
        except Exception: pass
    finally:
        if not cleanup and env.task:
            for attr, table in [('_base_user_sysid', 'sys_user'), ('user_sys_id', 'sys_user'),
                                ('laptop_sys_id', 'alm_hardware')]:
                identity = getattr(env.task, attr, None)
                if identity: cleanup.append((table, identity))
        try:
            env.close()
            report['close_completed'] = True
        except Exception as exc:
            report['close_completed'] = False
            report['close_error_type'] = type(exc).__name__
            for resource in [env.context, env.browser]:
                if resource:
                    try: resource.close()
                    except Exception: pass
        for table, identity in cleanup:
            try:
                absent = not selected_record(instance, table, identity)
            except Exception:
                absent = None
            report['cleanup'].append({'table': table, 'sys_id': identity, 'absent_after_close': absent})
        sources = [Path(__file__), ROOT / 'intent_browser/actions.py',
                   Path(sys.modules['browsergym.core.action.functions'].__file__),
                   Path(sys.modules['browsergym.workarena.tasks.utils.form'].__file__)]
        report['source_sha256'] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        write(args.output / 'report.json', report)
        write(args.output / 'artifact-hashes.json', {str(p.relative_to(args.output)): hashlib.sha256(p.read_bytes()).hexdigest()
                                                   for p in args.output.rglob('*') if p.is_file()})
    print(json.dumps({'output': str(args.output), 'error_type': report['error_type'],
                      'trials': len(report['trials']), 'cleanup': report['cleanup']}))


if __name__ == '__main__':
    main()
