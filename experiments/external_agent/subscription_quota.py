"""Read-only subscription dispatch guard; no resumes, interrupts or paid fallback.

Bjorn's task-support job permits subscription use down to1% remaining. Check both
the weekly bucket and any shorter subscription window, never a reserve-model pool.
An in-flight request or concurrent thread can consume usage after the read; this is
an admission guard, not a provider-side reservation or exact credit-use guarantee.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path


class SubscriptionQuotaUnavailable(RuntimeError):
    pass


class SubscriptionQuotaExhausted(RuntimeError):
    pass


def snapshot(result):
    from scripts.product_width_watch import weekly_snapshot
    weekly = weekly_snapshot(result)
    limit = result.get('rateLimitsByLimitId', {}).get('codex') or result.get('rateLimits', {})
    windows = []
    for name in ('primary', 'secondary'):
        window = limit.get(name)
        if window is None:
            continue
        used = window.get('usedPercent')
        duration = window.get('windowDurationMins')
        if type(used) not in (int, float) or not 0 <= used <= 100 or type(duration) is not int or duration <= 0:
            raise ValueError('Malformed subscription window')
        windows.append({'name': name, 'duration_minutes': duration,
                        'remaining_percent': 100-used, 'resets_at': window.get('resetsAt')})
    return {'weekly': weekly, 'windows': windows}


async def _read():
    from scripts.product_width_watch import Rpc
    async with Rpc() as rpc:
        return await rpc.call('account/rateLimits/read', {})


def _read_sync():
    """Read fresh quota when a synchronous callback owns an active loop.

    Create the RPC and coroutine on the worker's own loop. Never cache quota;
    worker exceptions still reach the admission guard.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_read())
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix='subscription-quota') as worker:
        return worker.submit(lambda: asyncio.run(_read())).result()


class SubscriptionQuotaGuard:
    def __init__(self, output, *, remaining_floor=1, reader=None):
        if type(remaining_floor) not in (int, float) or not 0 < remaining_floor < 100:
            raise ValueError('Declare a positive subscription reserve')
        self.output = Path(output)
        self.remaining_floor = remaining_floor
        self.reader = reader or _read_sync

    def __call__(self):
        self.output.mkdir(parents=True, exist_ok=True)
        record = {'at': datetime.now(timezone.utc).isoformat(), 'floor_percent': self.remaining_floor,
                  'billing': 'subscription_only', 'paid_fallback': False}
        try:
            current = snapshot(self.reader())
            record['quota'] = current
            if any(w['remaining_percent'] <= self.remaining_floor for w in current['windows']):
                record['status'] = 'held_at_floor'
                raise SubscriptionQuotaExhausted('Subscription window at or below the authorized remaining floor')
            record['status'] = 'admitted'
            return current
        except SubscriptionQuotaExhausted:
            raise
        except Exception as error:
            record.update(status='held_unverifiable', error_type=type(error).__name__, error=str(error))
            raise SubscriptionQuotaUnavailable('Cannot verify subscription usage; model dispatch held') from error
        finally:
            with (self.output/'checks.jsonl').open('a') as stream:
                stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False)+'\n')
