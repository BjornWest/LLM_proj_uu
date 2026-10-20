"""Search, then immediately create ONE Vast instance (no retry loop). Writes vast/rental.json.

  allocate.py search            rank current offers (no spend)
  allocate.py create OFFER_ID   create from a fresh lookup of that offer; on-host self-destroy armed
"""
import json, math, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from vastapi import client, credit, instances, offers

HERE = Path(__file__).resolve().parent
IMAGE = 'docker.io/vastai/base-image@sha256:c1d2b5326fae806b04d2c2d97a2b3948d0ccb0026dd3085e9a2ad55e304193f8'
DISK = 120
LIFETIME = int(5.5 * 3600)
GPUS = ['RTX PRO 6000 S', 'RTX PRO 6000 WS', 'RTX PRO 6000', 'H100 SXM']


def candidates(c):
    rows = []
    for g in GPUS:
        rows += offers.search_offers(c, {'gpu_name': {'eq': g}, 'num_gpus': {'eq': 1}}, storage=DISK, limit=60,
                                     order=[['dph_total', 'asc']])
    good = {}
    for o in rows:
        rel = o.get('reliability2') or o.get('reliability') or 0
        ok = (o['dph_total'] <= 1.6 and rel >= 0.98 and (o.get('inet_down') or 0) >= 500
              and (o.get('cuda_max_good') or 0) >= 13.0 and o.get('verification') == 'verified'
              and o['cpu_ram'] >= 100 * 1024 and (o.get('inet_down_cost') or 0) <= 0.02
              and (o.get('disk_space') or 0) >= DISK and (o.get('gpu_ram') or 0) >= 79000)
        if ok:
            good[o['id']] = o
    return sorted(good.values(), key=lambda o: o['dph_total'])


def summary(o):
    return {'offer_id': o['id'], 'machine_id': o['machine_id'], 'gpu': o['gpu_name'], 'gpu_ram_MB': o.get('gpu_ram'),
            'dph_total_incl_disk': round(o['dph_total'], 4), 'reliability': o.get('reliability2') or o.get('reliability'),
            'inet_down_Mbps': o.get('inet_down'), 'inet_up_Mbps': o.get('inet_up'),
            'inet_down_cost_per_GB': o.get('inet_down_cost'), 'inet_up_cost_per_GB': o.get('inet_up_cost'),
            'cpu_ram_GB': round(o['cpu_ram'] / 1024), 'cores': o.get('cpu_cores_effective'),
            'driver': o.get('driver_version'), 'cuda_max_good': o.get('cuda_max_good'),
            'geolocation': o.get('geolocation'), 'verification': o.get('verification'), 'disk_GB': DISK,
            'type': 'on-demand'}


def main():
    c = client()
    if sys.argv[1] == 'search':
        for o in candidates(c)[:10]:
            print(json.dumps(summary(o)))
        return
    offer_id = int(sys.argv[2])
    assert not (HERE / 'rental.json').exists(), 'rental.json exists: one allocation only'
    assert not instances.show_instances(c), 'account already has an instance'
    found = [o for o in candidates(c) if o['id'] == offer_id]
    if not found:
        raise SystemExit('offer gone or no longer qualifies; re-rank')
    o = found[0]
    start = math.floor(time.time())
    onstart = (HERE / 'host-kit/self_destroy_onstart.sh').read_text().replace('__DEADLINE_UTC__', str(start + LIFETIME))
    label = f'qwen-demo-sprint-{start}'
    body = instances.build_create_instance_payload(image=IMAGE, disk=DISK, label=label, ssh=True, direct=True,
                                                   cancel_unavail=True, onstart_cmd=onstart)
    intent = {'offer': summary(o), 'label': label, 'image': IMAGE, 'allocation_utc': start,
              'onhost_self_destroy_utc': start + LIFETIME, 'credit_before': credit(c)}
    (HERE / 'allocation-intent.json').write_text(json.dumps(intent, indent=1))
    try:
        response = instances.create_instance_from_payload(c, o['id'], body)
        iid = response['new_contract'] if response.get('success') is True else None
    except Exception as exc:
        text = getattr(getattr(exc, 'response', None), 'text', '') or repr(exc)
        (HERE / f'allocation-error-{offer_id}.json').write_text(json.dumps({'error': text[:2000]}))
        rows = [r for r in instances.show_instances(c) if r.get('label') == label]
        if len(rows) != 1:
            raise SystemExit('allocation failed: ' + text[:500])
        iid = rows[0]['id']
    assert type(iid) is int and iid > 0, 'no contract id'
    rental = {**intent, 'instance_id': iid}  # raw response never saved (may carry an instance key)
    (HERE / 'rental.json').write_text(json.dumps(rental, indent=1))
    print(json.dumps(rental, indent=1))


if __name__ == '__main__':
    main()
