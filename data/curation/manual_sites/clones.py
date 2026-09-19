"""Pinned disposable manual-review clones; no leases, server or model calls.

Reset is destructive ONLY for the two allowlisted, unmounted, label-checked
containers. The caller must revoke its browser lease before reset, and keep the
slot quarantined on failure. This command does not implement that broker policy.
"""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import subprocess
import time
from urllib.error import URLError
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[3]
OWNER = 'daylight-manual-sites-v1'
CANONICAL = 'http://172.23.129.52:8896'
SITES = {
    'shopping': {
        'name': 'daylight-manual-shopping-v1', 'port': 17870, 'control_port': 17871,
        'memory': '4g',
        'image': 'am1n3e/webarena-verified-shopping@sha256:3e8cb9b945ea9b1c94ab26dba53e8d12dd0406abbf4bf686fd3bb2b6a5908feb',
        'image_id': 'sha256:a5b6fb47ee9f378ceca18e32261a92a8964f0ccfb9f1d3741ce3a0e2d990839d',
    },
    'forum': {
        'name': 'daylight-manual-forum-v1', 'port': 19170, 'control_port': 19171,
        'memory': '2g',
        'image': 'am1n3e/webarena-verified-reddit@sha256:0594908059a03e5f610005689440a95c05e776e734006197c7b1eba12734cb46',
        'image_id': 'sha256:59a4863de0f2107ef275e4ee33d8ca37d76ccceeed8ec558cdda1a0c64939914',
    },
}


def command(*args, timeout=900):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT, timeout=timeout).strip()


def canonical_url(value):
    p = urlsplit(value)
    if p.scheme != 'http' or not p.hostname or p.username or p.password or p.path not in ('', '/') or p.query or p.fragment:
        raise ValueError('Canonical URL must be a credential-free HTTP origin')
    return value.rstrip('/')


def validate_container(d, site, canonical):
    spec = SITES[site]
    expected_labels = {'intent.owner': OWNER, 'intent.site': site, 'intent.reset-scope': 'isolated-disposable'}
    if d['Name'] != '/' + spec['name'] or d['Image'] != spec['image_id'] or d['Config']['Image'] != spec['image']:
        raise ValueError('Wrong container name/image; refusing mutation')
    if any(d['Config']['Labels'].get(k) != v for k, v in expected_labels.items()) or d['Mounts']:
        raise ValueError('Wrong owner/site/reset scope or mounted data; refusing mutation')
    expected_ports = {f'{c}/tcp': [{'HostIp': '127.0.0.1', 'HostPort': str(h)}]
                      for c, h in [(80, spec['port']), (8877, spec['control_port'])]}
    if d['HostConfig']['PortBindings'] != expected_ports:
        raise ValueError('Unexpected published ports; refusing mutation')
    if 'WA_ENV_CTRL_EXTERNAL_SITE_URL=' + canonical not in d['Config']['Env']:
        raise ValueError('Canonical origin mismatch; refusing mutation')
    return {k: d[k] for k in ('Id', 'Image', 'Created', 'Mounts')}


def inspect(site, canonical=CANONICAL):
    return validate_container(json.loads(command('docker', 'inspect', SITES[site]['name']))[0], site, canonical)


def create_argv(site, canonical):
    s = SITES[site]
    return ['docker', 'run', '-d', '--pull=never', '--name', s['name'],
            '--label', 'intent.owner=' + OWNER, '--label', 'intent.site=' + site,
            '--label', 'intent.reset-scope=isolated-disposable',
            '--memory', s['memory'], '--cpus', '2', '--shm-size', '256m',
            '-p', f"127.0.0.1:{s['port']}:80", '-p', f"127.0.0.1:{s['control_port']}:8877",
            '-e', 'WA_ENV_CTRL_EXTERNAL_SITE_URL=' + canonical, s['image']]


def upstream(site):
    return f"http://127.0.0.1:{SITES[site]['port']}"


def ready(site, canonical, output):
    start = time.monotonic()
    log = command('docker', 'exec', SITES[site]['name'], 'env-ctrl', 'init', '--base-url', canonical)
    (output / 'init.log').write_text(log + '\n')
    for _ in range(90):
        try:
            # No automatic cross-origin redirects during upstream health check.
            import http.client
            c = http.client.HTTPConnection('127.0.0.1', SITES[site]['port'], timeout=10)
            c.request('GET', '/', headers={'Host': urlsplit(canonical).netloc})
            r = c.getresponse(); status = r.status; location = r.getheader('Location'); r.read(); c.close()
            if status == 200 or (status in (301, 302, 303, 307, 308) and location and location.startswith(canonical + '/')):
                return {'http_status': status, 'location': location, 'initialization_seconds': time.monotonic() - start}
        except (OSError, URLError):
            pass
        time.sleep(1)
    raise RuntimeError('Clone not ready; keep slot quarantined')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['create', 'reset', 'inspect'])
    p.add_argument('--site', required=True, choices=SITES)
    p.add_argument('--canonical', type=canonical_url, default=CANONICAL)
    p.add_argument('--expected-id', help='Required exact current container ID for reset')
    p.add_argument('--output', type=Path, required=True, help='New evidence directory; existing paths rejected')
    a = p.parse_args()
    if a.action == 'reset' and not a.expected_id:
        p.error('reset requires --expected-id from the exclusive lease owner')
    a.output.mkdir(parents=True, exist_ok=False)
    locks = ROOT / '.local/manual-sites/locks'; locks.mkdir(parents=True, exist_ok=True)
    with (locks / (a.site + '.lock')).open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        report = {'schema': 'manual-site-clone-v1', 'action': a.action, 'site': a.site,
                  'canonical_url': a.canonical, 'upstream_origin': upstream(a.site), 'model_calls': 0,
                  'source_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
        try:
            if a.action in ('inspect', 'reset'):
                report['before'] = inspect(a.site, a.canonical)
            if a.action == 'reset':
                if report['before']['Id'] != a.expected_id:
                    raise ValueError('Container identity changed; refusing removal')
                # Exact ID rather than name: another replacement can never be removed.
                report['remove_output'] = command('docker', 'rm', '-f', a.expected_id)
            if a.action in ('create', 'reset'):
                s = SITES[a.site]
                if command('docker', 'image', 'inspect', s['image'], '--format', '{{.Id}}') != s['image_id']:
                    raise ValueError('Cached image ID mismatch')
                report['create_argv'] = create_argv(a.site, a.canonical)
                report['created_id'] = command(*report['create_argv'])
                report['ready'] = ready(a.site, a.canonical, a.output)
            report['after'] = inspect(a.site, a.canonical)
            report['passed'] = True
        except Exception as e:
            report.update(passed=False, error=f'{type(e).__name__}: {e}')
            raise
        finally:
            (a.output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
            print(json.dumps(report))


if __name__ == '__main__':
    main()
