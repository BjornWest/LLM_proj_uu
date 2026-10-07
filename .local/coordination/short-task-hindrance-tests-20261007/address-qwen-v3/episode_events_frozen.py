"""Durable, opt-in episode/suite completion subscriptions; no resident watcher.

Producers publish once their trace and grade are closed. Terminal process failure
also counts as finished, never as task success. SQLite serializes concurrent
producers and builds a transactional outbox. Delivery acceptance is not reading.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

ROOT = Path('/home/bjorn/code/LLM_proj_uu')
TERMINAL = {"succeeded", "failed", "interrupted", "not_started"}


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def now():
    return datetime.now(timezone.utc).isoformat()


class Events:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS suites(id TEXT PRIMARY KEY, episodes TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS episodes(
                  suite TEXT, id TEXT, state TEXT NOT NULL, payload TEXT,
                  PRIMARY KEY(suite,id));
                CREATE TABLE IF NOT EXISTS subscriptions(
                  id TEXT PRIMARY KEY, suite TEXT NOT NULL, recipient TEXT NOT NULL,
                  episode TEXT, milestones TEXT NOT NULL, final INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS notices(
                  id TEXT PRIMARY KEY, subscription TEXT NOT NULL, recipient TEXT NOT NULL,
                  payload TEXT NOT NULL, state TEXT NOT NULL, delivery TEXT);
            """)

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=20, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA busy_timeout=20000")
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def register(self, suite, episodes):
        if not isinstance(suite, str) or not suite or not episodes or any(
                not isinstance(e, str) or not e for e in episodes) or len(set(episodes)) != len(episodes):
            raise ValueError("Declare a nonempty finite suite with unique episode IDs")
        with self.transaction() as db:
            old = db.execute("SELECT episodes FROM suites WHERE id=?", (suite,)).fetchone()
            if old and old[0] != encoded(episodes):
                raise ValueError("Suite membership/order is immutable")
            if not old:
                db.execute("INSERT INTO suites VALUES (?,?)", (suite, encoded(episodes)))
                db.executemany("INSERT INTO episodes VALUES (?,?,'pending',NULL)",
                               [(suite, e) for e in episodes])

    def subscribe(self, subscription, suite, recipient, *, episode=None, milestones=(), final=True):
        if not subscription or not recipient or type(final) is not bool:
            raise ValueError("Explicit subscription ID, recipient and final flag required")
        milestones = sorted(set(milestones))
        if any(type(n) is not int or n <= 0 for n in milestones):
            raise ValueError("Milestones must be positive terminal counts")
        values = (subscription, suite, recipient, episode, encoded(milestones), int(final))
        with self.transaction() as db:
            row = db.execute("SELECT episodes FROM suites WHERE id=?", (suite,)).fetchone()
            if row is None:
                raise ValueError("Unknown suite")
            ids = json.loads(row[0])
            if (episode is not None and (episode not in ids or milestones or final)) or any(n > len(ids) for n in milestones):
                raise ValueError("Episode subscription uses final=False; milestones must fit the suite")
            old = db.execute("SELECT * FROM subscriptions WHERE id=?", (subscription,)).fetchone()
            if old and tuple(old) != values:
                raise ValueError("Subscription ID already has different semantics")
            if not old:
                db.execute("INSERT INTO subscriptions VALUES (?,?,?,?,?,?)", values)
            self._notices(db, suite)

    def start(self, suite, episode):
        with self.transaction() as db:
            row = db.execute("SELECT state FROM episodes WHERE suite=? AND id=?", (suite, episode)).fetchone()
            if row is None or row[0] != "pending":
                raise ValueError("Episode is unknown or already claimed; no automatic retry")
            db.execute("UPDATE episodes SET state='running' WHERE suite=? AND id=?", (suite, episode))

    def finish(self, suite, episode, state, payload):
        if state not in TERMINAL or not isinstance(payload, dict):
            raise ValueError("Terminal state and evidence dictionary required")
        body = encoded(payload)
        with self.transaction() as db:
            row = db.execute("SELECT state,payload FROM episodes WHERE suite=? AND id=?", (suite, episode)).fetchone()
            if row is None:
                raise ValueError("Unknown episode")
            if row[0] in TERMINAL:
                if (row[0], row[1]) != (state, body):
                    raise ValueError("Conflicting terminal event; preserve first evidence")
                return
            if row[0] != "running" and state != "not_started":
                raise ValueError("Episode must be claimed before completion")
            db.execute("UPDATE episodes SET state=?,payload=? WHERE suite=? AND id=?", (state, body, suite, episode))
            self._notices(db, suite)

    def _notices(self, db, suite):
        episodes = [dict(r) for r in db.execute("SELECT id,state,payload FROM episodes WHERE suite=? ORDER BY id", (suite,))]
        terminal = [r for r in episodes if r['state'] in TERMINAL]
        count = len(terminal)
        summary = {"suite": suite, "finished": count, "total": len(episodes),
                   "process_succeeded": sum(r['state'] == 'succeeded' for r in episodes),
                   "process_failed": sum(r['state'] == 'failed' for r in episodes),
                   "interrupted": sum(r['state'] == 'interrupted' for r in episodes),
                   "not_started": sum(r['state'] == 'not_started' for r in episodes),
                   "scope": "Terminal episodes, including failures; process success is not task success"}
        for sub in db.execute("SELECT * FROM subscriptions WHERE suite=?", (suite,)):
            triggers = []
            if sub['episode']:
                match = next((r for r in terminal if r['id'] == sub['episode']), None)
                if match:
                    triggers.append(('episode:' + match['id'], {**summary, "kind": "episode", "episode": match['id'],
                                     "state": match['state'], "evidence": json.loads(match['payload'])}))
            else:
                triggers.extend(('milestone:' + str(n), {**summary, "kind": "milestone", "milestone": n})
                                for n in json.loads(sub['milestones']) if count >= n)
                if sub['final'] and count == len(episodes):
                    triggers.append(('complete', {**summary, "kind": "suite_complete"}))
            for trigger, payload in triggers:
                notice = sha256(encoded([sub['id'], trigger]).encode()).hexdigest()[:24]
                db.execute("INSERT OR IGNORE INTO notices VALUES (?,?,?,?, 'pending',NULL)",
                           (notice, sub['id'], sub['recipient'], encoded(payload)))

    def notices(self, recipient=None):
        with self.transaction() as db:
            rows = db.execute("SELECT * FROM notices" + (" WHERE recipient=?" if recipient else "") + " ORDER BY rowid",
                              (recipient,) if recipient else ())
            return [{**dict(r), "payload": json.loads(r['payload']),
                     "delivery": json.loads(r['delivery']) if r['delivery'] else None} for r in rows]

    def snapshot(self):
        with self.transaction() as db:
            return {'suites': [dict(r) for r in db.execute('SELECT * FROM suites')],
                    'episodes': [{**dict(r), 'payload': json.loads(r['payload']) if r['payload'] else None}
                                 for r in db.execute('SELECT * FROM episodes')]}

    def reconcile_delivery(self, notice_id, state, evidence):
        """Explicit receipt-backed resolution only; never an automatic resend."""
        if state not in {'accepted', 'pending', 'rejected'} or not isinstance(evidence, dict) or not evidence:
            raise ValueError('Explicit delivery decision and retained evidence required')
        with self.transaction() as db:
            old = db.execute('SELECT state,delivery FROM notices WHERE id=?', (notice_id,)).fetchone()
            if old is None or old['state'] not in {'delivering', 'delivery_unknown'}:
                raise ValueError('Only uncertain/in-flight delivery may be reconciled')
            db.execute('UPDATE notices SET state=?,delivery=? WHERE id=?',
                       (state, encoded({'reconciliation': evidence, 'previous_delivery': old['delivery'],
                                        'at': now(), 'read_acknowledged': False}), notice_id))

    def deliver(self, sender):
        """Claim before network I/O. Unknown delivery never retries automatically.

        A crash between claim/send/record leaves `delivering`, requiring explicit
        receipt reconciliation; impossible exactly-once network delivery is not
        claimed. Definite pre-send unreachability stays pending for later flush.
        """
        for notice in self.notices():
            if notice['state'] != 'pending':
                continue
            with self.transaction() as db:
                claimed = db.execute("UPDATE notices SET state='delivering' WHERE id=? AND state='pending'", (notice['id'],)).rowcount
            if not claimed:
                continue
            try:
                result = sender(notice)
                state = result['state']
                if state not in {'accepted', 'inbox', 'pending', 'delivery_unknown', 'rejected'}:
                    raise ValueError("Invalid delivery state")
            except Exception as error:
                state, result = 'delivery_unknown', {'state': 'delivery_unknown', 'error': str(error)}
            with self.transaction() as db:
                db.execute("UPDATE notices SET state=?,delivery=? WHERE id=?", (state, encoded({**result, "at": now(), "read_acknowledged": False}), notice['id']))


def codex_sender(notice, *, run=subprocess.run):
    """User explicitly subscribes agent threads. Never resume or interrupt them."""
    recipient = notice['recipient']
    if recipient == 'inbox':
        return {'state': 'inbox', 'transport': 'durable_local_inbox'}
    if not recipient.startswith('codex:'):
        return {'state': 'rejected', 'reason': 'Unsupported recipient'}
    thread = recipient.removeprefix('codex:')
    try:
        result = run([sys.executable, str(ROOT/'scripts/agent_coordination.py'), 'status', '--thread', thread],
                     capture_output=True, text=True, timeout=25)
        if result.returncode:
            return {'state': 'pending', 'reason': 'Status unavailable before any message attempt', 'stderr': result.stderr}
        status = json.loads(result.stdout)
        phase = status['status']['type']
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as error:
        return {'state': 'pending', 'reason': 'Status unavailable before any message attempt', 'error': str(error)}
    payload = notice['payload']
    topic = ('episode ' + payload['episode'] if payload['kind'] == 'episode' else
             'milestone ' + str(payload['milestone']) if payload['kind'] == 'milestone' else 'suite complete')
    verdict = payload.get('evidence', {}).get('task_verdict')
    grade_text = ' Native task grade: ' + str(verdict) + '.' if verdict is not None else ''
    message = (f"Episode completion [{notice['id']}]: {topic}; {payload['finished']}/{payload['total']} terminal in {payload['suite']}. "
               f"Evidence and task grades: {notice['registry']}.{grade_text} Inspect this subscribed result; process completion does not imply task success.")
    if phase == 'active' and status.get('canAcceptDirectInput'):
        command = [sys.executable, str(ROOT/'scripts/agent_coordination.py'), 'steer', '--thread', thread, '--message', message]
    else:
        return {'state': 'pending', 'reason': 'Steering-only delivery: idle/unreachable notifications remain in durable outbox', 'status': status}
    sent = run(command, capture_output=True, text=True, timeout=30)
    return {'state': 'accepted' if sent.returncode == 0 else 'delivery_unknown',
            'transport': 'steer',
            'returncode': sent.returncode, 'stdout': sent.stdout, 'stderr': sent.stderr}


def flush(events):
    def send(notice):
        return codex_sender({**notice, 'registry': str(events.path)})
    events.deliver(send)
