"""User-authorized hourly Product review; wait for explicit coordinator registration.

No daemon/session creation, resumes, goal creation, or generation-worker mutation.
The generation coordinator owns its own stricter quota guard. This process only
starts scheduled review turns in the existing Product thread while it is idle.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import fcntl
import json
from pathlib import Path
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
SOCKET = '/home/bjorn/.codex/app-server-control/app-server-control.sock'
STATE = ROOT / '.local/product-width/reviewer'
REGISTRATION = ROOT / '.local/product-width/coordinator.json'
QUOTA_FLOOR = 5  # Bjorn's explicit extension, 2026-10-02.
PROMPT = (
    'Scheduled Product review [PRODUCT-WIDTH-HOURLY-20261001], explicitly requested '
    'by Bjorn. Read docs/agents/overnight-product-width-handoff.md, especially its '
    'hourly-review instructions, and .local/product-width/coordinator.json. '
    'Check the live weekly quota first; at 5% remaining or less, stop the review '
    'and report the pause without starting generation or workers. Otherwise inspect '
    'coordinator progress, recent package changes and available generated examples. '
    'Compare semantic choices with our pilot and recorded user reasoning while '
    'judging what makes sense for each actual product; do not force the footwear '
    'format onto other goods. Use a bounded review, record findings under '
    '.local/product-width/reviews/, and steer the coordinator only for an actionable '
    'blocker or design correction. Never edit worker-owned files or restart sessions. '
    'Finish this one review, without creating a persistent goal.'
)
PROMPT_NO_QUOTA = PROMPT.replace(
    'Check the live weekly quota first; at 5% remaining or less, stop the review '
    'and report the pause without starting generation or workers. Otherwise inspect ',
    'Bjorn has resumed the goal after a quota reset and disabled recurring quota '
    'checks; do not query quota or apply the previous weekly floor. Inspect '
)


def weekly_snapshot(result):
    """Choose the actual Codex weekly window; never use its reserve-model bucket."""
    limit = result.get('rateLimitsByLimitId', {}).get('codex')
    if limit is None:
        candidate = result.get('rateLimits', {})
        if candidate.get('limitId') == 'codex':
            limit = candidate
    if not limit:
        raise ValueError('Codex quota is unavailable')
    for name in ('primary', 'secondary'):
        window = limit.get(name)
        if window and window.get('windowDurationMins') == 10080:
            used = window.get('usedPercent')
            reset = window.get('resetsAt')
            if isinstance(used, bool) or not isinstance(used, (int, float)) or not 0 <= used <= 100 or not isinstance(reset, int):
                raise ValueError('Malformed weekly quota')
            return {'used_percent': used, 'remaining_percent': 100-used,
                    'resets_at': reset, 'limit_id': 'codex'}
    raise ValueError('Codex weekly quota is unavailable')


def next_action(quota, registration, reviewer, now, due, reset):
    if quota is not None and quota['remaining_percent'] <= QUOTA_FLOOR:
        return 'quota_pause'
    if quota is not None and reset is not None and abs(quota['resets_at'] - reset) > 5:
        return 'window_changed'
    if registration is None:
        return 'waiting_for_registration'
    if registration.get('status') == 'complete':
        return 'complete'
    if registration.get('status') != 'active':
        return 'coordinator_paused'
    if now < due:
        return 'waiting_for_hour'
    if reviewer != 'idle':
        return 'reviewer_unavailable'
    return 'review_due'


def read_registration():
    if not REGISTRATION.exists():
        return None
    value = json.loads(REGISTRATION.read_text())
    if value.get('version') != 'product-width-coordinator-v1' or not isinstance(value.get('thread_id'), str) or not value['thread_id']:
        raise ValueError('Malformed coordinator registration')
    if value.get('status') not in ('active', 'paused', 'complete'):
        raise ValueError('Invalid coordinator status')
    return value


class Rpc:
    async def __aenter__(self):
        import websockets
        self.ws = await websockets.unix_connect(SOCKET, uri='ws://localhost/rpc',
                                               compression=None, max_size=32*1024*1024, open_timeout=5)
        self.sequence = 0
        await self.call('initialize', {'clientInfo': {'name': 'product_width_hourly_review', 'version': '1'},
                                       'capabilities': {'experimentalApi': True}})
        await self.ws.send(json.dumps({'method': 'initialized'}))
        return self

    async def __aexit__(self, *_):
        await self.ws.close()

    async def call(self, method, params):
        self.sequence += 1
        await self.ws.send(json.dumps({'id': self.sequence, 'method': method, 'params': params}))
        async with asyncio.timeout(15):
            while True:
                value = json.loads(await self.ws.recv())
                if value.get('id') == self.sequence:
                    if 'error' in value:
                        raise RuntimeError(json.dumps(value['error']))
                    return value['result']


def save(state, event):
    state['last_event'] = event
    state['updated_at'] = datetime.now(timezone.utc).isoformat()
    temporary = STATE / 'state.tmp'
    temporary.write_text(json.dumps(state, indent=2)+'\n')
    temporary.replace(STATE / 'state.json')
    with (STATE / 'events.jsonl').open('a') as stream:
        stream.write(json.dumps({'at': state['updated_at'], 'event': event,
                                 'quota': state.get('quota')})+'\n')


async def run(args):
    monitor_quota = not getattr(args, 'no_quota_checks', False)
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / 'lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Reviewer already running')
        state = {'version': 'product-width-hourly-review-v1', 'reviewer_thread_id': args.thread,
                 'status': 'running', 'next_due': None, 'window_reset': None,
                 'quota_monitoring_enabled': monitor_quota}
        # A monitor reload must preserve cadence/window and its exact owned turn;
        # it must never reset the allowance or interrupt a later ordinary turn.
        previous_path = STATE / 'state.json'
        if previous_path.exists():
            previous = json.loads(previous_path.read_text())
            resumable = ('running', 'error_paused') if monitor_quota else ('running', 'error_paused', 'window_changed', 'quota_pause')
            if previous.get('reviewer_thread_id') == args.thread and previous.get('status') in resumable:
                for key in ('next_due', 'window_reset', 'review_turn_id'):
                    if key in previous:
                        state[key] = previous[key]
        if not monitor_quota:
            state['window_reset'] = None
        state['quota_floor_remaining'] = QUOTA_FLOOR if monitor_quota else None
        save(state, 'armed')
        while True:
            if (STATE / 'STOP').exists():
                state['status'] = 'stopped'
                save(state, 'manual_stop')
                return
            try:
                async with Rpc() as rpc:
                    quota = weekly_snapshot(await rpc.call('account/rateLimits/read', {})) if monitor_quota else None
                    if monitor_quota:
                        state['quota'] = quota
                    registration = read_registration()
                    now = time.time()
                    # Start the hourly cadence only after the generation job registers.
                    if registration is not None and state['next_due'] is None:
                        state['next_due'] = now + 3600
                    reviewer = (await rpc.call('thread/read', {'threadId': args.thread, 'includeTurns': False}))['thread']
                    action = next_action(quota, registration, reviewer['status']['type'],
                                         now, state['next_due'] if state['next_due'] is not None else now+3600,
                                         state['window_reset'])
                    if monitor_quota and state['window_reset'] is None:
                        state['window_reset'] = quota['resets_at']
                    if action in ('quota_pause', 'window_changed', 'complete'):
                        state['status'] = action
                        save(state, action)
                        if action == 'quota_pause' and state.get('review_turn_id'):
                            turns = await rpc.call('thread/turns/list', {'threadId': args.thread, 'limit': 1, 'itemsView': 'summary'})
                            current = turns.get('data', [])
                            # Never interrupt a subsequent ordinary user turn.
                            if current and current[0]['id'] == state['review_turn_id'] and current[0]['status'] == 'inProgress':
                                await rpc.call('turn/interrupt', {'threadId': args.thread, 'turnId': state['review_turn_id']})
                                save(state, 'scheduled_review_interrupted_at_quota_floor')
                        return
                    if action == 'review_due':
                        # Recheck immediately before dispatch. Observe, don't resume,
                        # the registered coordinator. No action on other threads.
                        coordinator = (await rpc.call('thread/read', {'threadId': registration['thread_id'], 'includeTurns': False}))['thread']
                        if coordinator.get('cwd') != str(ROOT):
                            raise ValueError('Coordinator belongs to another workspace')
                        if monitor_quota:
                            quota = weekly_snapshot(await rpc.call('account/rateLimits/read', {}))
                            if quota['remaining_percent'] <= QUOTA_FLOOR or abs(quota['resets_at'] - state['window_reset']) > 5:
                                state['quota'] = quota
                                state['status'] = 'quota_pause' if quota['remaining_percent'] <= QUOTA_FLOOR else 'window_changed'
                                save(state, state['status'])
                                return
                        # Persist intent before dispatch: never retry an ambiguous
                        # timeout and accidentally start duplicate review inference.
                        state['next_due'] = now+3600
                        save(state, 'review_dispatch_intent')
                        result = await rpc.call('turn/start', {'threadId': args.thread,
                                               'clientUserMessageId': str(uuid.uuid4()),
                                               'input': [{'type': 'text', 'text': PROMPT if monitor_quota else PROMPT_NO_QUOTA, 'text_elements': []}]})
                        state['review_turn_id'] = result['turn']['id']
                        save(state, 'review_turn_accepted')
                    else:
                        save(state, action)
            except Exception as exc:
                state['status'] = 'error_paused'
                save(state, 'error: '+str(exc)[:700])
                return
            if args.once:
                return
            await asyncio.sleep(60)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--thread', required=True, help='Existing Product reviewer thread, never a generated worker')
    parser.add_argument('--once', action='store_true', help='Perform one read-only poll unless a review is due')
    parser.add_argument('--no-quota-checks', action='store_true', help='User-authorized scheduling without quota polling or quota stops')
    asyncio.run(run(parser.parse_args()))
