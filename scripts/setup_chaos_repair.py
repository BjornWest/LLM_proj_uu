"""Build an isolated, hash-checked Chaos variant. Never changes the installed package."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ROOT=Path(__file__).resolve().parents[1]
BUNDLE='0271f4aba16401862247244be943194d96c2e5902529a8e3a9a7547b586352b1'
WEB='3068bbeb566673a91a35f2849ab9f8b98463201221f8d767ef2893916f1a16f7'

def digest(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,required=True)
    p.add_argument('--output',type=Path,default=ROOT/'.local/chaos-fifo-v2')
    p.add_argument('--rng',choices=['original','xorshift32-v1'],default='original')
    args=p.parse_args();source=args.source.resolve();output=args.output.resolve()
    assert source!=output and source not in output.parents and output not in source.parents
    cli=source/'dist/cli.mjs';web=source/'dist/web/assets/index-CiX7pK2V.js'
    if digest(cli)!=BUNDLE or digest(web)!=WEB:raise ValueError('Unsupported original Chaos build')
    if output.exists():raise ValueError('Output already exists; choose a new versioned directory')
    output.mkdir(parents=True)
    metadata=json.loads((source/'package.json').read_text())
    metadata['version'] += '-intent.fifo2' + ('.xor32' if args.rng!='original' else '')
    metadata['intent_repair']={'stage_queue':'stage-fifo-v2','rng':args.rng,'parent_bundle_sha256':BUNDLE}
    (output/'package.json').write_text(json.dumps(metadata,indent=2))
    dependencies=source.parent
    if not (dependencies/'fastify/package.json').exists():raise ValueError('Cached dependencies unavailable')
    (output/'node_modules').symlink_to(dependencies,target_is_directory=True)
    shutil.copytree(source/'dist',output/'dist')
    original=web.read_text();begin=original.index('function pg({challengeId:e})')
    end=original.index('if(!n||!a)return ',begin)
    if original.count('function pg({challengeId:e})')!=1:raise ValueError('Unexpected component layout')
    prefix=ROOT/'environments/chaos/stage-component-prefix.js.txt'
    repaired=original[:begin]+prefix.read_text()+original[end:]
    repaired='import {createStageQueue as __intentCreateStageQueue} from "./intent-stage-queue.mjs";\n'+repaired
    (output/web.relative_to(source)).write_text(repaired)
    shutil.copyfile(ROOT/'environments/chaos/stage-queue.mjs',output/'dist/web/assets/intent-stage-queue.mjs')
    if args.rng!='original':
        old='this.state = this.state * 1103515245 + 12345 & 2147483647;'
        code=cli.read_text()
        if code.count(old)!=1:raise ValueError('Unexpected RNG layout')
        new='let x = this.state; x ^= x << 13; x ^= x >>> 17; x ^= x << 5; this.state = x >>> 0;'
        (output/'dist/cli.mjs').write_text(code.replace(old,new))
    files=lambda directory:{str(p.relative_to(directory)):digest(p) for p in sorted(directory.rglob('*')) if p.is_file()}
    report={'schema_version':1,'variant':'stage-fifo-v2','rng':args.rng,'original_package':str(source),'cached_node_modules':str(dependencies),
      'dependency_lock_sha256':digest(dependencies/'.package-lock.json'),
      'original_files_sha256':files(source/'dist'),'derived_files_sha256':files(output/'dist'),
      'patch_sources_sha256':{str(p.relative_to(ROOT)):digest(p) for p in [Path(__file__),prefix,ROOT/'environments/chaos/stage-queue.mjs']},
      'limitations':['Derived local environment, not unmodified upstream.','No model performance or training readiness established.']}
    (output/'dist/intent-repair.json').write_text(json.dumps(report,indent=2))
    print(output)

if __name__=='__main__':main()
