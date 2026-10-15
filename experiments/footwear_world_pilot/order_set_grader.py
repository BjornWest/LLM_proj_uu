"""Read-only structured plan grading; no prose extraction or purchase grading."""
from collections import defaultdict, deque
from copy import deepcopy
from urllib.parse import urlsplit, parse_qsl

from environments.website_world import checkout_domain
from . import model, basket_quote, order_set_task
from experiments import source_binding

VERSION = 'native-order-set-response-v1'


class InvalidPlan(ValueError):
    pass


def coverage(requirements, purchased):
    """Integer max-flow; an overlapping purchased unit is allocated only once."""
    residual = defaultdict(dict)
    def edge(a,b,n):
        residual[a][b] = n
        residual[b].setdefault(a,0)
    source=('source',); sink=('sink',)
    demand=sum(r['quantity'] for r in requirements)
    for oid, quantity in purchased.items():edge(source,('offer',oid),quantity)
    for r in requirements:
        rn=('requirement',r['requirement_id']);edge(rn,sink,r['quantity'])
        for oid in r['offer_ids']:
            if oid in purchased:edge(('offer',oid),rn,demand)
    flow=0
    while True:
        parent={source:None}; queue=deque([source])
        while queue and sink not in parent:
            a=queue.popleft()
            for b,n in residual[a].items():
                if n>0 and b not in parent:parent[b]=a;queue.append(b)
        if sink not in parent:break
        amount=demand;node=sink
        while parent[node] is not None:
            prev=parent[node];amount=min(amount,residual[prev][node]);node=prev
        node=sink
        while parent[node] is not None:
            prev=parent[node];residual[prev][node]-=amount;residual[node][prev]+=amount;node=prev
        flow+=amount
    allocations=[]
    for r in requirements:
        rn=('requirement',r['requirement_id'])
        for oid in r['offer_ids']:
            n=residual[rn].get(('offer',oid),0)
            if n:allocations.append({'requirement_id':r['requirement_id'],'offer_id':oid,'quantity':n})
    return {'covered':flow==demand,'required_units':demand,'allocated_units':flow,'allocations':allocations}


def _bound(world,task,reference,plan,domain,coupon_plan,admission_plan=None):
    domain_id=checkout_domain.validate(world,domain)
    matching=order_set_task.match(world,task)
    if (type(reference) is not dict or reference.get('schema_version')!='native-order-set-reference-v1' or
            reference.get('task_sha256')!=model.digest(task) or reference.get('matching_sha256')!=model.digest(matching) or
            reference.get('checkout_domain_sha256')!=domain_id or
            reference.get('vocabulary_sha256')!=model.digest(order_set_task.vocabulary()) or
            not source_binding.same_code(reference.get('source_sha256'),order_set_task.source_identity(admission_plan))):
        raise ValueError('Stale or unsupported task/matching/domain/source reference binding')
    result=reference.get('result',{})
    if (reference.get('result_sha256')!=model.digest(result) or not result.get('complete') or
            result.get('status') not in ('optimal','infeasible') or
            result.get('world_id')!=world['world_id'] or result.get('world_sha256')!=model.digest(world) or
            result.get('plan_sha256')!=model.digest(plan) or
            result.get('admission_plan_sha256')!=(model.digest(admission_plan) if admission_plan is not None else None) or
            result.get('coupon_plan_sha256')!=(model.digest(coupon_plan) if coupon_plan else None)):
        raise ValueError('Incomplete, stale or unsupported exact reference')
    d=result.get('domain',{});td=task['domain']
    expected={'requirements':matching['requirements'],'allow_extras':td['allow_extras'],
        'quantity_limits':domain['quantity_limits'],'max_lines_per_order':domain['options']['max_lines_per_order'],
        'allowed_destination_types':td['allowed_destination_types'],'deadline':td['deadline'],
        'destination':world['user_location'],'canonical_line_id':'offer_id'}
    if any(d.get(k)!=v for k,v in expected.items()):raise ValueError('Reference search domain differs from accessible checkout')
    if result['status']=='optimal' and (type(result.get('total_minor')) is not int or result['total_minor']<0):
        raise ValueError('Invalid exact optimum')
    basket_quote.validate_plan(world,plan)
    return matching,result


def _links(orders,bindings):
    if bindings is None:return {'status':'inconclusive','reason':'authoritative_runtime_url_bindings_absent'}
    offers=bindings.get('retailer_offers',bindings)
    failures=[]
    for index,order in enumerate(orders):
        for row in order['lines']:
            oid=row['offer_id'];b=offers.get(oid)
            if b is None:return {'status':'inconclusive','reason':'authoritative_offer_binding_absent','offer_id':oid}
            url=row.get('url')
            if type(url) is not str:
                failures.append({'order':index,'offer_id':oid,'reason':'missing_or_incorrect_retailer_variant_url'});continue
            try:
                expected=urlsplit(b['url']); actual=urlsplit(url)
            except ValueError:
                failures.append({'order':index,'offer_id':oid,'reason':'malformed_retailer_url'});continue
            expected_route,_,_=expected.fragment.partition('?')
            route,_,query=actual.fragment.partition('?')
            if (b['retailer_id']!=order['retailer_id'] or
                    (actual.scheme,actual.netloc,actual.path,actual.query,route)!=
                    (expected.scheme,expected.netloc,expected.path,expected.query,expected_route)):
                failures.append({'order':index,'offer_id':oid,'reason':'missing_or_incorrect_retailer_variant_url'});continue
            pairs=parse_qsl(query,keep_blank_values=True)
            encoded=dict(pairs); selection=row.get('selection',{})
            required=b.get('required_selection',{})
            full=b.get('selection',required)
            behavior=b.get('url_behavior','none')
            if (len(pairs)!=len(encoded) or type(selection) is not dict or
                    any(k not in full or str(full[k])!=v for k,v in encoded.items()) or
                    any(k not in full or type(v) is not type(full[k]) or v!=full[k] for k,v in selection.items())):
                failures.append({'order':index,'offer_id':oid,'reason':'missing_or_incorrect_variant_selection'});continue
            # The renderer only reads URL axes permitted by its sampled URL
            # behavior. A reported selector must supply every other axis.
            effective={k:v for k,v in encoded.items() if behavior=='all' or behavior=='colour' and k=='colour'}
            if any(k not in selection and (k not in effective or effective[k]!=str(v)) for k,v in full.items()):
                failures.append({'order':index,'offer_id':oid,'reason':'missing_or_incorrect_variant_selection'})
    return {'status':'fail' if failures else 'pass','failures':failures}


def grade(world,request,response,*,reference,plan,domain,coupon_plan=None,url_bindings=None,admission_plan=None):
    """Return component pass/fail/inconclusive, with exact requotation evidence."""
    report={'schema_version':'native-order-set-grade-v1','verdict':'inconclusive',
            'components':{},'world_id':world.get('world_id')}
    try:
        task=order_set_task.validate(request)
        matching,result=_bound(world,task,reference,plan,domain,coupon_plan,admission_plan)
        oracle=basket_quote
        if admission_plan is not None:
            from experiments.accepted_catalog_commerce.delivery_admission import Oracle
            oracle=Oracle(world,plan,admission_plan)
    except (ValueError,KeyError,TypeError) as exc:
        report['components']['reference']={'status':'inconclusive','reason':str(exc)};return report
    report['components']['reference']={'status':'pass','reference_sha256':model.digest(reference)}
    if type(response) is not dict or response.get('schema_version')!=VERSION:
        report['components']['response']={'status':'inconclusive','reason':'structured_response_required; prose extraction unsupported'};return report
    try:
        if response.get('status')=='no_match':
            if set(response)!={'schema_version','status'}:raise InvalidPlan('No-match response has unsupported fields')
            ok=result['status']=='infeasible'
            report['components']['outcome']={'status':'pass' if ok else 'fail','reason':'exact_infeasibility' if ok else 'a_feasible_plan_exists'}
            report['verdict']='pass' if ok else 'fail';return report
        if set(response)!={'schema_version','status','orders','total_minor'} or response['status']!='plan':raise InvalidPlan('Supply status plan, orders and total_minor')
        if type(response['total_minor']) is not int or response['total_minor']<0:raise InvalidPlan('Claimed total must be exact nonnegative integer minor units')
        orders=response['orders']
        if type(orders) is not list or not orders:raise InvalidPlan('Supply nonempty orders')
        retailers={r['retailer_id']:r for r in world['retailers']}
        purchased=defaultdict(int);use=defaultdict(int);coupons=set();quoted=[]
        capacity={}
        for rid,r in retailers.items():
            for o in r['offers']:
                for sid,q in o['stock_by_source'].items():
                    key=(rid,o['sku_id'],sid)
                    if key in capacity and capacity[key]!=q:raise InvalidPlan('Inconsistent native source stock identity')
                    capacity[key]=q
        for index,order in enumerate(orders):
            if (type(order) is not dict or not {'retailer_id','lines','selections','split'}<=set(order) or
                    set(order)-{'retailer_id','lines','selections','split','coupon_code','total_minor'}):raise InvalidPlan('Unknown or missing order field')
            rid=order['retailer_id']
            if type(rid) is not str or rid not in retailers:raise InvalidPlan('Unknown retailer')
            if type(order['split']) is not bool:raise InvalidPlan('Split must be boolean')
            if type(order['lines']) is not list:raise InvalidPlan('Lines must be an array')
            lines=[]
            for row in order['lines']:
                if type(row) is not dict or not {'offer_id','quantity'}<=set(row) or set(row)-{'offer_id','quantity','url','selection'}:raise InvalidPlan('Unknown or missing line field')
                lines.append({'line_id':row['offer_id'],'offer_id':row['offer_id'],'quantity':row['quantity']})
            try:lines,_=checkout_domain.canonical_lines(world,domain,rid,lines)
            except (ValueError,TypeError) as exc:raise InvalidPlan(str(exc)) from exc
            selected=order['selections']
            if type(selected) is not dict or set(selected)!={l['offer_id'] for l in lines} or any(type(v) is not str for v in selected.values()):raise InvalidPlan('Supply complete canonical line-to-service selections')
            code=order.get('coupon_code')
            if code is not None and (type(code) is not str or not code):raise InvalidPlan('Coupon code must be text or null')
            try:q=oracle.quote(world,rid,lines,plan=plan,coupon_plan=coupon_plan,
                destination=world['user_location'],selections=selected,split=order['split'],coupon_code=code)
            except (ValueError,KeyError,TypeError) as exc:raise InvalidPlan('Invalid native quote request: '+str(exc)) from exc
            option=q['selected']
            if option is None:raise InvalidPlan('Checkout does not support submitted delivery/stock plan: '+q['status'])
            if 'total_minor' in order and (type(order['total_minor']) is not int or order['total_minor']!=option['total_minor']):raise InvalidPlan('Per-order monetary claim differs from native quote')
            for shipment in option['shipments']:
                if shipment['delivery']['destination_type'] not in task['domain']['allowed_destination_types']:raise InvalidPlan('Delivery type excluded by task')
                for item in shipment['items']:
                    if item['supply']=='on_hand':use[(rid,item['sku_id'],item['source_id'])]+=item['quantity']
            deadline=task['domain']['deadline']
            if deadline and (option['arrival']['status']!='estimated' or option['arrival']['latest_date']>deadline):raise InvalidPlan('Arrival does not meet deadline')
            if option['coupon']['status']=='applied':
                cid=option['coupon']['coupon_id']
                if cid in coupons:raise InvalidPlan('Single-use coupon used by multiple orders')
                coupons.add(cid)
            for l in lines:purchased[l['offer_id']]+=l['quantity']
            quoted.append({'order_index':index,'retailer_id':rid,'lines':lines,'quote_id':q['quote_id'],'selected':deepcopy(option)})
        if any(q>capacity.get(key,0) for key,q in use.items()):raise InvalidPlan('Combined orders exceed native source stock')
        allocation=coverage(matching['requirements'],purchased)
        if not allocation['covered']:raise InvalidPlan('Purchased units cannot cover every requested requirement without double-counting')
        if not task['domain']['allow_extras'] and sum(purchased.values())!=allocation['required_units']:raise InvalidPlan('Task excludes additional units')
        total=sum(q['selected']['total_minor'] for q in quoted)
        if total!=response['total_minor']:raise InvalidPlan('Claimed complete total differs from native requotation')
        optimum=result['total_minor']
        if result['status']!='optimal':
            report['components']['outcome']={'status':'inconclusive','reason':'feasible_submission_conflicts_with_exact_infeasibility'};return report
        if total<optimum:
            report['components']['outcome']={'status':'inconclusive','reason':'requote_beats_reference_requires_reference_audit','total_minor':total};return report
        report['components']['outcome']={'status':'pass' if total==optimum else 'fail','total_minor':total,'optimum_minor':optimum,'allocation':allocation,'quotes':quoted}
        report['components']['links']=_links(orders,url_bindings)
        statuses=[v['status'] for v in report['components'].values()]
        report['verdict']='fail' if 'fail' in statuses else 'inconclusive' if 'inconclusive' in statuses else 'pass'
    except (InvalidPlan,KeyError,TypeError) as exc:
        report['components']['outcome']={'status':'fail','reason':str(exc)};report['verdict']='fail'
    return report
