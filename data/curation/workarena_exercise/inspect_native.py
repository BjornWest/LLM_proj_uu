"""Privileged native WorkArena inspection, never model capability evidence."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / '.local/workarena-exercise/vendor'))
sys.path.insert(0, str(ROOT))
from browsergym.core.env import BrowserEnv
from browsergym.utils.obs import flatten_axtree_to_str
from browsergym.workarena.instance import SNowInstance
from browsergym.workarena.tasks.compositional.warranty_check import GetWarrantyExpirationDateTask
from browsergym.workarena.tasks.service_catalog import OrderStandardLaptopTask
from browsergym.workarena.api.utils import table_api_call
from PIL import Image
from intent_browser.actions import make_action_set


def write(path, value):
    with path.open('x') as f:
        json.dump(value, f, indent=2, default=str)
        f.write('\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task', choices=['warranty', 'catalog'], required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--solve', action='store_true', help='Use upstream privileged cheat driver (not a model).')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    secret = json.loads((ROOT / '.local/workarena-exercise/private/selected-instance.json').read_text())
    instance = SNowInstance(snow_url=secret['url'], snow_credentials=(secret['username'], secret['password']))
    kwargs = {'instance': instance}
    if args.task == 'warranty':
        entrypoint = GetWarrantyExpirationDateTask
        kwargs['level'] = 2
    else:
        entrypoint = OrderStandardLaptopTask
        config = json.loads((ROOT / 'data/curation/workarena_exercise/exercise.json').read_text())
        kwargs['fixed_config'] = config['conditions'][1]['fixed_config']
    report = {'schema': 'workarena-native-inspection-v1', 'task': args.task,
              'started_at': datetime.now(timezone.utc).isoformat(),
              'driver': 'upstream_privileged_cheat' if args.solve else 'native_setup_and_inspection',
              'model_calls': 0, 'training_eligible': False, 'captures': [], 'evaluations': [],
              'reset_complete': False, 'cleanup': [], 'error_type': None}
    env = BrowserEnv(task_entrypoint=entrypoint, task_kwargs=kwargs, headless=True,
                     slow_mo=250, wait_for_user_message=False,
                     action_mapping=make_action_set().to_python_code)
    def capture(label, obs=None):
        obs = obs if obs is not None else env._get_obs()
        text = flatten_axtree_to_str(obs['axtree_object'])
        (args.output / f'{label}.txt').write_text(text)
        Image.fromarray(obs['screenshot']).save(args.output / f'{label}.png')
        row = {'label': label, 'url': obs['url'], 'goal': obs['goal'], 'last_action_error': obs['last_action_error'],
               'text_sha256': hashlib.sha256(text.encode()).hexdigest(), 'text_characters': len(text)}
        report['captures'].append(row)
        write(args.output / f'{label}.json', row)
    cleanup_ids = []
    try:
        obs, info = env.reset(seed=701)
        report['reset_complete'] = True
        capture('initial', obs)
        if args.task == 'warranty':
            write(args.output / 'privileged-task.json', {k: getattr(env.task, k) for k in
                  ['user_full_name', 'user_sys_id', 'laptop_sys_id', 'warranty_expiration_date']})
        if args.solve:
            if args.task == 'warranty':
                for i in range(len(env.task)):
                    print(f'Privileged subtask {i}: {type(env.task.subtasks[i]).__name__}', flush=True)
                    env.task.cheat(env.page, env.chat.messages, i)
                    capture(f'after-subtask-{i}')
                    report['evaluations'].append(env.task.validate(env.page, env.chat.messages))
            else:
                env.task.cheat(env.page, env.chat.messages)
                capture('after-order')
                report['evaluations'].append(env.task.validate(env.page, env.chat.messages))
        report['final_native_result'] = env.task.validate(env.page, env.chat.messages)
    except Exception as exc:
        report['error_type'] = type(exc).__name__
        # Keep useful stack locations without exception text, URLs, locals or credentials.
        import traceback
        report['error_stack'] = [{'file': Path(f.filename).name, 'line': f.lineno, 'function': f.name}
                                 for f in traceback.extract_tb(exc.__traceback__)]
        try: capture('failure')
        except Exception: pass
    finally:
        task = env.task
        if task:
            for attr, table in [('_base_user_sysid', 'sys_user'), ('user_sys_id', 'sys_user'),
                                ('laptop_sys_id', 'alm_hardware'), ('request_sysid', 'sc_request')]:
                value = getattr(task, attr, None)
                if value: cleanup_ids.append((attr, table, value))
        try:
            env.close()
            report['close_completed'] = True
        except Exception as exc:
            report['close_completed'] = False
            report['close_error_type'] = type(exc).__name__
            # Stop browser resources if upstream teardown raises; do not hide failed record cleanup.
            for resource in [env.context, env.browser]:
                if resource:
                    try: resource.close()
                    except Exception: pass
        for attr, table, value in cleanup_ids:
            try:
                result = table_api_call(instance, table, params={'sysparm_query': f'sys_id={value}', 'sysparm_fields': 'sys_id'})['result']
                report['cleanup'].append({'attribute': attr, 'table': table, 'sys_id': value, 'absent_after_close': not result})
            except Exception as exc:
                report['cleanup'].append({'attribute': attr, 'table': table, 'sys_id': value, 'absent_after_close': None, 'error_type': type(exc).__name__})
        report['finished_at'] = datetime.now(timezone.utc).isoformat()
        report['script_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
        write(args.output / 'report.json', report)
    print(json.dumps({'output': str(args.output), 'reset': report['reset_complete'], 'error_type': report['error_type'],
                      'native_result': report.get('final_native_result'), 'cleanup': [x['absent_after_close'] for x in report['cleanup']], 'model_calls': 0}))


if __name__ == '__main__':
    main()
