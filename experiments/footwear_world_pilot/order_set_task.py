"""Opt-in native requests, authoritative matching and exact reference packets.

The original producer task and reference remain unchanged. Requests are authored
before sampling; matching never drops sold-out offers or invents public facts.
"""
from copy import deepcopy
from datetime import date
from hashlib import sha256
from pathlib import Path

from environments.product_world import footwear_context_pilot as footwear
from environments.website_world import checkout_domain
from . import model, basket_quote, order_set_optimizer

VERSION = 'native-order-set-task-v1'
OBJECTIVE = 'min_total_payable_order_set'


class UnsupportedTask(ValueError):
    """Unsupported semantics, distinct from a valid request with zero matches."""


def vocabulary():
    spec = footwear.load_spec()
    fields = {}
    def register(key, values):
        values = list(values)
        kind = type(values[0]).__name__
        if any(type(v).__name__ != kind for v in values):
            raise ValueError('Mixed authoring scalar vocabulary')
        fields[key] = {'type': kind, 'values': sorted(set(values)),
            'applicable_concepts':sorted(c['registry_id'] for c in spec['concepts'].values())}
    fixed = {}
    for concept in spec['concepts'].values():
        for key, value in concept['fixed'].items():
            fixed.setdefault(key, []).append(value)
    for key, values in fixed.items():
        register(key, values)
        fields[key]['applicable_concepts']=sorted(c['registry_id'] for c in spec['concepts'].values() if key in c['fixed'])
    for key in next(iter(spec['construction_packages'].values())):
        register(key, [p[key] for p in spec['construction_packages'].values()])
    register('fastening', [v for c in spec['concepts'].values() for v in c['fastening_weights']])
    register('sole_tread', spec['tread_weights'])
    return {'schema_version': 'native-order-set-vocabulary-v1',
        'authoring_spec_sha256': model.digest(spec),
        'concept_ids': sorted(c['registry_id'] for c in spec['concepts'].values()),
        'sizes_eu': deepcopy(spec['sizes_eu']),
        'widths': sorted({w for ws in spec['width_sets'].values() for w in ws}),
        'facts': fields,
        'limitations': ['Only listed exact scalar public predicates; no gender, nested materials, mass or review predicates.']}


def validate(request):
    if (type(request) is not dict or set(request) != {'schema_version','objective','requirements','domain'} or
            request['schema_version'] != VERSION or request['objective'] != OBJECTIVE):
        raise UnsupportedTask('Unsupported native order-set task schema/objective')
    rows = request['requirements']; vocab = vocabulary(); ids = set()
    if type(rows) is not list or not rows:
        raise UnsupportedTask('Supply a nonempty requirement list')
    for row in rows:
        if type(row) is not dict or not {'requirement_id','quantity','concept_id','size_eu'} <= set(row) or set(row)-{'requirement_id','quantity','concept_id','size_eu','width','facts'}:
            raise UnsupportedTask('Unknown or missing requirement field')
        key = row['requirement_id']
        if type(key) is not str or not key.strip() or key in ids:
            raise UnsupportedTask('Requirement IDs must be unique nonempty strings')
        ids.add(key)
        if type(row['quantity']) is not int or row['quantity'] < 1:
            raise UnsupportedTask('Quantity must be a positive exact integer')
        if row['concept_id'] not in vocab['concept_ids'] or type(row['size_eu']) is not int or row['size_eu'] not in vocab['sizes_eu']:
            raise UnsupportedTask('Unsupported concept or EU size')
        if 'width' in row and (type(row['width']) is not str or row['width'] not in vocab['widths']):
            raise UnsupportedTask('Unsupported width')
        facts = row.get('facts', {})
        if type(facts) is not dict or set(facts)-set(vocab['facts']):
            raise UnsupportedTask('Unsupported public fact predicate')
        for key, value in facts.items():
            field = vocab['facts'][key]
            if type(value).__name__ != field['type'] or value not in field['values']:
                raise UnsupportedTask('Unsupported typed fact value: '+key)
    domain = request['domain']
    if type(domain) is not dict or set(domain)-{'destination','allowed_destination_types','deadline','allow_extras'} or domain.get('destination') != 'user_home':
        raise UnsupportedTask('Only the generated user-home destination is supported')
    allowed = domain.get('allowed_destination_types', ['home','parcel_locker','staffed_counter','retailer_branch'])
    if (type(allowed) is not list or not allowed or any(type(v) is not str or v not in ('home','parcel_locker','staffed_counter','retailer_branch') for v in allowed) or len(allowed)!=len(set(allowed))):
        raise UnsupportedTask('Unsupported destination types')
    deadline = domain.get('deadline')
    try:
        if deadline is not None and (type(deadline) is not str or date.fromisoformat(deadline).isoformat()!=deadline):
            raise ValueError()
    except ValueError as exc: raise UnsupportedTask('Deadline must be an ISO date or null') from exc
    if type(domain.get('allow_extras', True)) is not bool:
        raise UnsupportedTask('Extras policy must be boolean')
    value = deepcopy(request)
    value['domain'] = {'destination':'user_home','allowed_destination_types':sorted(allowed),
                       'deadline':deadline,'allow_extras':domain.get('allow_extras',True)}
    return value


def match(world, request):
    task = validate(request)
    products = {}
    skus = {}
    for product in world['products']:
        public = product['public']; pid = public['product_id']
        if pid in products: raise ValueError('Duplicate product identity')
        products[pid] = public
        for sku in public['skus']:
            sid = sku['sku_id']
            if sid in skus or sku['product_id'] != pid: raise ValueError('Invalid manufactured SKU join')
            skus[sid] = sku
    matches = {r['requirement_id']: [] for r in task['requirements']}
    seen = set(); fact_fields=vocabulary()['facts']
    for retailer in world['retailers']:
        for offer in retailer['offers']:
            oid = offer['offer_id']; pid = offer['product_id']; sid = offer['sku_id']
            if oid in seen or pid not in products or sid not in skus or skus[sid]['product_id']!=pid:
                raise ValueError('Invalid retailer offer/product/SKU join')
            seen.add(oid); product = products[pid]; sku = skus[sid]
            for row in task['requirements']:
                if product['concept_id'] != row['concept_id'] or type(sku['size_eu']) is not int or sku['size_eu'] != row['size_eu']: continue
                if 'width' in row and sku['width'] != row['width']: continue
                if any(product['concept_id'] not in fact_fields[key]['applicable_concepts'] or key not in product['facts'] or type(product['facts'][key]) is not type(value) or product['facts'][key] != value for key,value in row.get('facts',{}).items()): continue
                matches[row['requirement_id']].append(oid)
    rows = [{'requirement_id':r['requirement_id'],'quantity':r['quantity'],
             'offer_ids':sorted(matches[r['requirement_id']])} for r in task['requirements']]
    return {'schema_version':'native-order-set-matching-v1','world_id':world['world_id'],
        'world_sha256':model.digest(world),'task_sha256':model.digest(task),
        'vocabulary_sha256':model.digest(vocabulary()),'requirements':rows}


def source_identity(admission_plan=None):
    # The generation manifest additionally pins the complete imported closure.
    paths = [Path(__file__), Path(__file__).with_name('order_set_grader.py'),
             Path(order_set_optimizer.__file__), Path(basket_quote.__file__),
             Path(model.__file__), Path(checkout_domain.__file__),
             Path(__file__).with_name('coupon_quote.py')]
    if admission_plan is not None:
        from experiments.accepted_catalog_commerce import delivery_admission
        paths.append(Path(delivery_admission.__file__))
    return {p.name:sha256(p.read_bytes()).hexdigest() for p in paths}


def reference(world, request, *, plan, domain, coupon_plan=None, budget=None, max_solutions=100, admission_plan=None):
    task = validate(request); matching = match(world,task)
    domain_id = checkout_domain.validate(world,domain)
    result = order_set_optimizer.solve(world,matching['requirements'],plan=plan,coupon_plan=coupon_plan,
        destination=world['user_location'],allowed_destination_types=task['domain']['allowed_destination_types'],
        deadline=task['domain']['deadline'],allow_extras=task['domain']['allow_extras'],
        quantity_limits=domain['quantity_limits'],max_lines_per_order=domain['options']['max_lines_per_order'],
        budget=budget,max_solutions=max_solutions,admission_plan=admission_plan)
    return {'schema_version':'native-order-set-reference-v1','task_sha256':model.digest(task),
        'matching_sha256':model.digest(matching),'checkout_domain_sha256':domain_id,
        'vocabulary_sha256':model.digest(vocabulary()),'source_sha256':source_identity(admission_plan),
        'result_sha256':model.digest(result),'result':result}


def user_message(request):
    task = validate(request); descriptions=[]
    for r in task['requirements']:
        text=f"{r['quantity']} pair(s) of {r['concept_id'].split('.')[-1].replace('_',' ')}, EU {r['size_eu']}"
        if 'width' in r:text+=', '+r['width']+' width'
        if r.get('facts'):text+='; '+', '.join(k.replace('_',' ')+' = '+str(v) for k,v in r['facts'].items())
        descriptions.append(text)
    d=task['domain']
    text='Find the cheapest order or set of orders that obtains '+ ' and '.join(descriptions)+', including all shipping and applicable discounts.'
    text+=' Separate orders at the same shop or different shops are allowed.'
    text+=(' Additional items are allowed if they lower the final cost.' if d['allow_extras'] else ' Do not buy additional items.')
    text+=' Allowed delivery types: '+', '.join(d['allowed_destination_types'])+'.'
    if d['deadline']:text+=' All items must arrive by '+d['deadline']+'.'
    return text+' Report quantities, every retailer product/variant link, delivery choices and the complete payable total. Inspect checkout without completing a purchase.'
