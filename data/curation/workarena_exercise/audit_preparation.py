"""Offline source/contract checks. Does not import WorkArena or contact ServiceNow.

Executes only the two upstream validator method ASTs against synthetic inputs.
This is not a browser replay, native page validation, or model evaluation.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from urllib import parse
import zipfile

ROOT = Path(__file__).resolve().parents[3]
CACHE = ROOT / '.research/workarena-use-case-review'
WHEEL = CACHE / 'browsergym_workarena-0.5.3-py3-none-any.whl'
REVISION = 'a772230a94cf1caf4166b8ead3983f3b3786455b'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def method(source, class_name, method_name, namespace):
    tree = ast.parse(source)
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == class_name)
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == method_name)
    # Postpone annotations; retain the exact method body and its original semantics.
    unit = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), fn], type_ignores=[])
    ast.fix_missing_locations(unit)
    exec(compile(unit, f'upstream:{class_name}.{method_name}', 'exec'), namespace)
    return namespace[method_name]


def audit():
    with zipfile.ZipFile(WHEEL) as wheel:
        sources = {}
        for path in sorted((CACHE / 'src/browsergym/workarena').rglob('*.py')):
            relative = path.relative_to(CACHE / 'src').as_posix()
            raw = path.read_bytes()
            assert wheel.read(relative) == raw, f'Wheel/source mismatch: {relative}'
            sources[relative] = digest(raw)
        configs_raw = wheel.read('browsergym/workarena/data_files/task_configs/order_standard_laptop_task.json')
        selected = json.loads(configs_raw)[70]
        assert selected == {
            'configuration': {'Additional software requirements': ['textarea', 'Slack'],
                              'Adobe Acrobat': ['checkbox', False], 'Adobe Photoshop': ['checkbox', False]},
            'description': 'Lenovo - Carbon x1', 'item': 'Standard Laptop', 'quantity': 1}
        list_source = wheel.read('browsergym/workarena/tasks/list.py').decode()
        catalog_source = wheel.read('browsergym/workarena/tasks/service_catalog.py').decode()

    extraction = method(list_source, 'ExtractListInfoTask', 'validate', {'json': json})
    task = SimpleNamespace(fields={'assigned_to': 'Assigned to', 'warranty_expiration': 'Warranty expiration'},
                           unique_field_name='assigned_to',
                           expected_values=[{'assigned_to': 'Synthetic Person', 'warranty_expiration': '2027-09-15'}])
    answers = []
    for label, answer, expected_reward in [
        ('generic_done', 'Done', 0),
        ('correct_iso_date', '2027-09-15', 1),
        ('incorrect_date', '2027-09-16', 0),
        ('negated_correct_date', 'The expiry is NOT 2027-09-15; it is 2027-09-16.', 1),
        ('two_conflicting_dates', '2027-09-15 or 2027-09-16', 1),
        ('equivalent_human_date', '15 September 2027', 0),
    ]:
        result = extraction(task, None, [{'role': 'assistant', 'message': answer}])
        assert result[0] == expected_reward, label
        answers.append({'id': label, 'synthetic_answer': answer, 'raw_upstream_result': result})

    # Native catalog validator against a synthetic persisted request, with zero sleep/network.
    namespace = {'parse': parse, 'sleep': lambda seconds: None}
    helper = next(n for n in ast.parse(catalog_source).body if isinstance(n, ast.FunctionDef) and n.name == 'option_match_heuristic')
    exec(compile(ast.Module(body=[helper], type_ignores=[]), 'upstream:option_match_heuristic', 'exec'), namespace)
    validate_catalog = method(catalog_source, 'OrderHardwareTask', 'validate', namespace)
    page = SimpleNamespace(evaluate=lambda script: 'https://synthetic.invalid/checkout?sysparm_sys_id=synthetic_request')
    catalog_results = []
    for label, acrobat, software, quantity, expected_reward in [
        ('requested_configuration', 'false', 'Slack', '1', 1),
        ('unwanted_acrobat', 'true', 'Slack', '1', 0),
        ('unrequested_textarea_extra', 'false', 'Slack, unrequested software', '1', 1),
        ('duplicate_quantity', 'false', 'Slack', '2', 0),
    ]:
        receipt = {'items': [{'short_description': 'Lenovo - Carbon x1', 'quantity': quantity,
                             'options': {'Adobe Acrobat': acrobat, 'Adobe Photoshop': 'false',
                                         'Additional software requirements': software}}]}
        namespace['get_request_by_id'] = lambda instance, sysid, receipt=receipt: receipt
        task = SimpleNamespace(instance=None, short_description=selected['description'], quantity=1,
                               requested_configuration=selected['configuration'])
        result = validate_catalog(task, page, [])
        assert result[0] == expected_reward, label
        catalog_results.append({'id': label, 'synthetic_request': receipt, 'raw_upstream_result': result})

    runner = (ROOT / 'intent_browser/runner.py').read_bytes()
    return {
        'schema': 'workarena-exercise-preparation-v1', 'source_revision': REVISION,
        'scope': 'Exact upstream validator bodies executed on synthetic objects; no native page or model execution.',
        'service_access': 'user_requested_pending_review', 'runnable_ready': False, 'training_eligible': False,
        'wheel': {'path': str(WHEEL.relative_to(ROOT)), 'sha256': digest(WHEEL.read_bytes()),
                  'bytes': WHEEL.stat().st_size, 'version': '0.5.3'},
        'matched_source_files': sources, 'catalog_file_sha256': digest(configs_raw),
        'catalog_config_index_zero_based': 70, 'catalog_config': selected,
        'answer_checks': answers, 'catalog_checks': catalog_results,
        'runner': {'sha256': digest(runner), 'generic_done_instruction_present': b"use send_msg_to_user('Done')" in runner},
        'limitations': ['Source-method isolation does not check imports, real instance schema, UI, setup or cleanup.',
                        'Upstream answer scoring is substring-based; contradictory answers can receive reward.',
                        'Upstream textarea scoring permits additional software text.',
                        'Upstream catalog check follows current URL request; entire-run order coverage is not established.',
                        'No credentials, expected real task answers, browser requests, or paid calls are included.'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    # Reject existing files including dangling symlinks before any source execution.
    if args.output.exists() or args.output.is_symlink():
        raise SystemExit('Refusing to overwrite an existing output')
    report = audit()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    print(f'{len(report["matched_source_files"])} source matches; 10 offline validator cases passed. No browser/model calls.')


if __name__ == '__main__':
    main()
