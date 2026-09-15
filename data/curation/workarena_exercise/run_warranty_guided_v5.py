"""Separately labeled guided warranty probe after the reference comparison.

Requires a frozen profile and explicit --live. No ServiceNow credentials are
written into the profile. Existing sweep cases/profiles remain unchanged.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / '.local/workarena-exercise/vendor'))
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv
from intent_browser.actions import make_action_set
from intent_browser.runner import run_episode
from intent_browser.workarena_exercise import WarrantyExercise, ANSWER_INSTRUCTION as BASE_TERMINAL_INSTRUCTION

ANSWER_INSTRUCTION = (BASE_TERMINAL_INSTRUCTION +
    " At every step output a bare Python function call, such as noop() or click('123'). "
    "Do not wrap the function call in square brackets, XML, JSON, or Markdown. "
    "Element IDs belong inside quoted function arguments, not alone in the response.")
REFERENCE_GUIDANCE = (
    " For reference/autocomplete fields, fill(bid, value, enable_autocomplete_menu=True) triggers native suggestions. "
    "A displayed name alone may not be a selected reference. Inspect the fresh page and select a matching suggestion if needed. "
    "After applying a filter, verify the actual condition and results. If the condition is empty or wrong, repair the filter "
    "instead of repeatedly clicking its breadcrumb.")
ANSWER_INSTRUCTION += REFERENCE_GUIDANCE
from data.curation.sweep_backend import SweepBackend


def hashes():
    files = list((ROOT / 'intent_browser').glob('*.py'))
    files += [ROOT / 'data/curation/sweep_backend.py', Path(__file__).resolve()]
    # Pin every installed WorkArena file, plus the isolated dependency Python code.
    vendor = ROOT / '.local/workarena-exercise/vendor'
    files += [p for p in vendor.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc']
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(files))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', type=Path, required=True)
    parser.add_argument('--freeze', action='store_true')
    parser.add_argument('--live', action='store_true')
    parser.add_argument('--case', default='WA-W01-guided-v5')
    args = parser.parse_args()
    if args.freeze == args.live:
        parser.error('Choose exactly one of --freeze or --live')
    ledger = ROOT / 'data/curation/sweeps/budget.json'
    if args.freeze:
        old = json.loads((ROOT / 'data/curation/sweeps/external-baseline-v1/profile.json').read_text())['config']
        config = {k: old[k] for k in ('model','providers','max_tokens','input_byte_limit','pace_seconds',
                                     'prompt_price_cap','output_price_cap','cap_usd','carried_usd','budget_id')}
        config['max_steps'] = 20
        config['input_byte_limit'] = 80000
        profile = {'schema': 'workarena-warranty-reference-guidance-v5', 'observation_text_limit': 48000,
                   'prior_profile_sha256': hashlib.sha256((ROOT/'data/curation/workarena_exercise/warranty-full-v4/profile.json').read_bytes()).hexdigest(),
                   'baseline_profile_sha256': hashlib.sha256((ROOT/'data/curation/workarena_exercise/warranty-model-v1/profile.json').read_bytes()).hexdigest(),
                   'amendment': 'Add explicit reference/autocomplete and filter-result checking guidance. Same full view, tools, goal and outcome checks; fresh generated task, not a paired causal comparison.', 'config': config,
                   'created_at': datetime.now(timezone.utc).isoformat(), 'source_hashes': hashes(),
                   'terminal_response_instruction': ANSWER_INSTRUCTION, 'reference_guidance': REFERENCE_GUIDANCE, 'seed': 707,
                   'headless': True, 'video': False, 'slow_mo': 250, 'training_eligible': False,
                   'safe_success_ready': False, 'search': None,
                   'existing_reserved_usd': json.loads(ledger.read_text())['reserved_cost_usd'],
                   'native_scripted_evidence': '.local/workarena-exercise/warranty-native-v1/report.json',
                   'reference_scripted_evidence': 'data/curation/workarena_exercise/reference-comparison-review-v1.json',
                   'budget_stop': 'Per-request reservation must fit cumulative cap; maximum steps is not a guaranteed funded horizon.'}
        args.profile.parent.mkdir(parents=True, exist_ok=True)
        with args.profile.open('x') as f:json.dump(profile, f, indent=2)
        print('Frozen',len(profile['source_hashes']),'files; no API/browser/model calls.')
        return
    profile_bytes = args.profile.read_bytes()
    profile = json.loads(profile_bytes)
    def validate():
        if args.profile.read_bytes() != profile_bytes:
            raise ValueError("Frozen profile changed")
        for name, expected in profile['source_hashes'].items():
            if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != expected:
                raise ValueError('Frozen source changed: '+name)
        if profile['terminal_response_instruction'] != ANSWER_INSTRUCTION:
            raise ValueError('Terminal instruction changed')
    validate()
    if any(r['case_id']==args.case for r in json.loads(ledger.read_text())['requests']):
        raise ValueError('Case already has reservations; no rerun')
    result_path = args.profile.parent / (args.case+'.json')
    if result_path.exists():raise ValueError('Case already has a result; no rerun')
    load_dotenv(ROOT / '.env')
    task = WarrantyExercise()
    backend = SweepBackend(os.environ['OPENROUTER_API_KEY'], ledger, validate, profile['config'], args.case)
    try:
        directory, summary = run_episode(
            lambda video: task.make_env(video, action_mapping=make_action_set().to_python_code),
            backend, {'source':'workarena-learning-exercise','case_id':args.case,
                      'profile_sha256':hashlib.sha256(args.profile.read_bytes()).hexdigest(),
                      'training_eligible':False,'verifier':'workarena-warranty-development'},
            output=str(ROOT/'runs'), max_steps=profile['config']['max_steps'], seed=profile['seed'],
            record_video=profile['video'], episode_task=task, before_observation=backend.wait_until_ready,
            terminal_response_instruction=profile['terminal_response_instruction'],
            observation_text_limit=profile['observation_text_limit'])
        with result_path.open('x') as f:json.dump({'trace':str(directory.relative_to(ROOT)),'summary':summary},f,indent=2)
    finally:
        backend.client.close()


if __name__ == '__main__':main()
