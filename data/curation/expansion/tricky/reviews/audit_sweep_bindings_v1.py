"""Read-only independent sweep-binding audit; no adapter import or browser calls.

python3 -m data.curation.expansion.tricky.reviews.audit_sweep_bindings_v1 \
  --input .local/curation-expansion/sweep-inputs-169-v2.json --output NEW.json
"""
import argparse
import ast
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[5]
DEFAULT_NATIVE_TERMINAL = "After the goal is complete, call send_msg_to_user with text set to 'Done'."


def load(path):
    return json.loads((ROOT / path).read_text())


def sha(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def effective_terminal(value):
    return DEFAULT_NATIVE_TERMINAL if value is None else value


def audit(path):
    export = load(path)
    pins = {}
    for item in walk(export):
        if set(item) == {'path', 'sha256'}:
            pins[item['path']] = item['sha256']
    pin_mismatches = [name for name, digest in pins.items() if sha(name) != digest]
    builder_path = Path(export['builder']['path'])
    if sha(builder_path) != export['builder']['sha256']:
        builder_path = Path('.local/curation-expansion/sweep-inputs-exporter-v2.py')
        assert sha(builder_path) == export['builder']['sha256']
    source = ast.parse((ROOT / builder_path).read_text())
    # Execute only the pure policy projection function; never import a task adapter.
    projection_node = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == 'policy_projection')
    namespace = {}
    exec(compile(ast.Module(body=[projection_node], type_ignores=[]), '<projection-only>', 'exec'), namespace)
    project = namespace['policy_projection']
    source_tasks = {str(t['task_id']): t for t in load('.local/webarena-verified/dataset.json')}
    checks = Counter()
    mismatches = []
    trace_rows = []
    missing = []
    adapter_symbols = set()
    for binding in export['tasks']:
        task_id = binding['id']
        projected = project({**binding, 'grader_input': {'secret': 'AUDIT_PRIVATE_SENTINEL'},
                             'evaluation': {'safe_success': True}})
        assert set(projected) == {'goal', 'terminal_response_instruction'}
        assert 'AUDIT_PRIVATE_SENTINEL' not in json.dumps(projected)
        assert isinstance(projected['goal'], str) and projected['goal']
        assert projected['terminal_response_instruction'] is None or isinstance(projected['terminal_response_instruction'], str)
        assert all(binding[key] is False for key in ('model_tested', 'training_eligible', 'production_ready', 'new_execution_ready'))
        assert binding['reference_runtime_for_new_offline_profile']['historical_execution_identity'] is False
        contract = load(binding['private_contract']['path'])
        if binding['dataset'] == 'trickyarena':
            selected = next(t for t in contract['tasks'] if t['id'] == binding['private_contract_row_id'])
            assert projected['goal'] == selected['policy_input']['goal']
        else:
            selected = source_tasks[task_id.split(':')[1]]
            assert projected['goal'] == selected['intent']
        checks['goal_and_policy_boundary'] += 1
        for field in ('factory', 'browser_task'):
            entry = binding['implementation'].get(field)
            if entry:
                tree = ast.parse((ROOT / entry['source']['path']).read_text())
                assert any(isinstance(n, ast.ClassDef) and n.name == entry['symbol'] for n in tree.body)
                adapter_symbols.add((entry['source']['path'], entry['symbol']))
        seen = set()
        for review in binding['review_references']:
            for item in walk(load(review['path'])):
                trace = item.get('trace')
                if not isinstance(trace, str) or trace in seen or not (ROOT / trace / 'episode.json').exists():
                    continue
                episode = load(str(Path(trace) / 'episode.json'))
                prefix = 'tricky:' if binding['dataset'] == 'trickyarena' else 'webarena:'
                recorded_id = prefix + str(episode.get('task_id', episode.get('source_task_id')))
                if recorded_id != task_id or episode.get('harness_profile', {}).get('name') != 'core-tools-v3':
                    continue
                seen.add(trace)
                for field in ('max_steps', 'observation_text_limit'):
                    expected = binding['validation_profile'][field]
                    if expected != episode[field]:
                        mismatches.append({'id': task_id, 'field': field, 'exported': expected,
                                           'recorded': episode[field], 'trace': trace})
                terminal = effective_terminal(projected['terminal_response_instruction'])
                if terminal != episode['terminal_response_instruction']:
                    mismatches.append({'id': task_id, 'field': 'terminal_response_instruction', 'trace': trace})
                with (ROOT / trace / 'steps.jsonl').open() as stream:
                    first = json.loads(next(stream))
                messages = first['model_request']['messages']
                assert terminal in '\n'.join(m.get('content') or '' for m in messages if m['role'] == 'system')
                assert any((m.get('content') or '').split('\n\nCURRENT BROWSER OBSERVATION\n')[0] == 'USER GOAL: ' + projected['goal'] for m in messages), (task_id, trace)
                trace_rows.append({'id': task_id, 'trace': trace,
                                   'episode_sha256': sha(str(Path(trace) / 'episode.json')),
                                   'steps_sha256': sha(str(Path(trace) / 'steps.jsonl')),
                                   'max_steps': episode['max_steps'],
                                   'authorization_satisfied': episode['evaluation'].get('authorization_satisfied'),
                                   'safe_success': episode['evaluation'].get('safe_success')})
                checks['saved_native_policy_and_protocol'] += 1
        if not seen:
            missing.append(task_id)
    # These imports stop at the explicit runtime assertion, before any BrowserGym
    # imports, environment creation, or inference. Disable bytecode file writes.
    env = dict(os.environ)
    env.pop('CURATION_FROZEN_RUNTIME', None)
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    imports = []
    for module in ('data.curation.expansion.webarena_biography.run',
                   'data.curation.expansion.webarena_coupon.run_v2'):
        result = subprocess.run([sys.executable, '-c', 'import ' + module], cwd=ROOT, env=env,
                                text=True, capture_output=True, timeout=15)
        assert result.returncode != 0 and 'AssertionError' in result.stderr
        imports.append({'module': module, 'without_runtime_environment': 'AssertionError',
                        'returncode': result.returncode, 'stderr': result.stderr})
    required_ids = {'webarena:399', 'webarena:407'} | {'webarena:' + str(n) for n in range(689, 694)}
    runtime_gaps = [b['id'] for b in export['tasks'] if b['id'] in required_ids and
                    b['implementation'].get('pre_import_runtime_activation', {}).get('required') is not True]
    findings = []
    if runtime_gaps:
        findings.append({'id': 'SWEEP-BINDINGS-RUNTIME', 'tasks': runtime_gaps,
                        'description': 'Factory modules require CURATION_FROZEN_RUNTIME at import; binding omits required activation.',
                        'fix': 'Bind required pre-import activation and pin runtime_snapshot.py; retain historical-versus-new distinction.'})
    if mismatches:
        findings.append({'id': 'SWEEP-BINDINGS-CAP', 'tasks': sorted({m['id'] for m in mismatches}),
                        'description': 'Exported profile differs from accepted native episodes; see historical_profile_mismatches.',
                        'fix': 'Preserve recorded settings or explicitly declare a new profile amendment.'})
    return {'schema': 'independent-sweep-bindings-review-v1', 'coordination_id': 'SWEEP-BINDINGS-01',
            'status': 'requires_binding_amendments' if findings else 'accepted_invocation_preparation_only', 'input': str(path), 'input_sha256': sha(path),
            'builder': export['builder'], 'reviewer_sha256': sha(Path(__file__).relative_to(ROOT)),
            'counts': export['counts'], 'checks': dict(checks), 'unique_adapter_symbols': len(adapter_symbols),
            'reference_hashes_checked': len(pins), 'reference_hash_mismatches': pin_mismatches,
            'missing_task_evidence': missing, 'historical_profile_mismatches': mismatches,
            'required_runtime_import_checks': imports, 'records': trace_rows,
            'findings': findings,
            'nonblocking_notes': [
                'Null terminal instruction deliberately selects the copied native runner Done default; it is not missing policy delivery.',
                'A profile name alone is not a constructor call. New execution should bind native_tools_profile(parallel_tool_calls=None, compact_feedback=True, reasoning_replay="preserve") and its source closure.',
                'Factory recipe references are not executable sweep configuration; external factories still require explicit account headers, routing, HAR recording, callbacks and cleanup.',
                'Unknown authorization/safety in recorded outcomes remains unknown; success is not promoted to model evidence.',
                'This audit does not certify live services, runtime readiness, budgets, or new model execution.'],
            'browser_calls': 0, 'model_calls': 0, 'shared_edits': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with args.output.open('x') as output:
        report = audit(args.input)
        json.dump(report, output, indent=2)
        output.write('\n')
    print(json.dumps({key: report[key] for key in ('status', 'counts', 'checks', 'reference_hash_mismatches', 'missing_task_evidence')}))


if __name__ == '__main__':
    main()
