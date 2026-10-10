"""Publish a separate local development runtime; never alter the producer pin."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from .adapter import PIN, ROOT
from .runtime import Runtime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=Path('.local/website-world/first-journey-v1'))
    parser.add_argument('--serve', action='store_true')
    parser.add_argument('--pin', type=Path, default=PIN)
    parser.add_argument('--presentation', type=Path, help='World-bound explicit presentation request JSON')
    parser.add_argument('--coupon-pin', type=Path, help='Frozen opt-in native quantity-one coupon stage')
    args = parser.parse_args()
    output = args.output.resolve()
    if not args.serve:
        if (output / 'manifest.json').exists():
            raise SystemExit('Publication already exists; use a separate output for a new runtime')
        output.mkdir(parents=True, exist_ok=True)
        log = (output / 'server.log').open('a')
        command = [sys.executable, '-m', 'environments.website_world.preview', '--serve', '--output', str(output), '--pin', str(args.pin.resolve())]
        if args.presentation:
            command += ['--presentation', str(args.presentation.resolve())]
        if args.coupon_pin:
            command += ['--coupon-pin', str(args.coupon_pin.resolve())]
        process = subprocess.Popen(command,
                                   stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        for _ in range(200):
            if (output / 'manifest.json').exists():
                print(json.dumps(json.loads((output / 'manifest.json').read_text()), indent=2))
                return
            if process.poll() is not None:
                raise SystemExit((output / 'server.log').read_text())
            time.sleep(.1)
        raise SystemExit('Publisher did not become ready; inspect server.log')
    done = False
    def stop(*args):
        nonlocal done
        done = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    presentation = json.loads(args.presentation.read_text()) if args.presentation else None
    with Runtime(args.pin, presentation=presentation, coupon_pin=args.coupon_pin) as runtime:
        # Freeze the renderer/adapter and opted-in producer source alongside the
        # private publication, including the HTML template. Nothing is mounted.
        sources = dict(runtime.sources)
        if runtime.coupons:
            sources.update(runtime.coupons.manifest['source_sha256'])
            sources.update(runtime.coupons.manifest['native_quote_source_sha256'])
        for name, expected in sources.items():
            raw = (ROOT / name).read_bytes()
            if sha256(raw).hexdigest() != expected:
                raise ValueError('Source changed during publication: ' + name)
            target = output / 'source-snapshot' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        policy_input = {**json.loads((args.pin / 'policy-input.json').read_text()),
                        'start_url': runtime.index_origin, 'binding_status': 'new_runtime_callable'}
        if args.coupon_pin:
            policy_input.update(binding_status='coupon_runtime_manual_reference_only',
                reference_status='Original no-coupon reference does not apply; use separate coupon-stage enumeration.')
        documents = {'bindings.json': runtime.bindings, 'compositions.private.json': runtime.compositions,
                     'field-bindings.private.json': runtime.adapter.fields,
                     'process.json': {'pid': os.getpid()},
                     'presentation-request.private.json': runtime.presentation,
                     'policy-input.json': policy_input,
                     'manifest.json': runtime.manifest}
        for name, document in documents.items():
            temporary = output / (name + '.publishing')
            temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n')
            temporary.replace(output / name)
        while not done:
            time.sleep(.5)


if __name__ == '__main__':
    main()
