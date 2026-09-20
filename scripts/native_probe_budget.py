"""Development native-tool budget, derived from the frozen curation sweep backend.

Reservations include the complete serialized request (schemas, native assistant
calls and tool results), plus overhead. Historical curation code is unchanged.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
import fcntl
import hashlib
import json
import math
from pathlib import Path
import time
from intent_browser.backend import ChatCompletionsBackend, BackendResponseError
from intent_browser.openrouter import provider_options, routing_record
from intent_browser.trace import write_json


def now():
    return datetime.now(timezone.utc).isoformat()


def state_digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def request_options(config):
    result = provider_options(config['providers'])
    result['provider']['max_price'] = {'prompt': float(config['prompt_price_cap']),
                                     'completion': float(config['output_price_cap']), 'request': 0}
    return result


def reservation(bound, max_tokens, config):
    return (Decimal(bound) * Decimal(config['prompt_price_cap']) +
            Decimal(max_tokens) * Decimal(config['output_price_cap'])) / 1000000


def initial_ledger(config, inherited):
    result = {'protocol_id': config['budget_id'], 'approved_cap_usd': config['cap_usd'],
            'carried_reservations_usd': config['carried_usd'], 'new_reserved_cost_usd': '0',
            'reserved_cost_usd': config['carried_usd'], 'not_before_epoch': 0,
            'inherited': inherited, 'requests': []}
    if config.get('settle_reported_cost'):
        result.update(accounting='settled-cost-v1', reported_cost_usd='0', unresolved_reserved_usd='0',
                      committed_cost_usd=config['carried_usd'])
    return result


def settled_totals(rows, carried):
    """Retain original reservations; settle only verified completed responses."""
    reported=Decimal(0);unresolved=Decimal(0)
    for row in rows:
        amount=Decimal(row['reservation_usd'])
        if row['status']=='completed' and not row.get('audit_issue'):
            raw=(row.get('model_response') or {}).get('usage') or {}
            try:
                cost=Decimal(str(row.get('reported_cost_usd')))
                raw_cost=Decimal(str(raw.get('cost')))
                if not cost.is_finite() or not Decimal(0)<=cost<=amount or cost!=raw_cost:
                    raise ValueError('Unverified settlement cost')
            except InvalidOperation as exc:raise ValueError('Unverified settlement cost') from exc
            reported+=cost
        else:
            unresolved+=amount
    return {'reported_cost_usd':str(reported),'unresolved_reserved_usd':str(unresolved),
            'committed_cost_usd':str(Decimal(carried)+reported+unresolved)}


class NativeProbeBackend(ChatCompletionsBackend):
    supports_native_tools = True
    def __init__(self, key, ledger, validate, config, case_id, *, clock=time.time, sleep=time.sleep):
        self.config, self.case_id = config, case_id
        self.MODEL = config['model']
        self.MAX_TOKENS, self.MAX_STEPS = config['max_tokens'], config['max_steps']
        self.INPUT_BOUND, self.PACE = config['input_byte_limit'], config['pace_seconds']
        self.CAP, self.CARRIED = Decimal(config['cap_usd']), Decimal(config['carried_usd'])
        self.PROVIDERS = tuple(config['providers'])
        super().__init__('https://openrouter.ai/api/v1', self.MODEL, key, max_tokens=self.MAX_TOKENS,
                         request_options=request_options(config), session_routing=True)
        self.ledger, self.validate = Path(ledger), validate
        self.clock, self.sleep = clock, sleep
        self.http = None
        self.stopped = False
        self.ready = None
        self.dispatch_epoch = None
        self.client.event_hooks['request'].append(self.capture_dispatch)
        self.client.event_hooks['response'].append(self.capture_response)

    def capture_dispatch(self, request):
        # httpx request-hook entry, not socket-write confirmation. Never headers.
        self.dispatch_epoch = self.clock()

    def _read_ledger(self):
        data = json.loads(self.ledger.read_text())
        if any(Decimal(r['reservation_usd']) != reservation(r['input_byte_bound'], r['max_tokens'], self.config) for r in data['requests']):
            raise ValueError('Unexpected reservation amount; no refunds or credits allowed')
        new_total = sum((Decimal(r['reservation_usd']) for r in data['requests']), Decimal(0))
        settled=self.config.get('settle_reported_cost',False)
        liability=new_total
        if settled:
            totals=settled_totals(data['requests'],self.CARRIED)
            if data.get('accounting')!='settled-cost-v1' or any(Decimal(data.get(k,'NaN'))!=Decimal(v) for k,v in totals.items()):
                raise ValueError('Settlement ledger mismatch')
            liability=Decimal(totals['committed_cost_usd'])-self.CARRIED
        if new_total < 0 or self.CARRIED + liability > self.CAP:
            raise ValueError('Budget outside authorized bounds')
        if (data.get('protocol_id') != self.config['budget_id'] or Decimal(data['approved_cap_usd']) != self.CAP or
                Decimal(data['carried_reservations_usd']) != self.CARRIED or
                Decimal(data['new_reserved_cost_usd']) != new_total or
                Decimal(data['reserved_cost_usd']) != self.CARRIED + new_total):
            raise ValueError('Budget ledger mismatch; no request sent')
        if any(r['status'] != 'completed' or r.get('audit_issue') for r in data['requests']):
            raise ValueError('Prior failed/unknown/audit attempt requires review; no request sent')
        if sum(r['case_id'] == self.case_id for r in data['requests']) >= self.MAX_STEPS:
            raise ValueError('Case request limit reached; no request sent')
        deadline = data.get('not_before_epoch', 0)
        if type(deadline) not in (float, int) or not math.isfinite(deadline):
            raise ValueError('Invalid readiness deadline')
        return data, liability, deadline

    def _update_totals(self,data):
        reserved=sum((Decimal(row['reservation_usd']) for row in data['requests']),Decimal(0))
        data.update(reserved_cost_usd=str(self.CARRIED+reserved),new_reserved_cost_usd=str(reserved))
        if self.config.get('settle_reported_cost'):data.update(settled_totals(data['requests'],self.CARRIED))

    def wait_until_ready(self):
        if self.stopped or not self.session_id:
            raise ValueError('Stopped or missing episode session; no readiness check')
        self.ready = None
        started = self.clock()
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        while True:
            with self.ledger.with_suffix('.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                data, _, deadline = self._read_ledger()
                if self.clock() >= deadline:
                    self.ready = {'state_sha256': state_digest(data), 'session_id': self.session_id,
                                  'started_epoch': started, 'ready_epoch': self.clock(),
                                  'wait_seconds': self.clock() - started, 'not_before_epoch': deadline}
                    return dict(self.ready)
            # No lock held during sleep. No source validation, reservation or HTTP.
            self.sleep(max(0, min(60, deadline - self.clock())))

    def capture_response(self, response):
        value = response.headers.get('retry-after')
        seconds = None
        if value is not None:
            try:
                seconds = float(value)
            except ValueError:
                try:
                    seconds = parsedate_to_datetime(value).timestamp() - self.clock()
                except (ValueError, TypeError, OverflowError):
                    pass
        if seconds is not None:
            seconds = max(0, seconds) if math.isfinite(seconds) else None
        self.http = {'status': response.status_code, 'retry_after': value,
                     'retry_after_seconds': seconds, 'received_epoch': self.clock()}

    def validate_messages(self, messages):
        # Default remains text-only. A separately validated image probe must
        # explicitly adopt an image bound without rewriting transmitted messages.
        if any(not isinstance(m, dict) or m.get('role') not in ('system','user','assistant','tool')
               or (m.get('content') is not None and not isinstance(m.get('content'),str)) for m in messages):
            raise ValueError('Only native text/tool messages fit this reservation')

    def complete(self, messages):
        if self.stopped or not self.session_id:
            raise ValueError('Stopped or missing episode session; no request sent')
        self.validate_messages(messages)
        request = {'model': self.model, 'messages': messages, 'temperature': 0,
                   'max_tokens': self.max_tokens, 'stream': False, **self.request_options,
                   'session_id': self.session_id}
        if not request.get('tools'): raise ValueError('Native tools must be configured before dispatch')
        bound = len(json.dumps(request, ensure_ascii=False, allow_nan=False).encode('utf-8')) + 2048
        if bound > self.INPUT_BOUND:
            raise ValueError('Input exceeds reservation bound; no request sent')
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            ready, self.ready = self.ready, None  # consume one hook result
            data, new_total, deadline = self._read_ledger()
            if (ready is None or ready['session_id'] != self.session_id or
                    ready['state_sha256'] != state_digest(data) or self.clock() < deadline):
                raise ValueError('Readiness changed or hook missing; reject stale prompt without waiting')
            # Capture and prompt construction occurred after readiness. Recheck
            # immutable sources here, then reserve once under the dispatch lock.
            self.validate()
            amount = reservation(bound, self.MAX_TOKENS, self.config)
            total = self.CARRIED + new_total + amount
            if total > self.CAP:
                raise ValueError('Development reservation cap reached; no request sent')
            request = {'model': self.model, 'messages': messages, 'temperature': 0,
                       'max_tokens': self.max_tokens, 'stream': False, **self.request_options,
                       'session_id': self.session_id}
            row = {'protocol_id': self.config['budget_id'], 'case_id': self.case_id,
                   'session_id': self.session_id, 'status': 'reserved', 'started_at': now(),
                   'reservation_epoch': self.clock(), 'readiness': ready, 'reservation_usd': str(amount), 'max_tokens': self.MAX_TOKENS,
                   'input_byte_bound': bound, 'model_request': request, 'model_response': None,
                   'reported_cost_usd': None, 'audit_issue': None}
            data['requests'].append(row)
            self._update_totals(data)
            write_json(self.ledger, data)
            self.http = None
            self.dispatch_epoch = None
            try:
                completion = super().complete(messages)
                row['model_response'] = completion.raw
                row['routing'] = routing_record(completion.request, completion.raw)
                raw = completion.raw
                usage = raw.get('usage') if isinstance(raw.get('usage'), dict) else {}
                row['reported_cost_usd'] = usage.get('cost')
                issues = []
                if completion.request != request:
                    issues.append('Request differs from reservation')
                if raw.get('model') != self.MODEL or str(raw.get('provider', '')).lower() not in self.PROVIDERS:
                    issues.append('Unexpected model/provider')
                try:
                    cost = Decimal(str(usage.get('cost')))
                    if not cost.is_finite() or not Decimal(0) <= cost <= amount:
                        issues.append('Invalid cost or reservation exceeded')
                except InvalidOperation:
                    issues.append('Missing/invalid cost')
                for field, limit in [('prompt_tokens', bound), ('completion_tokens', self.MAX_TOKENS)]:
                    value = usage.get(field)
                    if type(value) is not int or not 0 <= value <= limit:
                        issues.append('Invalid token usage: ' + field)
                if issues:
                    row['audit_issue'] = '; '.join(issues)
                    raise BackendResponseError(row['audit_issue'], request, raw)
                row['status'] = 'completed'
                return completion
            except BaseException as exc:
                row.update(status='error', error_type=type(exc).__name__)
                if row['model_response'] is None:
                    row['model_response'] = getattr(exc, 'response_payload', None)
                row['routing'] = routing_record(request, row['model_response'])
                self.stopped = True
                raise
            finally:
                end = self.clock()
                row.update(finished_at=now(), attempt_finished_epoch=end, http=self.http,
                           http_request_hook_epoch=self.dispatch_epoch,
                           timing_scope='httpx request hook; response headers hook; backend attempt end (not socket/body timestamps)')
                # This is attempt completion, NOT a confirmed HTTP response if
                # transport failed. Interrupted processes leave status=reserved.
                cooldown = max(self.PACE, 60 if row['status'] != 'completed' else 0,
                               (self.http or {}).get('retry_after_seconds') or 0)
                data['not_before_epoch'] = end + cooldown
                self._update_totals(data)
                write_json(self.ledger, data)
