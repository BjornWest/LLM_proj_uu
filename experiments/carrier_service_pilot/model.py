"""Policies -> timestamped histories -> applicable opinions, with separate exports."""
from collections import Counter
from datetime import datetime, timedelta, time
import math
from zoneinfo import ZoneInfo

from environments.product_world.areas import city_areas
from experiments.address_checkout_pilot.model import generate as address_world, digest
from experiments.carrier_location_pilot.model import accessible_at, rng
from .prose import combine, statement

VERSION = 'carrier-service-evidence-v1'
DEFAULTS = {'shipments_per_carrier': 64, 'text_probability': .25,
            'detailed_tracking_probability': .7, 'dispatch_notice_probability': .7,
            'delivery_day_notice_probability': .7, 'approaching_notice_probability': .4,
            'failed_attempt_notice_probability': .8}
ASPECTS = ('punctuality', 'handling', 'handoff', 'communication')
REVIEWERS = ('Alex', 'Robin', 'Sam', 'Kim', 'Lou', 'Charlie', 'Jamie', 'Morgan', 'Lee', 'Casey', 'Noor', 'Taylor')


def config(options=None):
    if options is not None and (not isinstance(options, dict) or set(options) - set(DEFAULTS)):
        raise ValueError('Unknown carrier sampling parameter')
    c = {**DEFAULTS, **(options or {})}
    if type(c['shipments_per_carrier']) is not int or not 8 <= c['shipments_per_carrier'] <= 256:
        raise ValueError('Shipments per carrier must be an integer between 8 and 256')
    if any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1
           for k, v in c.items() if k != 'shipments_per_carrier'):
        raise ValueError('Probabilities must be finite numbers between zero and one')
    return c


def stamp(day, hour, zone):
    return datetime.combine(day, time(hour), tzinfo=ZoneInfo(zone))


def observation(aspect, sentiment, pool, ids, **slots):
    return {'aspect': aspect, 'sentiment': sentiment, 'pool': pool, 'evidence_ids': ids, 'slots': slots}


def policy(base, carrier, cfg):
    seed, cid = base['seed'], carrier['carrier_id']
    r = rng(seed, VERSION + '/policy/' + cid)
    detailed = r.random() < cfg['detailed_tracking_probability']
    notices = {'dispatch': r.random() < cfg['dispatch_notice_probability'],
               'delivery_day': r.random() < cfg['delivery_day_notice_probability'],
               'approaching': r.random() < cfg['approaching_notice_probability'],
               'failed_attempt': r.random() < cfg['failed_attempt_notice_probability']}
    result = {'carrier_id': cid, 'name': carrier['name'],
              'tracking': {'level': 'detailed' if detailed else 'basic',
                           'promised_events': ['received', 'delivered', 'ready_for_collection', 'collected'] +
                            (['in_transit', 'out_for_delivery', 'failed_attempt'] if detailed else []),
                           'maximum_update_delay_minutes': 60},
              'notifications': {'channel': r.choices(['email', 'sms', 'email_and_sms'], [.4, .35, .25])[0],
                                'offered': notices,
                                'timing': {'dispatch': 'Within 60 minutes of carrier handover.',
                                           'delivery_day': 'By 08:00 on the home-delivery day, before the attempt.',
                                           'approaching': 'At least 30 minutes before a home-delivery attempt.',
                                           'failed_attempt': 'Within 30 minutes of a failed home-delivery attempt.'}},
              'collection_point_ids': carrier['collection_point_ids'], 'services': [],
              'terms': ['Building entry, when resolved, means delivery to the apartment door.',
                        'Unattended leaving requires explicit recipient permission and compatible building entry.',
                        'Date-only services do not promise a clock-time window.',
                        'Collection access hours are separate from parcel readiness.']}
    for source in (s for s in base['services'] if s['carrier_id'] == cid):
        sr = rng(seed, VERSION + '/fallback/' + source['service_id'])
        fallback = 'redirect_to_collection' if source['shipping_class'] == 'regular' and carrier['collection_point_ids'] and sr.random() < .3 else 'reattempt'
        result['services'].append({'service_id': source['service_id'], 'shipping_class': source['shipping_class'],
            'scheduling': source['scheduling'], 'evening_windows': source['evening_windows'] and source['scheduling'] == 'choose_day_and_window',
            'unattended_allowed': source['unattended_allowed'], 'failed_delivery_policy': fallback,
            'fallback_readiness_days': 1,
            'notifications': {k: v for k, v in notices.items()},
            'notification_scope': 'Dispatch applies after handover; other notices only for home delivery and their triggering event.'})
    channel = result['notifications']['channel'].replace('_and_', ' and ').replace('sms', 'SMS')
    result['policy_text'] = [
        ('Detailed tracking shows handover, transit, delivery progress and completion.' if detailed else
         'Basic tracking shows carrier handover and delivery or collection readiness/completion.'),
        'Promised tracking events are published within 60 minutes.',
        f'Notifications use {channel}. Contact details must be supplied for these messages.',
        *[f"{k.replace('_', ' ').capitalize()} notification: {result['notifications']['timing'][k]}" for k, v in notices.items() if v],
        *[f"No {k.replace('_', ' ')} notification is offered." for k, v in notices.items() if not v],
        'Delivery-day, approaching-driver and failed-attempt notices apply to home delivery, when the event occurs.',
        *result['terms']]
    return result


def history(base, pol, levels, index, rates):
    cid, seed = pol['carrier_id'], base['seed']
    hid = f'{cid}-shipment-{index:04d}'
    r = rng(seed, VERSION + '/history/' + hid)
    service = pol['services'][0 if r.random() < .7 else 1]
    source = next(s for s in base['services'] if s['service_id'] == service['service_id'])
    points = [p for p in base['collection_points'] if p['point_id'] in pol['collection_point_ids']]
    collection = service['shipping_class'] == 'regular' and bool(points) and r.random() < .25
    selected_point = r.choice(points) if collection else None
    zone = base['city']['timezone']
    start = datetime.fromisoformat(base['quote_as_of']).date() - timedelta(days=r.randint(10, 90))
    planned_handover = stamp(start, 9, zone)
    retailer_delay = r.choice((1, 2)) if r.random() < .15 else 0
    actual_handover = planned_handover + timedelta(days=retailer_delay)
    transit_days = max(1, 1 + source['transit_offset_days']) + (service['shipping_class'] == 'bulky')
    choice_offset = r.randrange(3) if not collection and service['scheduling'] != 'carrier_assigned' else 0
    expected = actual_handover.date() + timedelta(days=transit_days + choice_offset)
    retailer_expected = planned_handover.date() + timedelta(days=transit_days + choice_offset)
    promised_window = None
    if not collection and service['scheduling'] == 'choose_day_and_window':
        promised_window = r.choice([(8, 12), (12, 16)] + ([(16, 20)] if service['evening_windows'] else []))
    on_day = r.random() < rates['arrival_on_promised_day'][levels['punctuality']]
    late_days = 0 if on_day else r.randint(1, 3)
    inside = on_day and r.random() < rates['within_promised_window_given_right_day'][levels['punctuality']] if promised_window else None
    hour = (sum(promised_window) // 2 if inside else r.choice((7, 21))) if promised_window else 12
    first = stamp(expected + timedelta(days=late_days), hour, zone)
    present = r.random() < .9
    permission = service['unattended_allowed'] and r.random() < .5
    # Histories represent different past customers/buildings, not many reviewers of the current user's apartment.
    mode = r.choices(['recipient_opens', 'provided_code_or_intercom', 'authorised_access'], [.4, .35, .25])[0]
    code_provided = r.random() < .8
    entry = mode == 'authorised_access' or present or (mode == 'provided_code_or_intercom' and code_provided)
    presence_ok = present or permission
    failed = not collection and not (entry and presence_ok)
    complied = None if collection or failed else r.random() < rates['promised_handoff_complied_with'][levels['handoff']]
    actual_place = 'collection' if collection else 'no_handoff' if failed else 'apartment_door' if complied else 'lobby'
    fallback = service['failed_delivery_policy'] if failed else None
    receipt = first
    ready = first if collection else None
    if failed:
        receipt = first + timedelta(days=1)
        if fallback == 'redirect_to_collection':
            selected_point = r.choice(points)
            actual_place = 'collection'
            ready = receipt
        else:
            actual_place = 'apartment_door'
    if selected_point:
        ready = ready or first
        receipt = ready + timedelta(days=r.randrange(2))
        # Point opening hours/user collection can affect receipt; they do not alter carrier ready time.
        for _ in range(24 * 8):
            if accessible_at(selected_point, receipt):
                break
            receipt += timedelta(hours=1)
        else:
            raise ValueError('No collection access within the bounded history horizon')
    intact = r.random() < rates['parcel_intact'][levels['handling']]
    condition = 'intact' if intact else r.choice(('crushed', 'wet', 'torn'))
    events = []
    def event(kind, timestamp, **extra):
        eid = hid + '-event-' + str(len(events) + 1)
        events.append({'event_id': eid, 'kind': kind, 'at': timestamp.isoformat(), **extra})
        return eid
    received_id = event('received', actual_handover, condition='intact')
    transit_id = event('in_transit', actual_handover + timedelta(minutes=30))
    day_started_id = event('delivery_day_started', stamp(first.date(), 0, zone)) if not collection else None
    leaving_id = event('out_for_delivery', first - timedelta(hours=1)) if not collection else None
    first_id = event('ready_for_collection' if collection else 'failed_attempt' if failed else 'delivery_attempt', first,
                     handoff=actual_place if not failed else 'no_handoff')
    if failed:
        event('fallback_ready' if fallback == 'redirect_to_collection' else 'reattempt', first + timedelta(days=1),
              recipient_available=True, building_entry_resolved=True)
    final_id = event('collected' if selected_point else 'delivered', receipt, handoff=actual_place, condition=condition)
    comm_probability = rates['communication_promise_met'][levels['communication']]
    tracking_good = r.random() < comm_probability
    tracking_failure = None if tracking_good else 'false_attempt' if pol['tracking']['level'] == 'detailed' and not collection and not failed and present and r.random() < .4 else 'stale'
    tracking_events = []
    for e in events:
        if e['kind'] not in pol['tracking']['promised_events']:
            continue
        timestamp = datetime.fromisoformat(e['at'])
        publish = timestamp + timedelta(minutes=r.randrange(0, 61)) if tracking_good or e['kind'] == 'received' else max(timestamp + timedelta(minutes=61), receipt + timedelta(days=1))
        tracking_events.append({'kind': e['kind'], 'occurred_at': e['at'], 'published_at': publish.isoformat(),
                                'source_event_id': e['event_id'], 'truthful': True})
    false_id = None
    if tracking_failure == 'false_attempt':
        false_time = first - timedelta(minutes=30)
        false_id = hid + '-false-scan'
        tracking_events.append({'kind': 'failed_attempt', 'occurred_at': false_time.isoformat(),
                                'published_at': false_time.isoformat(), 'source_event_id': None,
                                'tracking_id': false_id, 'truthful': False})
    notices = []
    for kind, offered in service['notifications'].items():
        if not offered or (kind != 'dispatch' and collection) or (kind == 'failed_attempt' and not failed):
            continue
        trigger = received_id if kind == 'dispatch' else first_id if kind == 'failed_attempt' else day_started_id if kind == 'delivery_day' else leaving_id
        due = actual_handover + timedelta(hours=1) if kind == 'dispatch' else first + timedelta(minutes=30) if kind == 'failed_attempt' else first - timedelta(minutes=30) if kind == 'approaching' else min(stamp(first.date(), 8, zone), first - timedelta(minutes=30))
        good = r.random() < comm_probability
        failure = None if good else r.choice(('missing', 'late'))
        sent = due - timedelta(minutes=5) if good else None if failure == 'missing' else (actual_handover + timedelta(hours=2) if kind == 'dispatch' else first + timedelta(hours=2))
        notices.append({'notification_id': hid + '-notice-' + kind, 'kind': kind, 'promised': True,
                        'channel': pol['notifications']['channel'], 'trigger_event_id': trigger,
                        'due_at': due.isoformat(), 'sent_at': sent.isoformat() if sent else None,
                        'outcome': 'met' if good else failure})
    observations = []
    if not failed and not collection:
        observations.append(observation('punctuality', 'positive' if on_day else 'negative', 'punctuality', [first_id],
                          late_days=late_days, late_duration='a day' if late_days == 1 else f'{late_days} days'))
        if promised_window:
            observations.append(observation('window', 'positive' if inside else 'negative', 'window', [first_id],
                                window=f'{promised_window[0]:02}:00–{promised_window[1]:02}:00'))
        observations.append(observation('handoff', 'positive' if complied else 'negative', 'handoff', [first_id]))
    observations.append(observation('handling', 'positive' if intact else 'negative', 'handling', [received_id, final_id], condition=condition))
    observations.append(observation('tracking', 'positive' if tracking_good else 'negative', 'tracking' if tracking_good else 'tracking_false_attempt' if tracking_failure == 'false_attempt' else 'tracking_stale',
                        [received_id, final_id] + ([false_id] if false_id else [])))
    for n in notices:
        observations.append(observation('notification_' + n['kind'], 'positive' if n['outcome'] == 'met' else 'negative',
                            'notification' if n['outcome'] == 'met' else 'notification_' + n['outcome'], [n['notification_id']],
                            notification=n['kind'].replace('_', '-')))
    if selected_point:
        host = {'fuel_station': 'the petrol station', 'grocery_store': 'the grocery shop',
                'convenience_store': 'the corner shop', 'parcel_locker': 'the lockers'}[selected_point['host_type']]
        point_location = selected_point['location']
        area = min(city_areas(base['city']), key=lambda a: (a['east_km'] - point_location['local_east_km']) ** 2 +
                    (a['north_km'] - point_location['local_north_km']) ** 2)
        reference = host + ' in ' + area['name']
        observations.append(observation('collection', 'neutral', 'fallback_collection' if failed else 'collection',
                            [first_id, final_id], point_name=reference))
        if selected_point['access_24_7']:
            observations.append(observation('locker', 'positive', 'locker', [final_id]))
    elif failed:
        observations.append(observation('fallback', 'neutral', 'fallback_retry', [first_id, final_id]))
    return {'shipment_id': hid, 'carrier_id': cid, 'service_id': service['service_id'], 'shipping_class': service['shipping_class'],
            'destination_type': 'collection' if collection else 'home', 'timezone': zone,
            'historical_building_context_id': hid + '-building' if not collection else None,
            'planned_handover_at': planned_handover.isoformat(), 'actual_handover_at': actual_handover.isoformat(),
            'retailer_original_estimated_day': retailer_expected.isoformat(),
            'carrier_promised_day': expected.isoformat(),
            'window_booked_after_handover': bool(promised_window), 'promised_window_hours': promised_window,
            'first_attempt_at': first.isoformat(), 'receipt_at': receipt.isoformat(),
            'parcel_ready_at': ready.isoformat() if ready else None,
            'first_attempt_on_promised_day': on_day, 'first_attempt_inside_window': inside,
            'retailer_end_to_end_late': receipt.date() > retailer_expected,
            'recipient_present': present, 'unattended_permission': permission, 'code_provided': code_provided,
            'building_entry_mode': mode, 'building_entry_resolved': entry, 'handoff_complied': complied,
            'failed_first_attempt': failed, 'fallback': fallback,
            'parcel_condition': condition, 'events': sorted(events, key=lambda e: e['at']),
            'tracking': tracking_events, 'tracking_outcome': 'met' if tracking_good else tracking_failure,
            'notifications': notices, 'observations': observations}


def stars(observations, r):
    # One communication group and one day/window group prevent many notices or coupled facts dominating ratings.
    groups = {}
    for o in observations:
        if o['sentiment'] == 'neutral' or o['aspect'] == 'locker':
            continue
        group = 'timeliness' if o['aspect'] in ('window', 'punctuality') else 'communication' if o['aspect'] == 'tracking' or o['aspect'].startswith('notification_') else o['aspect']
        groups.setdefault(group, []).append(o['sentiment'] == 'positive')
    total_weight = sum(2 if group == 'timeliness' else 1 for group in groups)
    positive = sum((2 if group == 'timeliness' else 1) * sum(values)/len(values)
                   for group, values in groups.items()) / total_weight if total_weight else .5
    p = .1 + .8 * positive
    latent = r.betavariate(p * 1.5, (1 - p) * 1.5)
    return 1 + sum(r.random() < latent for _ in range(4))


def summaries(histories, reviews):
    metrics = {}
    predicates = {
        'promised_day_attempts': lambda h: h['first_attempt_on_promised_day'],
        'promised_window_attempts': lambda h: h['first_attempt_inside_window'],
        'apartment_door_handoffs': lambda h: h['handoff_complied'],
        'intact_parcels': lambda h: h['parcel_condition'] == 'intact',
        'accurate_timely_tracking': lambda h: h['tracking_outcome'] == 'met'}
    for name, getter in predicates.items():
        values = [getter(h) for h in histories if getter(h) is not None]
        metrics[name] = {'successes': sum(values), 'failures': len(values)-sum(values), 'eligible_shipments': len(values),
                         'success_fraction': sum(values)/len(values) if values else None}
    rating_counts = Counter(r['stars'] for r in reviews)
    claims = {}
    for review in reviews:
        for claim in review['statements']:
            entry = claims.setdefault(claim['aspect'], {'positive': set(), 'negative': set(), 'neutral': set()})
            entry[claim['sentiment']].add(review['reviewer_id'])
    public_claims = {aspect: {**{k: len(v) for k, v in counts.items()},
                              'mentioned_reviewers': len(set().union(*counts.values()))}
                     for aspect, counts in claims.items()}
    return {'shipment_count': len(histories), 'rating_count': len(reviews),
            'text_review_count': sum(r['text'] is not None for r in reviews),
            'rating_counts': {str(n): rating_counts[n] for n in range(1, 6)},
            'average_stars': round(sum(r['stars'] for r in reviews)/len(reviews), 2),
            'metrics': metrics, 'written_review_claim_counts': public_claims,
            'scope': 'Generated historical sample, not a future delivery guarantee. Day/window metrics refer to attempts; handoff excludes failed attempts and collection. Each shipment/reviewer counted once.'}


def generate(seed=0, city_id='uppsala', options=None):
    cfg = config(options)
    base = address_world(seed, city_id)
    import json
    from experiments.address_checkout_pilot.model import PLAN
    plan = json.loads(PLAN.read_text())
    experience = plan['carrier_review_backlog']['experience_sampling_proposal']
    level_weights = experience['aspect_level_probabilities']
    rates = experience['success_probabilities_by_aspect_level']
    policies, histories, reviews, private = [], [], [], []
    uses = {}
    for carrier in base['carriers']:
        pol = policy(base, carrier, cfg)
        policies.append(pol)
        cid = carrier['carrier_id']
        levels = {aspect: rng(seed, VERSION + '/quality/' + cid + '/' + aspect).choices(list(level_weights), list(level_weights.values()))[0]
                  for aspect in ASPECTS}
        private.append({'carrier_id': cid, 'aspect_levels': levels})
        for i in range(cfg['shipments_per_carrier']):
            h = history(base, pol, levels, i, rates)
            histories.append(h)
            r = rng(seed, VERSION + '/review/' + h['shipment_id'])
            statements = []
            if r.random() < cfg['text_probability']:
                count = min(len(h['observations']), r.choices([1, 2, 3, 4], [.4, .35, .2, .05])[0])
                # Group notifications so adding channels does not swamp punctuality/handling.
                available = {o['aspect']: o for o in h['observations']}
                chosen = []
                for _ in range(count):
                    weights = [2 if k == 'punctuality' else .35 if k.startswith('notification_') else 1 for k in available]
                    key = r.choices(list(available), weights)[0]
                    chosen.append(available.pop(key))
                r.shuffle(chosen)
                statements = [statement(o, r, uses) for o in chosen]
            rating = stars(h['observations'], r)
            signs = {s['sentiment'] for s in statements} - {'neutral'}
            if signs == {'positive'}:
                rating = max(3, rating)
            elif signs == {'negative'}:
                rating = min(3, rating)
            elif 'negative' in signs:
                rating = min(4, rating)
            reviews.append({'review_id': h['shipment_id'] + '-review', 'reviewer_id': h['shipment_id'] + '-person',
                            'reviewer_name': r.choice(REVIEWERS), 'shipment_id': h['shipment_id'], 'carrier_id': cid,
                            'service_id': h['service_id'], 'shipping_class': h['shipping_class'],
                            'date': datetime.fromisoformat(h['receipt_at']).date().isoformat(), 'stars': rating,
                            'statements': statements, 'text': combine(statements, r) if statements else None})
    for pol in policies:
        summary = summaries([h for h in histories if h['carrier_id'] == pol['carrier_id']],
                            [r for r in reviews if r['carrier_id'] == pol['carrier_id']])
        private_row = next(p for p in private if p['carrier_id'] == pol['carrier_id'])
        private_row['observed_history_metrics'] = summary['metrics']
        pol['summary'] = {k: v for k, v in summary.items() if k not in ('metrics', 'shipment_count')}
        pol['summary']['scope'] = 'Ratings include textless reviews; aspect counts use written statements only, deduplicated by reviewer. No claims are inferred from stars or private shipment facts.'
    binding = {'schema_version': VERSION, 'seed': seed, 'city_id': city_id, 'parameters': cfg,
               'source_address_world_id': base['world_id'], 'policies': policies, 'histories': histories, 'reviews': reviews}
    corpus_id = digest(binding)
    public_reviews = [{k: v for k, v in review.items() if k not in ('statements', 'shipment_id')} for review in reviews]
    return {'schema_version': VERSION, 'corpus_id': corpus_id, 'seed': seed, 'city': base['city'], 'parameters': cfg,
            'public': {'corpus_id': corpus_id, 'carriers': policies, 'reviews': public_reviews,
                       'collection_points': base['collection_points']},
            'private': {'corpus_id': corpus_id, 'carrier_parameters': private, 'shipments': histories,
                        'reviews': reviews, 'source_address_world_id': base['world_id'],
                        'source_plan_sha256': base['provenance']['plan_sha256']},
            'limitations': ['Isolated authoring corpus, not connected-world renderer/task/grader integration.',
                            'Notification capabilities/participation defaults are prototype proposals.',
                            'Completed historical shipments only; one fallback attempt, no return-to-sender lifecycle.',
                            'Fictional shipment sample; probabilities are not empirical carrier estimates.',
                            'Retailer dispatch delays are distinguished in histories; retailer reviews are not generated here.']}
