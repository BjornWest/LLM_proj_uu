"""Destroy the rented instance at min(allocation + 5.5 h, Vast credit < $0.50). Checks every 10 min.

  autodestroy.py check    parse credit/instance once and print (no destroy)
  autodestroy.py run      loop (start with nohup); logs to vast/autodestroy.log
"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from vastapi import client, credit, instances

HERE = Path(__file__).resolve().parent
LOG = HERE / 'autodestroy.log'
rental = json.loads((HERE / 'rental.json').read_text())
IID, DEADLINE, FLOOR, PERIOD = rental['instance_id'], rental['allocation_utc'] + int(5.5 * 3600), 0.5, 600
# Overrides (2026-10-20 SFT phase): --deadline-utc N, --no-credit-floor (Vast auto top-up is on).
if '--deadline-utc' in sys.argv:
    DEADLINE = int(sys.argv[sys.argv.index('--deadline-utc') + 1])
if '--no-credit-floor' in sys.argv:
    FLOOR = float('-inf')


def log(**row):
    row = {'utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), **row}
    with LOG.open('a') as f:
        f.write(json.dumps(row) + '\n')
    print(json.dumps(row), flush=True)


def state(c):
    value = credit(c)
    assert isinstance(value, float) and value == value, 'credit did not parse'
    present = [r for r in instances.show_instances(c) if r['id'] == IID]
    return value, ((present[0].get('actual_status') or present[0].get('cur_state') or 'present') if present else None)


def destroy(c, reason):
    for attempt in range(1, 31):
        _, status = state(c)
        if status is None:
            value, _ = state(c)
            log(event='destroyed_confirmed_absent', reason=reason, attempts=attempt - 1, credit=value)
            return True
        try:
            instances.destroy_instance(c, IID)
            log(event='destroy_requested', reason=reason, attempt=attempt)
        except Exception as error:
            log(event='destroy_call_failed', attempt=attempt, error=repr(error)[:300])
        time.sleep(15)
    log(event='STILL_PRESENT_after_30_attempts', reason=reason)
    return False


def main():
    if sys.argv[1] == 'check':
        c = client(); value, status = state(c)
        print(json.dumps({'credit_usd': value, 'instance': IID, 'status': status, 'deadline_utc': DEADLINE, 'credit_floor': FLOOR,
                          'seconds_left': DEADLINE - time.time(), 'would_destroy_now': time.time() >= DEADLINE or value < FLOOR}))
        return
    log(event='armed', instance=IID, deadline_utc=DEADLINE, credit_floor=FLOOR, period_s=PERIOD)
    while True:
        try:
            c = client(); value, status = state(c)
            log(event='poll', credit=round(value, 4), status=status, seconds_left=int(DEADLINE - time.time()))
            if status is None:
                log(event='instance_absent_exit'); return
            if time.time() >= DEADLINE or value < FLOOR:
                if destroy(c, 'deadline' if time.time() >= DEADLINE else 'credit_floor'):
                    return
        except Exception as error:
            log(event='poll_failed', error=repr(error)[:300])
        # Sleep in slices so the deadline is honoured within a minute of passing.
        end = time.time() + PERIOD
        while time.time() < min(end, DEADLINE + 1):
            time.sleep(30)
        if time.time() >= DEADLINE:
            time.sleep(30)  # past the deadline: keep retrying, but not in a tight loop


if __name__ == '__main__':
    main()
