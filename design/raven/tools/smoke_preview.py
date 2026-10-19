"""Finite local HTTP smoke check; no browser or model is launched.

From the repository root, use the repository resource wrapper:
python3 scripts/run_bounded_job.py --memory-mib 1024 -- python3 design/raven/tools/smoke_preview.py
"""
from pathlib import Path
import argparse
import hashlib
import json
import socket
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

PACKAGE = Path(__file__).resolve().parent.parent
WEB = PACKAGE / 'outputs' / 'raven'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=18766)
    args = parser.parse_args()
    # Fail on an occupied test port; never disturb an existing server.
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', args.port))
    process = subprocess.Popen([sys.executable, str(WEB / 'server.py'), '--port', str(args.port)],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    origin = f'http://127.0.0.1:{args.port}'
    try:
        for _ in range(50):
            if process.poll() is not None:
                raise RuntimeError('Export preview server exited during startup.')
            try:
                with urlopen(origin + '/', timeout=.5) as response:
                    assert response.status == 200
                    break
            except URLError:
                time.sleep(.1)
        else:
            raise TimeoutError('Export preview server startup timed out.')
        checked = 0
        for path in sorted(WEB.rglob('*')):
            if not path.is_file() or path.suffix not in {'.html', '.js', '.css'}:
                continue
            with urlopen(origin + '/' + path.relative_to(WEB).as_posix(), timeout=5) as response:
                assert response.status == 200
                assert hashlib.sha256(response.read()).digest() == hashlib.sha256(path.read_bytes()).digest()
            checked += 1
        bank = json.loads((WEB / 'live-raven-v34.json').read_text(encoding='utf-8'))
        for name in ['live-raven-v34.json', bank['binary']['uri'], 'live-actions-meta-v34.json',
                     'live-idle-meta-v34.json', 'live-flight-meta-v34.json',
                     'live-attention-meta-v34.json', 'patrol-path.json']:
            with urlopen(origin + '/' + name, timeout=10) as response:
                assert response.status == 200
                assert hashlib.sha256(response.read()).digest() == hashlib.sha256((WEB / name).read_bytes()).digest()
            checked += 1
        print(json.dumps({'status': 'passed', 'httpAssets': checked,
                          'metadata': {'tags': ['scripted']},
                          'scope': 'local startup and byte-identical HTTP delivery; no browser/model episode'}))
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


if __name__ == '__main__':
    main()
