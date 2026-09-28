#!/usr/bin/env python3
"""P11 browser→native GRPO, CPU-gated, one 2×L40S attempt capped at 10min/GPU."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import uuid
import modal
from modal_grpo import ROOT, dependency_image, SOURCES as BASE_SOURCES, cache, results, PYTHON
from modal_acceptance import prepare as prepare_base, gpu_probe as probe_base, EXTRA

SNAPSHOT = ROOT / 'outputs/browser-harness/p11-bcd60369b32b'
ADDITIONS = [ROOT / 'scripts' / n for n in ('modal_browser_grpo.py', 'project_browser_worker.py', 'validate_project_grpo.py')]
SOURCES = sorted(set(BASE_SOURCES + EXTRA + ADDITIONS))
image = (dependency_image
    .add_local_file(ROOT / 'envs/browser/pyproject.toml', '/opt/browser/pyproject.toml', copy=True)
    .add_local_file(ROOT / 'envs/browser/uv.lock', '/opt/browser/uv.lock', copy=True)
    .run_commands('cd /opt/browser && uv sync --locked --python 3.12.12 --default-index https://pypi.org/simple',
                  '/opt/browser/.venv/bin/playwright install --with-deps chromium',
                  'uv pip check --python /opt/browser/.venv/bin/python'))
for source in SOURCES:
    image = image.add_local_file(source, '/opt/training/' + str(source.relative_to(ROOT)))
image = (image.add_local_dir(SNAPSHOT / 'frozen', '/opt/browser-snapshot/frozen')
         .add_local_file(SNAPSHOT / 'frozen-sources.json', '/opt/browser-snapshot/frozen-sources.json'))
app = modal.App('browser-training-p11-grpo', image=image, include_source=False)


@app.function(cpu=8, memory=16384, timeout=360, retries=0, max_containers=1,
              scaledown_window=2, volumes={'/model-cache': cache, '/results': results})
def prepare():
    prepared = prepare_base.local()
    # This runs native spawned TRL, the exact remote browser image, and fake HTTP token responses.
    from browser_training.processes import run_logged
    output = Path('/tmp') / ('p11-cpu-' + uuid.uuid4().hex[:8])
    code = run_logged([PYTHON, 'scripts/validate_project_grpo.py', '--frozen', '/opt/browser-snapshot/frozen',
                       '--browser-python', '/opt/browser/.venv/bin/python', '--tokenizer', prepared['trainer'],
                       '--slow-shutdown-seconds', '22',
                       '--output', str(output)], Path('/tmp/p11-prepare.log'), cwd='/opt/training',
                      env=dict(os.environ, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', USE_HUB_KERNELS='NO'), timeout=180)
    if code:
        raise RuntimeError('Remote browser/TRL CPU gate failed; no GPU allocated')
    prepared['browser_cpu'] = json.loads((output / 'report.json').read_text())
    return prepared


@app.function(gpu='L40S:2', cpu=12, memory=98304, timeout=540, startup_timeout=60,
              retries=0, max_containers=1, scaledown_window=2,
              volumes={'/model-cache': cache, '/results': results})
def gpu_probe(run_id, prepared, deadline):
    return probe_base.local(run_id, prepared, deadline, 2, 540, browser_frozen='/opt/browser-snapshot/frozen')


def main():
    import argparse
    from dotenv import dotenv_values
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--prepare-only', action='store_true')
    a = p.parse_args()
    plan = dict(gpu='L40S:2', steps=2, maximum_gpu_minutes=20, function_timeout_s=540,
                startup_timeout_s=60, queue_allowance_s=600, retries=0, task='P11-clean',
                context_cap_tokens=8192, tokenizer='Qwen3.8-27B', max_output_tokens_per_turn=512,
                max_browser_turns=4, group_size=4, max_inflight=4,
                scope='Real model actions and native GRPO on a harness-dev task; not a learning benchmark',
                browser_source_sha256=json.loads((SNAPSHOT / 'frozen-sources.json').read_text())['sha256'])
    if a.dry_run:
        print(json.dumps(plan, indent=2)); return
    for key, value in dotenv_values(ROOT.parent / '.env').items():
        if key in ('MODAL_TOKEN_ID', 'MODAL_TOKEN_SECRET') and value:
            os.environ.setdefault(key, value)
    run_id = time.strftime('l40s-browser-%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8]
    local = ROOT / 'outputs/modal' / run_id
    local.mkdir(parents=True)
    sources = SOURCES + [ROOT / 'envs' / env / name for env in ('rl', 'browser') for name in ('pyproject.toml', 'uv.lock')]
    plan['source_sha256'] = {str(s.relative_to(ROOT)): hashlib.sha256(s.read_bytes()).hexdigest() for s in sources}
    for source in sources:
        target = local / 'sources' / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())
    plan['git_commit'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    (local / 'plan.json').write_text(json.dumps(plan, indent=2))
    with modal.enable_output(), app.run():
        (local / 'app.json').write_text(json.dumps(dict(app_id=app.app_id, url=app.get_dashboard_url())))
        prepared = prepare.remote()
        (local / 'cache.json').write_text(json.dumps(prepared, indent=2))
        if a.prepare_only:
            return
        deadline = time.time() + 1200
        call = gpu_probe.spawn(run_id, prepared, deadline)
        (local / 'call.json').write_text(json.dumps(dict(call_id=call.object_id, deadline=deadline)))
        try:
            report = call.get(timeout=max(1, deadline-time.time()))
        finally:
            call.cancel(terminate_containers=True)
        (local / 'report.json').write_text(json.dumps(report, indent=2))
        print(json.dumps(report, indent=2))
        if report['status'] != 'PASS':
            raise SystemExit(1)


if __name__ == '__main__':
    main()
