#!/usr/bin/env python3
"""Apply or verify the pinned, source-only vLLM0.28 MTP offload backport.

No model imports, network access or compiler work. Unknown source bytes fail
closed. Application happens in a private /tmp directory, then replaces exactly
one package source file after its expected result hash and syntax are checked.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
from importlib.metadata import distribution

PATCH_ID = 'vllm028-mtp-cpu-offload-v1'
SOURCE_PATH = 'vllm/distributed/kv_transfer/kv_connector/v1/offloading/scheduler.py'
BASE_SHA256 = '616e7fd4cb0d09064cbc4d5735f607b37964c6be3b81e26de00d5913e0a9a3e3'
RESULT_SHA256 = '599a1613fb6088a28c14b7fb2119b7eabfe5ed5e4085b1c6fd5f4a4c8a23f3ec'
PATCH_SHA256 = '453b0238c7a3072c7c558778db91b98214ba46dca704e9dbf9932e5f2ea587b6'
PATCH_FILE = Path(__file__).resolve().parents[1] / 'patches/vllm028_mtp_cpu_offload.patch'
UPSTREAM = {
    '54288': 'dc02934a07672eb778a8d819f4e35d0f93ee427b',
    '52807': 'da8ec2826898d47bd2fb424bc607052a6dc515c1',
    '52771': '4a806d08ee94b35356dd749bf814ee91ee93f8d0',
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def apply_patch(source=None, *, verify_only=False, patch_file=None, install_in_place=False):
    """An explicit source path supports model-free scratch regression tests."""
    if source is None:
        if not verify_only and not install_in_place:
            raise RuntimeError('Installed-package modification requires --install-in-place')
        package = distribution('vllm')
        if package.version != '0.28.0':
            raise RuntimeError('Backport requires exactly vLLM0.28.0')
        source = package.locate_file(SOURCE_PATH)
    source = Path(source)
    if source.is_symlink():
        raise RuntimeError('Refuse a symlinked package source')
    patch_file = Path(patch_file) if patch_file is not None else PATCH_FILE
    patch = patch_file.read_bytes()
    if sha256(patch) != PATCH_SHA256:
        raise RuntimeError('Backport artifact differs from pinned patch bytes')
    original = source.read_bytes()
    current = sha256(original)
    receipt = dict(patch_id=PATCH_ID, source=str(source), source_sha256=current,
                   upstream_commits=UPSTREAM, patch_sha256=PATCH_SHA256)
    if current == RESULT_SHA256:
        return dict(receipt, status='verified' if verify_only else 'already_patched')
    if current != BASE_SHA256:
        raise RuntimeError('Unknown vLLM scheduler source; refuse patch: ' + current)
    if verify_only:
        raise RuntimeError('Required MTP offload backport is not installed')
    # /tmp avoids inherited Git discovery; result hashes catch skipped hunks.
    with tempfile.TemporaryDirectory(prefix='vllm028-offload-', dir='/tmp') as folder:
        root = Path(folder)
        target = root / SOURCE_PATH
        target.parent.mkdir(parents=True)
        target.write_bytes(original)
        artifact = root / 'backport.patch'
        artifact.write_bytes(patch)
        env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
        env['GIT_CEILING_DIRECTORIES'] = str(root.parent)
        proc = subprocess.run(['git', 'apply', '--include=' + SOURCE_PATH, str(artifact)],
                              cwd=root, env=env, text=True, capture_output=True, timeout=20)
        if proc.returncode:
            raise RuntimeError('Backport application failed: ' + proc.stderr[-3000:])
        updated = target.read_bytes()
        if sha256(updated) != RESULT_SHA256:
            raise RuntimeError('Backport produced wrong source bytes; package unchanged')
        ast.parse(updated)
    # Never overwrite a source that changed during preparation.
    if source.read_bytes() != original:
        raise RuntimeError('Package source changed during patch preparation')
    fd, name = tempfile.mkstemp(prefix='.mtp-offload-', dir=source.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(updated)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, stat.S_IMODE(source.stat().st_mode))
        os.replace(name, source)
    finally:
        Path(name).unlink(missing_ok=True)
    return dict(receipt, status='patched', source_sha256=RESULT_SHA256)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--install-in-place', action='store_true',
                        help='Explicitly modify installed vLLM before workers start')
    parser.add_argument('--source', type=Path, help='Explicit scratch source file')
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    if args.source is None and not args.verify_only and not args.install_in_place:
        parser.error('Use --verify-only, --source or explicit --install-in-place')
    receipt = apply_patch(args.source, verify_only=args.verify_only,install_in_place=args.install_in_place)
    text = json.dumps(receipt, indent=2) + '\n'
    if args.receipt:
        args.receipt.write_text(text)
    print(text, end='')


if __name__ == '__main__':
    main()
