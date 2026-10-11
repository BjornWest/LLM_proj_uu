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
import math
from pathlib import Path


class SubscriptionQuotaUnavailable(RuntimeError):
    pass


class SubscriptionQuotaExhausted(RuntimeError):
    pass


def _applicable_snapshot(result):
    """Validate a complete read, distinguishing explicit null from omission.

    Nullable windows are part of the app-server protocol. Null is not an
    unlimited allowance: at least one fully known Codex window is required.
    """
    if not isinstance(result, dict):
        raise ValueError('Malformed subscription quota response')
    if result.get('ordinaryUsageAllowed') is not True:
        raise ValueError('Ordinary subscription usage is not confirmed')
    if set(result) - {'ordinaryUsageAllowed', 'accountId', 'rateLimits',
                      'rateLimitsByLimitId', 'rateLimitResetCredits', 'rateLimitUpsell'}:
        raise ValueError('Unknown subscription quota response fields')
    if not isinstance(result.get('rateLimits'), dict):
        raise ValueError('Complete legacy quota view required by read protocol')

    allowed = {'limitId', 'limitName', 'normalModelSlug', 'primary', 'secondary',
               'credits', 'individualLimit', 'spendControlReached', 'planType',
               'rateLimitReachedType'}

    def view(bucket):
        if not isinstance(bucket, dict) or bucket.get('limitId') != 'codex':
            raise ValueError('Known Codex subscription bucket required')
        if set(bucket) - allowed:
            raise ValueError('Unknown subscription quota fields')
        plans = {'free', 'go', 'plus', 'pro', 'prolite', 'promax', 'team', 'business',
                 'enterprise', 'edu', 'edu_plus', 'edu_pro', 'self_serve_business_prolite'}
        if bucket.get('planType') not in plans:
            raise ValueError('Known included-usage plan required; no usage-based billing')
        credits = bucket.get('credits')
        if credits is not None and (not isinstance(credits, dict) or
                set(credits) - {'hasCredits', 'unlimited', 'balance'} or
                type(credits.get('hasCredits')) is not bool or
                type(credits.get('unlimited')) is not bool or
                (credits.get('balance') is not None and not isinstance(credits['balance'], str))):
            raise ValueError('Malformed credit metadata; never use it as allowance')
        if bucket.get('rateLimitReachedType') is not None:
            raise ValueError('Subscription limit state blocks dispatch')
        spend = bucket.get('spendControlReached')
        if spend is not None and (type(spend) is not bool or spend):
            raise ValueError('Subscription spend-control state blocks dispatch')
        individual = bucket.get('individualLimit')
        if individual is not None:
            if (not isinstance(individual, dict) or
                    set(individual) != {'limit', 'used', 'remainingPercent', 'resetsAt'} or
                    not isinstance(individual['limit'], str) or not individual['limit'] or
                    not isinstance(individual['used'], str) or not individual['used'] or
                    type(individual['remainingPercent']) is not int or
                    not 0 <= individual['remainingPercent'] <= 100 or
                    type(individual['resetsAt']) is not int or not 0 <= individual['resetsAt'] < 2**63):
                raise ValueError('Malformed individual subscription limit')
            individual = {'remaining_percent': individual['remainingPercent'],
                          'resets_at': individual['resetsAt']}
        windows, states = [], {}
        for name in ('primary', 'secondary'):
            if name not in bucket:
                raise ValueError('Missing subscription window field: ' + name)
            window = bucket[name]
            if window is None:
                states[name] = 'not_applicable'
                continue
            if not isinstance(window, dict) or set(window) != {'usedPercent', 'windowDurationMins', 'resetsAt'}:
                raise ValueError('Malformed subscription window: ' + name)
            used, duration, reset = (window['usedPercent'], window['windowDurationMins'], window['resetsAt'])
            if (type(used) not in (int, float) or (type(used) is float and not math.isfinite(used)) or
                    not 0 <= used <= 100 or
                    type(duration) is not int or not 0 < duration < 2**63 or
                    type(reset) is not int or not 0 <= reset < 2**63):
                raise ValueError('Unknown or malformed subscription window: ' + name)
            states[name] = 'applicable'
            windows.append({'name': name, 'duration_minutes': duration,
                            'remaining_percent': 100-used, 'resets_at': reset})
        if not windows:
            raise ValueError('At least one known subscription quota window required')
        weekly = [window for window in windows if window['duration_minutes'] == 10080]
        week = min(weekly, key=lambda window: window['remaining_percent']) if weekly else None
        return {'weekly': {'used_percent': 100-week['remaining_percent'],
                           'remaining_percent': week['remaining_percent'],
                           'resets_at': week['resets_at'], 'limit_id': 'codex'} if week else None,
                'windows': windows, 'window_states': states, 'individual_limit': individual}

    views = []
    multiple = result.get('rateLimitsByLimitId')
    if multiple is not None:
        if not isinstance(multiple, dict) or 'codex' not in multiple:
            raise ValueError('Codex bucket missing from multi-bucket quota response')
        views.append(view(multiple['codex']))
    if result.get('rateLimits') is not None:
        views.append(view(result['rateLimits']))
    if not views:
        raise ValueError('Subscription quota snapshot is unavailable')
    if any(candidate != views[0] for candidate in views[1:]):
        raise ValueError('Conflicting subscription quota views')
    return views[0]


def snapshot(result, *, require_complete_windows=False):
    if require_complete_windows:
        return _applicable_snapshot(result)
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

    def __call__(self, *, require_complete_windows=False):
        self.output.mkdir(parents=True, exist_ok=True)
        record = {'at': datetime.now(timezone.utc).isoformat(), 'floor_percent': self.remaining_floor,
                  'billing': 'subscription_only', 'paid_fallback': False}
        try:
            current = snapshot(self.reader(), require_complete_windows=require_complete_windows)
            record['quota'] = current
            limits = current['windows'] + ([current['individual_limit']] if current.get('individual_limit') else [])
            if any(w['remaining_percent'] <= self.remaining_floor for w in limits):
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
