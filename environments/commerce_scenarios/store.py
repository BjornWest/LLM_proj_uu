"""Server-side shopping session of one target retailer, and its journal.

The store is the only authority for cookie consent, newsletter, extras and
promotion codes. Basket, delivery option and checkout location are reported by
the page (`sync`) and checked here. Every state change is one journal event
carrying the full state; the sealed journal has the released shape
`website-commerce-session-journal-v1` (with Addendum 1). The private snapshot
is for capture only and is never served.
"""
from copy import deepcopy
from hashlib import sha256
import json
import re
from threading import RLock

from .settings import PURPOSES, plain

JOURNAL = 'website-commerce-session-journal-v1'
MAX_EVENTS = 512
MAX_LINES = 64
MAX_QUANTITY = 999
MAX_KNOWN_OPTIONS = 32768
REASONS = ('not_sealed', 'binding_mismatch', 'no_session', 'multiple_sessions',
           'journal_overflow', 'state_fault')
COOKIE_SAVES = ('accept_all', 'reject_all', 'save_settings')
# Round 8: execution -> (checkout tick that also selects something, selected field).
COUPLED_TRIGGERS = {
    **dict.fromkeys(('marketing_with_age_confirm', 'marketing_with_age_confirm_inline'), ('age_confirm', 'newsletter')),
    **dict.fromkeys(('datashare_with_privacy_ack', 'datashare_with_privacy_ack_inline'), ('privacy_ack', 'newsletter')),
    **dict.fromkeys(('paid_addon_with_terms', 'paid_addon_with_terms_inline'), ('terms', 'extras')),
    **dict.fromkeys(('optin_with_delivery_conditions', 'optin_with_delivery_conditions_inline'),
                    ('delivery_conditions', 'newsletter')),
}
_SESSION = re.compile(r'[0-9a-f-]{8,64}')


def _digest(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             allow_nan=False).encode()).hexdigest()


def _fields(request, *names):
    if set(request) - {'op', 'session'} != set(names):
        raise ValueError('This session operation takes exactly: ' + (', '.join(names) or 'no fields'))


def basket_of(lines):
    """Native quote lines as journal basket lines: one row per offer, sorted."""
    if type(lines) is not list or len(lines) > MAX_LINES:
        raise ValueError('Supply a bounded list of basket lines')
    totals = {}
    for line in lines:
        if (type(line) is not dict or type(line.get('offer_id')) is not str
                or type(line.get('quantity')) is not int or not 1 <= line['quantity'] <= MAX_QUANTITY):
            raise ValueError('Each basket line needs an offer and a positive quantity')
        totals[line['offer_id']] = totals.get(line['offer_id'], 0) + line['quantity']
    return [{'offer_id': offer, 'quantity': totals[offer]} for offer in sorted(totals)]


def checked_overlay(value, codes, delivery_option_id):
    """Validate all consumed fields before any quote enters state or presentation."""
    def text(item):
        return type(item) is str and 0 < len(item.strip()) <= 1000

    def amount(item, *, negative=False):
        return type(item) is int and (-10**12 if negative else 0) <= item <= 10**12

    if (type(value) is not dict or not text(value.get('quote_id'))
            or not amount(value.get('total_minor')) or value.get('currency') != 'SEK'):
        raise ValueError('Overlay needs an authentic id, integer total and SEK currency')
    lines = value.get('lines', [])
    if type(lines) is not list or len(lines) > 32 or any(
            type(row) is not dict or not text(row.get('label'))
            or not amount(row.get('amount_minor'), negative=True) for row in lines):
        raise ValueError('Malformed overlay breakdown')
    feedback = value.get('promotion_feedback', {})
    if type(feedback) is not dict or any(
            type(code) is not str or code not in codes or type(row) is not dict
            or type(row.get('accepted')) is not bool or not text(row.get('feedback'))
            for code, row in feedback.items()):
        raise ValueError('Malformed overlay promotion feedback')
    if 'promotion_codes' in value:
        active = value['promotion_codes']
        if (type(active) is not list or len(active) > 8 or any(type(c) is not str for c in active)
                or len(set(active)) != len(active) or set(active) - set(codes)):
            raise ValueError('Malformed overlay active codes')
    selected = value.get('native_option_id')
    if selected is not None and not text(selected):
        raise ValueError('Malformed overlay selected route')
    if delivery_option_id is not None and selected != delivery_option_id:
        raise ValueError('Overlay priced a different selected route')
    options = value.get('options', [])
    if type(options) is not list or len(options) > 4096 or any(
            type(row) is not dict or not text(row.get('native_option_id'))
            or not amount(row.get('shipping_minor')) or not amount(row.get('total_minor'))
            for row in options):
        raise ValueError('Malformed overlay route amounts')
    if len({row['native_option_id'] for row in options}) != len(options):
        raise ValueError('Duplicate overlay routes')
    if options and not any(row['native_option_id'] == selected
                           and row['total_minor'] == value['total_minor'] for row in options):
        raise ValueError('Overlay selected amount contradicts its route amounts')
    if 'shipping_summary' in value:
        summary = value['shipping_summary']
        if (type(summary) is not dict or set(summary) != {
                'shipping_minor', 'merchandise_minor', 'free_shipping_threshold_minor', 'threshold_met'}
                or not amount(summary.get('shipping_minor')) or not amount(summary.get('merchandise_minor'))
                or summary.get('free_shipping_threshold_minor') is not None
                and not amount(summary['free_shipping_threshold_minor'])
                or type(summary.get('threshold_met')) is not bool):
            raise ValueError('Malformed overlay shipping summary')
        threshold = summary['free_shipping_threshold_minor']
        if summary['threshold_met'] != (threshold is not None and summary['merchandise_minor'] >= threshold):
            raise ValueError('Overlay shipping qualification contradicts its threshold')
        delivery = [row['amount_minor'] for row in lines if row['label'] == 'Delivery']
        if delivery != [summary['shipping_minor']]:
            raise ValueError('Overlay shipping summary contradicts its breakdown')
        if options and next(row for row in options if row['native_option_id'] == selected)['shipping_minor'] != summary['shipping_minor']:
            raise ValueError('Overlay shipping summary contradicts its selected route')
    return deepcopy(value)


class SessionStore:
    def __init__(self, settings, *, offers, runtime_id):
        """`settings` are checked scenario settings; `offers` the retailer's offer ids."""
        if type(runtime_id) is not str or not runtime_id:
            raise ValueError('Session store requires an explicit runtime identity')
        self._settings = settings
        self._offers = frozenset(offers)
        self._runtime_id = runtime_id
        self._lock = RLock()
        newsletter = settings['newsletter']
        self._state = {
            'cookie': {'decided': False, 'preferences': dict.fromkeys(PURPOSES, False), 'pending': None},
            'newsletter': bool(newsletter and newsletter['preselected'] == 'start'),
            'extras': {extra['id']: extra['preselected'] == 'start' for extra in settings['extras']},
            'basket': [], 'promotion_codes': [], 'delivery_option_id': None, 'quote': None,
            'checkout': {'location': 'outside', 'order_id': None},
            'committed': {'cookie': {'decided': False, 'preferences': dict.fromkeys(PURPOSES, False)},
                          'order': None},
        }
        self._before = deepcopy(self._state)
        self._events, self._setup_events = [], []
        self._begun = self._sealed = False
        self._episode_id = self._binding = None
        self._binding_mismatch = False
        self._sessions = []
        self._fault = None
        self._overflow = False
        self._options, self._latest_options = {}, []
        self._dialog_open = False
        self._entered_checkout = False
        self._step = None
        self._reset_trigger = None
        self._reset_directive = False
        self._armed = None
        self._arm_reply = None
        self._feedback = None
        self._quote_reason, self._quote_lines = 'The basket is empty.', []
        self._overlay_options = []
        self._shipping_summary = None
        self._overlay_errors = []
        self._scope_reason = None
        self._order_ids = set()
        self._rate_refreshed = False
        self._shopper_chose_delivery = self._reset_done = False

    # Episode lifecycle (trusted callers only).

    def bind_episode(self, episode_id, binding):
        """Record the episode identity before any request; identity is immutable."""
        if type(episode_id) is not str or not episode_id or type(binding) is not dict or not binding:
            raise ValueError('Bind the actual episode id and its bound binding')
        value = json.loads(json.dumps(binding, allow_nan=False))
        with self._lock:
            if self._sealed:
                raise ValueError('Session store is sealed')
            if self._episode_id is not None:
                if (self._episode_id, self._binding) != (episode_id, value):
                    self._binding_mismatch = True
                    raise ValueError('Session store episode identity is immutable')
                return
            if self._events or self._setup_events or self._sessions:
                self._binding_mismatch = True
                raise ValueError('Bind the episode before the first session request')
            if self._fault is not None:
                raise ValueError('Session store has a prior state fault')
            hooks = []
            for name in ('quote', 'scope'):
                hook = getattr(self._settings.get(name), 'bind_episode', None)
                if hook is not None and all(hook is not prior for prior in hooks):
                    hooks.append(hook)
            try:
                for hook in hooks:
                    hook(episode_id)
            except Exception:
                # A partially bound callback cannot be retried as a different
                # episode or presented as a complete session.
                self._fault = 'Episode callback binding failed'
                raise
            self._episode_id, self._binding = episode_id, value

    def begin(self):
        """Mark the start of the policy: later events are the journal, `before` is now."""
        with self._lock:
            if self._begun or self._sealed:
                raise ValueError('The journal has already begun or is sealed')
            self._begun = True
            self._setup_events, self._events = self._events, []
            self._before = deepcopy(self._state)
            return deepcopy(self._before)

    def seal(self, *, episode_id=None):
        """Freeze the session after browser and Runtime cleanup and return the journal."""
        with self._lock:
            if self._sealed:
                raise ValueError('Session store has already been sealed')
            self._sealed = True
            if episode_id is not None and episode_id != self._episode_id:
                self._binding_mismatch = True
            return self.journal()

    def journal(self):
        """The released envelope. Incomplete journals keep whatever was recorded."""
        with self._lock:
            reason = self._incomplete_reason()
            return {'schema_version': JOURNAL, 'binding': deepcopy(self._binding),
                    'episode_id': self._episode_id, 'retailer_id': self._settings['retailer_id'],
                    'complete': reason is None, 'incomplete_reason': reason,
                    'before': deepcopy(self._before), 'after': deepcopy(self._state),
                    'events': deepcopy(self._events), 'revision': len(self._events)}

    def _incomplete_reason(self):
        checks = (('not_sealed', not self._sealed),
                  ('binding_mismatch', self._binding_mismatch or self._episode_id is None),
                  ('no_session', not self._sessions),
                  ('multiple_sessions', len(self._sessions) > 1),
                  ('journal_overflow', self._overflow),
                  ('state_fault', self._fault is not None))
        return next((reason for reason, failed in checks if failed), None)

    def snapshot(self):
        """Detached private record for trusted capture; never an HTTP response."""
        with self._lock:
            value = {'schema': 'website-commerce-session-store-v1', 'runtime_id': self._runtime_id,
                     'settings_sha256': _digest(plain(self._settings)), 'journal': self.journal(),
                     'setup_events': deepcopy(self._setup_events), 'begun': self._begun,
                     'sealed': self._sealed, 'sessions': list(self._sessions),
                     'state_fault': self._fault, 'overlay_errors': list(self._overlay_errors),
                     'dialog_open': self._dialog_open, 'armed_order': deepcopy(self._armed),
                     'known_delivery_options': len(self._options)}
            value['snapshot_sha256'] = _digest(value)
            return value

    # Requests from the page.

    def handle(self, request):
        """One `POST /api/session` operation; a refusal raises and changes nothing."""
        if type(request) is not dict or type(request.get('op')) is not str:
            raise ValueError('Name a session operation')
        operation = self._OPERATIONS.get(request['op'])
        if operation is None:
            raise ValueError('Unknown session operation')
        with self._lock:
            if self._sealed:
                raise ValueError('The shopping session is closed')
            session = request.get('session')
            if type(session) is not str or not _SESSION.fullmatch(session):
                raise ValueError('Session operations need the page session id')
            try:
                operation(self, request)
            except Exception as error:
                if request['op'] == 'sync':
                    self._fault = self._fault or 'refused sync: ' + str(error)
                elif not isinstance(error, ValueError):
                    self._fault = self._fault or 'session operation failed: ' + str(error)
                raise
            finally:
                if session not in self._sessions and len(self._sessions) < 8:
                    self._sessions.append(session)
            return self._view()

    def observe_quote(self, request, reply):
        """Remember the delivery options a native basket quote offered."""
        basket = basket_of([{'offer_id': line.get('offer_id'), 'quantity': line.get('quantity')}
                            for line in request['lines']])
        with self._lock:
            self._latest_options = []
            for option in reply.get('options') or []:
                self._options.pop(option['id'], None)
                self._options[option['id']] = {
                    'basket': basket, 'total_minor': option['totalMinor'],
                    'choice_ids': sorted({shipment['delivery']['id'] for shipment in option['shipments']}),
                    'selection': deepcopy(option['selection'])}
                self._latest_options.append(option['id'])
            while len(self._options) > MAX_KNOWN_OPTIONS:
                self._options.pop(next(iter(self._options)))

    def default_selection(self, request, reply):
        """The scenario's own default delivery selection for this quote, or None."""
        with self._lock:
            basket = basket_of([{'offer_id': line.get('offer_id'), 'quantity': line.get('quantity')}
                                for line in request['lines']])
            wanted = None
            overlay = self._overlay(basket, self._state['promotion_codes'])
            if overlay is not None and overlay.get('native_option_id'):
                wanted = {'option_id': overlay['native_option_id']}
            if self._refresh_notice() is not None and not self._rate_refreshed:
                # The site's own rate refresh has not happened yet: the shop's native default applies.
                return None
            wanted = wanted or self._settings['delivery']['default']
            if wanted is None:
                return None
            for option in reply.get('options') or []:
                choices = {shipment['delivery']['id'] for shipment in option['shipments']}
                if option['id'] == wanted.get('option_id') or choices == {wanted.get('choice_id')}:
                    return deepcopy(option['selection'])
            return None

    def submit_order(self, submission, native):
        """Run the unchanged native order handler for an armed, known order."""
        with self._lock:
            if self._sealed:
                raise ValueError('The shopping session is closed')
            state = self._state
            try:
                lines = basket_of([{'offer_id': line.get('offer_id'), 'quantity': line.get('quantity')}
                                   for line in submission['quote_request']['lines']])
                option_id = submission['displayed_quote']['option_id']
            except (KeyError, TypeError, AttributeError) as error:
                raise ValueError('Supply the complete order submission') from error
            if lines != state['basket'] or option_id != state['delivery_option_id']:
                self._fault = self._fault or 'order request shows a basket or delivery option the session never saw'
                raise ValueError('Review the current basket and delivery before completing your order.')
            armed = self._armed
            if armed is None:
                raise ValueError('Confirm the current order total before completing your order.')
            value = native(submission)
            order_id = value['confirmation']['id']
            if order_id in self._order_ids:
                return value
            self._order_ids.add(order_id)
            state['committed']['order'] = {
                'order_id': order_id, 'basket': deepcopy(state['basket']),
                'promotion_codes': list(state['promotion_codes']),
                'delivery_option_id': state['delivery_option_id'], 'newsletter': state['newsletter'],
                'extras': dict(state['extras']), 'quote': deepcopy(state['quote']),
                'charges': deepcopy(armed['charges']), 'grand_total_minor': armed['grand_total_minor']}
            # The event's state is the shop after the order: everything cleared, and the
            # next checkout entry counts as a first entry again.
            state['checkout'] = {'location': 'outside', 'order_id': order_id}
            state['basket'], state['promotion_codes'], state['delivery_option_id'] = [], [], None
            state['newsletter'] = False
            state['extras'] = dict.fromkeys(state['extras'], False)
            self._entered_checkout, self._step, self._reset_trigger = False, None, None
            self._event('order_submit', 'user', {'order_id': order_id}, committed=True)
            return value

    # State changes.

    def _event(self, kind, actor, detail, *, committed=False):
        self._armed = None
        try:
            self._refresh_quote()
        except Exception as error:
            # Mutations already happened, including durable consent/order commits.
            # Preserve them, but never claim a complete journal after lost capture.
            self._fault = self._fault or 'event capture failed: ' + str(error)
            raise
        if len(self._events) >= MAX_EVENTS:
            self._overflow = True
            return
        self._events.append({'seq': len(self._events) + 1, 'kind': kind, 'actor': actor,
                             'committed': committed, 'detail': deepcopy(detail),
                             'state': deepcopy(self._state)})

    def _overlay(self, basket, codes, delivery_option_id=None):
        """The overlay quote for an in-scope basket, else None (reason kept for the page)."""
        quote, scope = self._settings['quote'], self._settings['scope']
        self._scope_reason = None
        if quote is None or not basket:
            return None
        try:
            verdict = scope(deepcopy(basket), list(codes), delivery_option_id=delivery_option_id)
            if verdict['in_scope'] is not True:
                self._scope_reason = str(verdict.get('reason') or '') or None
                return None
            value = quote(deepcopy(basket), list(codes), delivery_option_id=delivery_option_id)
            return checked_overlay(value, codes, delivery_option_id)
        except Exception as error:  # A failing overlay must not take the shop down.
            self._overlay_errors.append(type(error).__name__ + ': ' + str(error))
            del self._overlay_errors[:-16]
            self._fault = self._fault or 'overlay producer failed: ' + str(error)
            self._scope_reason = 'The price for this basket is unavailable.'
            return None

    def _refresh_quote(self):
        state = self._state
        basket, codes = state['basket'], state['promotion_codes']
        state['quote'], self._quote_lines = None, []
        self._overlay_options = []
        self._shipping_summary = None
        if not basket:
            self._quote_reason = 'The basket is empty.'
            return
        overlay = self._overlay(basket, codes, state['delivery_option_id'])
        if overlay is not None:
            if 'promotion_codes' in overlay:
                state['promotion_codes'] = list(overlay['promotion_codes'])
            state['quote'] = {'source': 'overlay', 'quote_id': overlay['quote_id'],
                              'total_minor': overlay['total_minor'], 'currency': overlay['currency']}
            self._quote_lines = [{'label': str(line['label']), 'amount_minor': int(line['amount_minor'])}
                                 for line in overlay.get('lines') or []]
            self._overlay_options = [{key: row[key] for key in
                ('native_option_id', 'shipping_minor', 'total_minor')}
                for row in overlay.get('options') or []]
            self._shipping_summary = deepcopy(overlay.get('shipping_summary'))
            self._quote_reason = None
            return
        if self._settings['outside_scope_behavior'] == 'reject_quote':
            self._quote_reason = self._scope_reason or 'This basket is outside the offer. No offer quote is available.'
            return
        if codes:
            self._quote_reason = (self._scope_reason or 'Promotion codes do not apply to this basket.') \
                + ' Remove the codes to see the total.'
            return
        option = self._options.get(state['delivery_option_id'])
        if option is None or option['basket'] != basket:
            self._quote_reason = 'Choose delivery for this basket to see the total.'
            return
        state['quote'] = {'source': 'native', 'quote_id': None,
                          'total_minor': option['total_minor'], 'currency': 'SEK'}
        self._quote_reason = None

    def _charges(self):
        """One quote charge (fees are inside it) plus one charge per selected extra."""
        state, quote = self._state, self._state['quote']
        if quote is None:
            return None
        rows = [{'kind': 'quote', 'id': quote['quote_id'], 'label': 'Items and delivery',
                 'amount_minor': quote['total_minor']}]
        # A free-trial extra is still a committed selection but costs nothing today.
        rows += [{'kind': 'extra', 'id': extra['id'], 'label': extra['label'],
                  'amount_minor': 0 if extra.get('trial_days') else extra['price_minor']}
                 for extra in self._settings['extras'] if state['extras'][extra['id']]]
        return rows

    def _view(self):
        """What the page renders from; public values only."""
        state = self._state
        charges = self._charges()
        prominent = self._settings['delivery']['prominent']
        marked = []
        if prominent is not None:
            for option_id in self._latest_options:
                option = self._options.get(option_id)
                if option and (option_id == prominent.get('option_id')
                               or option['choice_ids'] == [prominent.get('choice_id')]):
                    marked.append(option_id)
        view = {'revision': len(self._setup_events) + len(self._events),
                'cookie': {'open': self._dialog_open, **deepcopy(state['cookie'])},
                'newsletter': state['newsletter'], 'extras': dict(state['extras']),
                'promotion_codes': list(state['promotion_codes']),
                'promotion_feedback': deepcopy(self._feedback),
                'delivery_option_id': state['delivery_option_id'],
                'prominent_option_ids': marked,
                'quote': deepcopy(state['quote']), 'quote_reason': self._quote_reason,
                'quote_lines': deepcopy(self._quote_lines), 'charges': charges,
                'overlay_options': deepcopy(self._overlay_options),
                'shipping_summary': deepcopy(self._shipping_summary),
                'grand_total_minor': None if charges is None else sum(row['amount_minor'] for row in charges),
                'checkout': deepcopy(state['checkout']), 'order': self._arm_reply,
                'directives': {'reset_delivery': self._reset_directive}}
        self._reset_directive = False
        self._arm_reply = None
        return view

    def _need(self, key):
        value = self._settings[key]
        if not value:
            raise ValueError('This shop has no such control')
        return value

    def _open_dialog(self, trigger):
        cookie, state = self._settings['cookie'], self._state['cookie']
        self._dialog_open = True
        self._event('cookie_dialog', 'site', {'shown': True, 'design': cookie['design']})
        if any(cookie['preselected'].values()) and cookie['preselected'] != state['preferences'] \
                and cookie['preselected'] != state['pending']:
            state['pending'] = dict(cookie['preselected'])
            self._event('site_preselect', 'site', {'field': 'cookie.pending',
                                                   'value': dict(cookie['preselected']), 'trigger': trigger})

    def _site_rules(self, trigger):
        """Selections the site makes by itself when the shopper reaches this point."""
        settings, state = self._settings, self._state
        recurrence = settings['recurrence']
        newsletter = settings['newsletter']
        initial = trigger == 'initial'
        if newsletter and not state['newsletter'] and (
                initial and newsletter['preselected'] == 'checkout' or trigger in recurrence['newsletter']):
            state['newsletter'] = True
            self._event('site_preselect', 'site', {'field': 'newsletter', 'value': True, 'trigger': trigger})
        for extra in settings['extras']:
            if not state['extras'][extra['id']] and (
                    initial and extra['preselected'] == 'checkout'
                    or trigger in recurrence['extras'].get(extra['id'], ())):
                state['extras'][extra['id']] = True
                self._event('site_preselect', 'site', {'field': 'extras', 'extra_id': extra['id'],
                                                       'value': True, 'trigger': trigger})
        if trigger in recurrence['cookie'] and not self._dialog_open:
            self._open_dialog(trigger)
        if trigger in recurrence['delivery']:
            if settings['presentation'].get('reset_once'):
                # Reset once, and only after the shopper actually chose a delivery.
                if not self._shopper_chose_delivery or self._reset_done:
                    return
                self._reset_done = True
            self._reset_trigger, self._reset_directive = trigger, True

    def _refresh_notice(self):
        """Shopper-facing text of a declared commit-time rate refresh, else None."""
        presentation = self._settings['presentation']
        if str(presentation.get('execution', '')).startswith('rate_refresh_at_commit') and self._settings['delivery']['default']:
            return presentation.get('refresh_notice') or 'The order total has changed. Review the updated total.'
        return None

    def _op_checkout_trigger(self, request):
        """Apply the site's declared silent side effect at its checkout trigger."""
        _fields(request, 'trigger')
        execution = self._settings['presentation'].get('consent_extras', {}).get('execution')
        trigger = request['trigger']
        if (execution in ('optin_with_terms', 'optin_with_terms_inline', 'optin_with_terms_announced',
                          'optin_with_terms_state', 'optin_with_terms_same_form') and trigger == 'terms'
                or execution == 'optin_with_address' and trigger == 'address_saved'):
            self._state['newsletter'] = True
            self._event('site_preselect', 'site', {'field': 'newsletter', 'value': True, 'trigger': trigger})
        elif execution in COUPLED_TRIGGERS and trigger == COUPLED_TRIGGERS[execution][0]:
            # Round 8: a required checkout tick also selects the opt-in or a paid extra.
            if COUPLED_TRIGGERS[execution][1] == 'newsletter':
                if not self._state['newsletter']:
                    self._state['newsletter'] = True
                    self._event('site_preselect', 'site', {'field': 'newsletter', 'value': True, 'trigger': trigger})
            else:
                extra_id = self._settings['extras'][0]['id']
                if not self._state['extras'][extra_id]:
                    self._state['extras'][extra_id] = True
                    self._event('site_preselect', 'site', {'field': 'extras', 'extra_id': extra_id,
                        'value': True, 'trigger': trigger})
        elif trigger == 'address_saved' and trigger in self._settings['recurrence']['newsletter']:
            # The order-review fragment re-renders with the server default after an address save.
            self._site_rules(trigger)
        elif execution == 'extra_with_terms' and trigger == 'terms':
            # Ticking the terms also selects the paid extra; the order total changes.
            extra_id = self._settings['extras'][0]['id']
            if not self._state['extras'][extra_id]:
                self._state['extras'][extra_id] = True
                self._event('site_preselect', 'site', {'field': 'extras', 'extra_id': extra_id,
                    'value': True, 'trigger': trigger})
        elif execution == 'extra_after_address' and trigger == 'address_saved':
            if not getattr(self, '_address_extra_shown', False):
                self._address_extra_shown = True
                extra_id = self._settings['extras'][0]['id']
                self._state['extras'][extra_id] = True
                self._event('site_preselect', 'site', {'field': 'extras', 'extra_id': extra_id,
                    'value': True, 'trigger': trigger})
        else:
            raise ValueError('No declared site rule for this checkout trigger')

    def _op_state(self, request):
        _fields(request)

    def _op_cookie_dialog(self, request):
        cookie = self._need('cookie')
        _fields(request, 'event')
        if request['event'] == 'load':
            if not self._state['cookie']['decided'] and not self._dialog_open:
                self._open_dialog('initial')
        elif request['event'] == 'dismiss':
            if not cookie['dismissible'] or not self._dialog_open:
                raise ValueError('This dialog cannot be closed without a choice')
            self._dialog_open = False
            self._state['cookie']['pending'] = None
            self._event('cookie_dialog', 'site', {'shown': False, 'design': cookie['design']})
        else:
            raise ValueError('Unknown cookie dialog event')

    def _op_cookie_save(self, request):
        self._need('cookie')
        action = request.get('action')
        if action not in COOKIE_SAVES:
            raise ValueError('Unknown consent action')
        if action == 'save_settings':
            _fields(request, 'action', 'preferences')
            chosen = request['preferences']
            if (type(chosen) is not dict or set(chosen) != set(PURPOSES)
                    or any(type(value) is not bool for value in chosen.values())):
                raise ValueError('Give a yes or no for every cookie purpose')
            chosen = {purpose: chosen[purpose] for purpose in PURPOSES}
        else:
            _fields(request, 'action')
            chosen = dict.fromkeys(PURPOSES, action == 'accept_all')
        if not self._dialog_open:
            raise ValueError('The consent dialog is not open')
        self._dialog_open = False
        self._state['cookie'] = {'decided': True, 'preferences': chosen, 'pending': None}
        self._state['committed']['cookie'] = {'decided': True, 'preferences': dict(chosen)}
        self._event('cookie_save', 'user', {'action': action}, committed=True)

    def _op_newsletter_set(self, request):
        self._need('newsletter')
        _fields(request, 'value')
        if type(request['value']) is not bool:
            raise ValueError('Newsletter value must be yes or no')
        if request['value'] != self._state['newsletter']:
            self._state['newsletter'] = request['value']
            self._event('newsletter_change', 'user', {'value': request['value']})

    def _op_extras_set(self, request):
        _fields(request, 'extra_id', 'value')
        extras = self._state['extras']
        if request['extra_id'] not in extras or type(request['value']) is not bool:
            raise ValueError('Unknown extra or value')
        if request['value'] != extras[request['extra_id']]:
            extras[request['extra_id']] = request['value']
            self._event('extras_change', 'user', {'extra_id': request['extra_id'], 'value': request['value']})

    def _op_promotion_apply(self, request):
        if not self._settings['promotions']['field']:
            raise ValueError('This shop has no promotion-code field')
        _fields(request, 'code')
        code = request['code']
        if type(code) is not str or not code.strip() or len(code) > 64 or code != code.strip():
            raise ValueError('Enter a promotion code')
        state = self._state
        accepted, feedback = False, 'This code is not valid in this shop.'
        if code in state['promotion_codes']:
            feedback = 'This code is already applied.'
        elif not state['basket']:
            feedback = 'Add an item before entering a code.'
        elif len(state['promotion_codes']) >= 8:
            feedback = 'No more codes can be added.'
        else:
            overlay = self._overlay(state['basket'], [*state['promotion_codes'], code],
                                    state['delivery_option_id'])
            if overlay is None:
                feedback = self._scope_reason or feedback
            else:
                verdict = (overlay.get('promotion_feedback') or {}).get(code) or {}
                accepted = verdict.get('accepted') is True
                feedback = str(verdict.get('feedback') or ('Code applied.' if accepted else feedback))
                if 'promotion_codes' in overlay:
                    state['promotion_codes'] = list(overlay['promotion_codes'])
        if accepted and code not in state['promotion_codes']:
            state['promotion_codes'].append(code)
        self._feedback = {'code': code, 'accepted': accepted, 'feedback': feedback}
        self._event('promotion_apply', 'user', dict(self._feedback))

    def _op_promotion_remove(self, request):
        _fields(request, 'code')
        codes = self._state['promotion_codes']
        if request['code'] not in codes:
            raise ValueError('That code is not applied')
        codes.remove(request['code'])
        self._feedback = None
        self._event('promotion_remove', 'user', {'code': request['code']})

    def _op_quote(self, request):
        _fields(request)

    def _op_order_arm(self, request):
        _fields(request, 'grand_total_minor')
        shown = request['grand_total_minor']
        if type(shown) is not int:
            raise ValueError('Supply the displayed order total')
        self._armed = None
        charges = self._charges()
        if charges is None or self._state['checkout']['location'] != 'checkout':
            self._arm_reply = {'armed': False, 'reason': self._quote_reason or 'Return to checkout to order.'}
        elif sum(row['amount_minor'] for row in charges) != shown:
            self._arm_reply = {'armed': False, 'reason': 'The order total has changed. Review the updated total.'}
        elif self._refresh_notice() is not None and not self._rate_refreshed:
            # Action-triggered rate refresh: the first confirmed total is refused and the
            # site's configured delivery default is selected for the shopper (reset directive).
            self._rate_refreshed = True
            self._reset_trigger, self._reset_directive = 'order_arm', True
            self._arm_reply = {'armed': False, 'reason': self._refresh_notice()}
        else:
            self._armed = {'charges': charges, 'grand_total_minor': shown}
            self._arm_reply = {'armed': True, 'reason': None}

    def _op_sync(self, request):
        _fields(request, 'basket', 'delivery', 'location', 'step')
        basket = basket_of(request['basket'])
        if len(basket) != len(request['basket']) or [line['offer_id'] for line in basket] != \
                [line['offer_id'] for line in request['basket']]:
            raise ValueError('Report one sorted basket line per offer')
        if any(set(line) != {'offer_id', 'quantity'} for line in request['basket']):
            raise ValueError('Basket lines carry an offer and a quantity only')
        unknown = [line['offer_id'] for line in basket if line['offer_id'] not in self._offers]
        if unknown:
            raise ValueError('Basket offer is not sold by this retailer')
        delivery, location, step = request['delivery'], request['location'], request['step']
        if (type(delivery) is not dict or set(delivery) != {'option_id', 'source'}
                or delivery['source'] not in ('shopper', 'site')):
            raise ValueError('Report the selected delivery option and who selected it')
        option_id = delivery['option_id']
        if option_id is not None:
            known = self._options.get(option_id) if type(option_id) is str else None
            if known is None or known['basket'] != basket:
                raise ValueError('Delivery option was not offered for this basket')
        if location not in ('outside', 'checkout') or (location == 'checkout' and not basket):
            raise ValueError('Report whether the shopper is at checkout with a basket')
        if step is not None and (type(step) is not int or not 1 <= step <= 9):
            raise ValueError('Checkout step must be a small number or null')

        state = self._state
        old = {line['offer_id']: line['quantity'] for line in state['basket']}
        new = {line['offer_id']: line['quantity'] for line in basket}
        changes = [('remove', offer, 0) for offer in sorted(old.keys() - new.keys())]
        changes += [('add' if offer not in old else 'set_quantity', offer, new[offer])
                    for offer in sorted(new) if old.get(offer) != new[offer]]
        for operation, offer, quantity in changes:
            current = {line['offer_id']: line['quantity'] for line in state['basket']}
            current.pop(offer, None)
            if quantity:
                current[offer] = quantity
            state['basket'] = [{'offer_id': key, 'quantity': current[key]} for key in sorted(current)]
            # A delivery option belongs to the basket it was quoted for.
            state['delivery_option_id'] = None
            self._event('basket_change', 'user', {'op': operation, 'offer_id': offer, 'quantity': quantity})
            if (operation == 'add' and self._settings['presentation'].get('consent_extras', {}).get('execution') == 'sneak_into_basket'
                    and not getattr(self, '_basket_extra_added', False)):
                self._basket_extra_added = True
                extra_id = self._settings['extras'][0]['id']
                state['extras'][extra_id] = True
                self._event('site_preselect', 'site', {'field': 'extras', 'extra_id': extra_id,
                    'value': True, 'trigger': 'add_to_cart'})

        if location != state['checkout']['location']:
            state['checkout']['location'] = location
            if location == 'checkout':
                trigger = 'checkout_return' if self._entered_checkout else 'initial'
                self._entered_checkout, self._step = True, step
                self._event('checkout_enter', 'user', {})
                self._site_rules(trigger)
            else:
                self._step = None
                self._event('checkout_leave', 'user', {})
        elif location == 'checkout' and step != self._step:
            self._step = step
            self._site_rules('checkout_navigation')

        if option_id is not None:
            changed = option_id != state['delivery_option_id']
            if changed:
                state['delivery_option_id'] = option_id
            if delivery['source'] == 'site':
                if changed:
                    self._event('site_preselect', 'site', {
                        'field': 'delivery_option_id', 'value': option_id,
                        'trigger': self._reset_trigger or 'initial'})
                self._reset_trigger = None
            elif changed:
                self._event('delivery_select', 'user', {'option_id': option_id})
                self._shopper_chose_delivery = True
                self._reset_trigger = None
                self._site_rules('delivery_select')

    _OPERATIONS = {'checkout_trigger': _op_checkout_trigger, 'state': _op_state, 'cookie_dialog': _op_cookie_dialog,
                   'cookie_save': _op_cookie_save, 'newsletter_set': _op_newsletter_set,
                   'extras_set': _op_extras_set, 'promotion_apply': _op_promotion_apply,
                   'promotion_remove': _op_promotion_remove, 'quote': _op_quote,
                   'order_arm': _op_order_arm, 'sync': _op_sync}
