"""Copy a fixture package with the current runtime for separate acceptance.

No downloads or changes to the base. Existing certificates remain historical;
this manifest records bytes, not certification of the replacement policy.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil

from intent_browser.environment_package import inventory, verify
from intent_browser.standard_profile import tokenizer_path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--fixtures', type=Path, required=True)
    args = parser.parse_args()
    if os.path.lexists(args.output):
        raise FileExistsError(args.output)
    original = verify(args.base)
    shutil.copytree(args.base, args.output)
    runtime = args.output / 'runtime'
    from intent_browser.hosted_tasks import check_package
    check_package(args.fixtures)
    shutil.rmtree(args.output/'fixtures')
    shutil.copytree(args.fixtures,args.output/'fixtures')
    shutil.rmtree(runtime / 'intent_browser')
    shutil.copytree(ROOT / 'intent_browser', runtime / 'intent_browser',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for relative in ('environments/aggregator_trial','data/curation/aggregator_trial'):
        destination=runtime/relative
        if destination.exists():shutil.rmtree(destination)
        shutil.copytree(ROOT/relative,destination,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    for name in ('team_tasks.json','chaos_verifier.json','team_sites.json','prislyktan_tasks.json'):
        shutil.copy2(ROOT/'config'/name,runtime/'config'/name)
    tokenizer = runtime / 'tokenizers/qwen/tokenizer.json'
    tokenizer.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(tokenizer_path(), tokenizer)
    shutil.copy2(Path(tokenizer_path()).with_name('chat_template.jinja'),tokenizer.with_name('chat_template.jinja'))
    manifest = copy.deepcopy(original)
    manifest['derivation'] = {
        'base_manifest_sha256': hashlib.sha256((args.base / 'manifest.json').read_bytes()).hexdigest(),
        'scope': 'Current runtime replacement; unchanged fixture assets; separate acceptance required.',
        'runtime_validation': 'pending',
        'old_certificates': 'Historical; no source hash or readiness overrides.'}
    manifest['datasets']=[d for d in manifest['datasets'] if d['id']!='prislyktan']
    manifest['datasets'].append({'id':'prislyktan','tasks':[],'scope':'Original synthetic four-origin manual site; task acceptance separate'})
    manifest['requires'].update(tokenizers='0.23.2', greenlet='>=3,<4')
    (args.output / 'manifest.json').unlink()
    manifest['files'] = inventory(args.output)
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    verify(args.output)
    print(json.dumps({'package': str(args.output), 'files': len(manifest['files']), 'acceptance': 'pending'}))


if __name__ == '__main__':
    main()
