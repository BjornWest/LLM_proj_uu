"""Live episode cap from vLLM KV headroom. Writes the integer cap to the shared --concurrency-file.

  kv_controller.py --cap-file vast/concurrency.txt [--metrics URL] [--initial 8] [--min 2] [--ceiling 32]

Every 30 s logs to vast/kv-controller.log: active episodes (all runners, from CAPFILE.active.<pid>),
running/waiting requests, KV %, preemptions, token rates, prefix-cache hit %, cap.
Raise by 1-2 when the runners are saturated (active >= cap), KV < 80 % and no waiting or new
preemptions for 2 min; lower by 1-2 when KV > 95 % or preemptions grow. Running episodes are never
stopped: a lower cap only delays new starts. Missing metrics leave the cap unchanged.
"""
import argparse, json, os, re, time, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent


def metrics(url):
    text = urllib.request.urlopen(url, timeout=15).read().decode()
    values = {}
    for line in text.splitlines():
        m = re.match(r'^(vllm:[a-z_]+?)(?:\{[^}]*\})? ([0-9.eE+-]+|NaN)$', line)
        if m and m.group(2) != 'NaN':
            values[m.group(1)] = values.get(m.group(1), 0.0) + float(m.group(2))
    return values


def active(cap_file):
    total = 0
    for marker in cap_file.parent.glob(cap_file.name + '.active.*'):
        if marker.name.endswith('.tmp'):
            continue
        try:
            os.kill(int(marker.name.rsplit('.', 1)[-1]), 0)
            total += int(marker.read_text() or 0)
        except (OSError, ValueError):
            pass
    return total


def write_cap(path, cap):
    tmp = path.with_name(path.name + '.tmp')
    tmp.write_text(f'{cap}\n')
    tmp.replace(path)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--cap-file', type=Path, default=HERE / 'concurrency.txt')
    p.add_argument('--metrics', default='http://127.0.0.1:18000/metrics')
    p.add_argument('--initial', type=int, default=8)
    p.add_argument('--min', type=int, default=2)
    p.add_argument('--ceiling', type=int, default=32)
    p.add_argument('--period', type=int, default=30)
    p.add_argument('--target', type=float, default=None, help='hold a smoothed KV fraction near this (e.g. 0.5) instead of the 80/95 rule')
    p.add_argument('--band', type=float, default=0.1)
    p.add_argument('--log', type=Path, default=HERE / 'kv-controller.log')
    a = p.parse_args()
    try:
        cap = int(a.cap_file.read_text().split()[0])
    except (OSError, ValueError, IndexError):
        cap = a.initial
    cap = max(a.min, min(a.ceiling, cap)); write_cap(a.cap_file, cap)
    previous, calm, ema, hot = None, 0, None, 0
    while True:
        row = {'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'active_episodes': active(a.cap_file)}
        try:
            m = metrics(a.metrics); now = time.time()
        except Exception as error:
            row.update(cap=cap, metrics_error=repr(error)[:200], action='hold')
            m = None
        if m is not None:
            kv = m.get('vllm:kv_cache_usage_perc', m.get('vllm:gpu_cache_usage_perc'))
            pre = m.get('vllm:num_preemptions_total', 0.0)
            row.update(running=m.get('vllm:num_requests_running'), waiting=m.get('vllm:num_requests_waiting'),
                       kv_percent=None if kv is None else round(100 * kv, 1), preemptions_total=pre)
            if previous:
                dt = now - previous[0]; old = previous[1]
                delta = lambda k: m.get(k, 0.0) - old.get(k, 0.0)
                row.update(preemptions_new=delta('vllm:num_preemptions_total'),
                           gen_tok_s=round(delta('vllm:generation_tokens_total') / dt, 1),
                           prompt_tok_s=round(delta('vllm:prompt_tokens_total') / dt, 1))
                q = delta('vllm:prefix_cache_queries_total')
                if q > 0:
                    row['prefix_hit_percent'] = round(100 * delta('vllm:prefix_cache_hits_total') / q, 1)
            new_pre = row.get('preemptions_new', 0) > 0
            action = 'hold'
            if kv is not None and a.target is not None:
                ema = kv if ema is None else 0.3 * kv + 0.7 * ema
                row['kv_ema_percent'] = round(100 * ema, 1)
                hot = hot + 1 if (row.get('waiting') or 0) > 2 else 0
                if ema > a.target + a.band or new_pre or hot >= 3:
                    calm = 0
                    if cap > a.min:
                        cap -= 1; action = 'lower1'; ema = a.target
                elif ema < a.target - a.band and not (row.get('waiting') or 0) and previous:
                    calm += 1
                    if calm * a.period >= 120 and row['active_episodes'] >= cap and cap < a.ceiling:
                        cap += 1; action = 'raise1'; calm = 0
                else:
                    calm = 0
            elif kv is not None:
                if kv > 0.95 or new_pre:
                    step = 2 if (kv > 0.98 or row.get('preemptions_new', 0) > 2) else 1
                    if cap > a.min:
                        cap = max(a.min, cap - step); action = f'lower{step}'
                    calm = 0
                elif kv < 0.80 and not (row.get('waiting') or 0) and previous:
                    calm += 1
                    if calm * a.period >= 120 and row['active_episodes'] >= cap and cap < a.ceiling:
                        step = 2 if kv < 0.60 else 1
                        cap = min(a.ceiling, cap + step); action = f'raise{step}'; calm = 0
                else:
                    calm = 0
            write_cap(a.cap_file, cap)
            row.update(cap=cap, action=action, calm_samples=calm)
            previous = (now, m)
        with a.log.open('a') as f:
            f.write(json.dumps(row) + '\n')
        time.sleep(a.period)


if __name__ == '__main__':
    main()
