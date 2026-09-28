"""Stage a private current-harness image without altering older packages."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from package_expanded_worker import package
from intent_browser.standard_profile import tokenizer_path


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--registry',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    package(args.registry,args.output)
    runtime=args.output/'runtime'
    for relative in ('environments/aggregator_trial','data/curation/aggregator_trial'):
        destination=runtime/relative
        shutil.copytree(ROOT/relative,destination,dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copy2(ROOT/'config/prislyktan_tasks.json',runtime/'config/prislyktan_tasks.json')
    tokenizer=args.output/'tokenizer.json';shutil.copy2(tokenizer_path(),tokenizer)
    shutil.copy2(Path(tokenizer_path()).with_name('chat_template.jinja'),args.output/'chat_template.jinja')
    manifest={'schema':'standard-worker-package-v1','scope':'Private executable closure; acceptance certificates supplied separately.',
              'files':{str(p.relative_to(args.output)):hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in args.output.rglob('*') if p.is_file() and p.name!='standard-manifest.json'}}
    (args.output/'standard-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps({'files':len(manifest['files']),'output':str(args.output)}))

if __name__=='__main__':main()
