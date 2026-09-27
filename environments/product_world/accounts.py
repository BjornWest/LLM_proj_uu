"""Synthetic signed-in accounts, price coupons and scoped historical order state."""
from copy import deepcopy
from datetime import date,timedelta
from decimal import Decimal,ROUND_HALF_UP
from threading import RLock
from .generator import rng,digest,weighted
from .config import _number,_weights
from .stores import validate_store_world

VERSION='shopping-accounts-v1'
STATUSES=('processing','shipped','delivered','cancelled')


def options(patch=None):
    cfg={'signed_in_probability':.7,'coupon_probability':.75,'expired_probability':.2,
         'redeemed_probability':.1,'coupons_per_account':2,'orders_per_account':3,
         'order_status_weights':{'processing':.4,'shipped':.3,'delivered':.25,'cancelled':.05}}
    if patch is not None:
        if not isinstance(patch,dict) or set(patch)-set(cfg):raise ValueError('Unknown account option')
        cfg.update(patch)
    for key in ('signed_in_probability','coupon_probability','expired_probability','redeemed_probability'):_number(cfg[key],key,probability=True)
    for key in ('coupons_per_account','orders_per_account'):
        if type(cfg[key]) is not int or not 0<=cfg[key]<=12:raise ValueError('Account counts must be 0..12')
    cfg['order_status_weights']=_weights(dict.fromkeys(STATUSES,1),cfg['order_status_weights'],'order status')
    return cfg


def iso(value):
    if not isinstance(value,str):raise ValueError('Expected ISO date')
    d=date.fromisoformat(value)
    if d.isoformat()!=value:raise ValueError('Expected YYYY-MM-DD date')
    return d


def generate_accounts(world,*,seed=0,as_of='2026-09-27',config=None):
    validate_store_world(world)
    if type(seed) is not int:raise ValueError('Account seed must be integer')
    today=iso(as_of)
    if today<date(2,1,1):raise ValueError('Account date must allow historical orders')
    cfg=options(config);products={p['product_id']:p for p in world['public']['products']};rows=[]
    for store in world['public']['retailers']:
        sid=store['retailer_id'];ns=VERSION+'/'+sid;coupons=[];orders=[]
        for i in range(cfg['coupons_per_account']):
            r=rng(seed,ns+'/coupon/'+str(i))
            if r.random()>=cfg['coupon_probability']:continue
            kind=r.choice(('percent','fixed'));value=r.choice((10,15,20,25)) if kind=='percent' else r.choice((5000,10000,15000))
            coupons.append({'coupon_id':f'coupon-{sid}-{i+1:02d}','code':f'SAVE{i+1}-{value if kind=="percent" else value//100}',
                'kind':kind,'value':value,'minimum_subtotal_minor':r.choice((0,20000,50000)),
                'families':[] if r.random()<.5 else [r.choice(store['families'])],
                'valid_from':(today-timedelta(days=30)).isoformat(),
                'valid_until':(today+timedelta(days=-1 if r.random()<cfg['expired_probability'] else 30)).isoformat(),
                'redeemed':r.random()<cfg['redeemed_probability']})
        offers=sorted((o for o in world['public']['offers'] if o['retailer_id']==sid),key=lambda o:o['offer_id'])
        for i in range(cfg['orders_per_account']):
            r=rng(seed,ns+'/order/'+str(i));o=r.choice(offers);quantity=r.randint(1,2)
            status=weighted(r,list(STATUSES),[cfg['order_status_weights'][s] for s in STATUSES])
            age=r.randint(*{'processing':(0,2),'shipped':(2,5),'delivered':(6,45),'cancelled':(2,30)}[status])
            placed=today-timedelta(days=age);events=[{'date':placed.isoformat(),'status':'processing','description':'Order received'}]
            if status in ('shipped','delivered'):events.append({'date':(placed+timedelta(days=1)).isoformat(),'status':'shipped','description':'Parcel dispatched'})
            if status=='delivered':events.append({'date':(placed+timedelta(days=3)).isoformat(),'status':status,'description':'Parcel delivered'})
            if status=='cancelled':events.append({'date':(placed+timedelta(days=1)).isoformat(),'status':status,'description':'Order cancelled'})
            subtotal=o['price_minor']*quantity
            orders.append({'order_id':f'{sid}-order-{i+1:04d}','retailer_id':sid,'status':status,
                'placed_date':placed.isoformat(),'estimated_delivery_date':(today+timedelta(days=r.randint(1,4))).isoformat() if status in ('processing','shipped') else None,
                'delivered_date':events[-1]['date'] if status=='delivered' else None,
                'cancelled_date':events[-1]['date'] if status=='cancelled' else None,'can_cancel':status=='processing',
                'lines':[{'product_id':o['product_id'],'name':products[o['product_id']]['name'],'quantity':quantity,'unit_price_minor':o['price_minor']}],
                'subtotal_minor':subtotal,'shipping_minor':4900,'discount_minor':0,'total_minor':subtotal+4900,
                'currency':'SEK','tracking_events':events})
        rows.append({'retailer_id':sid,'account_id':'account-'+sid,'display_name':'Alex',
            'signed_in':rng(seed,ns+'/signed-in').random()<cfg['signed_in_probability'],'coupons':coupons,'orders':orders})
    result={'schema_version':VERSION,'source_world_sha256':world['world_sha256'],'as_of':as_of,'accounts':rows}
    validate_accounts(world,result)
    return result


def validate_accounts(world,data):
    validate_store_world(world)
    if not isinstance(data,dict) or set(data)!={'schema_version','source_world_sha256','as_of','accounts'} or data['schema_version']!=VERSION:
        raise ValueError('Unknown account export')
    if data['source_world_sha256']!=world['world_sha256']:raise ValueError('Accounts belong to another world')
    today=iso(data['as_of']);stores={s['retailer_id']:s for s in world['public']['retailers']}
    products={p['product_id']:p for p in world['public']['products']};pairs={(o['retailer_id'],o['product_id']) for o in world['public']['offers']}
    if not isinstance(data['accounts'],list):raise ValueError('Expected account list')
    seen=set();order_ids=set();coupon_ids=set()
    for account in data['accounts']:
        if not isinstance(account,dict) or set(account)!={'retailer_id','account_id','display_name','signed_in','coupons','orders'}:raise ValueError('Invalid account')
        sid=account['retailer_id']
        if sid not in stores or sid in seen or account['account_id']!='account-'+sid or type(account['signed_in']) is not bool or not isinstance(account['display_name'],str):raise ValueError('Invalid account identity/session')
        seen.add(sid);codes=set()
        if not isinstance(account['coupons'],list) or not isinstance(account['orders'],list):raise ValueError('Invalid account contents')
        for c in account['coupons']:
            if set(c)!={'coupon_id','code','kind','value','minimum_subtotal_minor','families','valid_from','valid_until','redeemed'}:raise ValueError('Invalid coupon')
            if not isinstance(c['coupon_id'],str) or not c['coupon_id'] or c['coupon_id'] in coupon_ids or not isinstance(c['code'],str) or not c['code'] or c['code'] in codes:raise ValueError('Invalid coupon identity')
            coupon_ids.add(c['coupon_id']);codes.add(c['code'])
            if c['kind'] not in ('percent','fixed') or type(c['value']) is not int or c['value']<=0 or c['kind']=='percent' and c['value']>100:raise ValueError('Invalid coupon value')
            if type(c['minimum_subtotal_minor']) is not int or c['minimum_subtotal_minor']<0 or type(c['redeemed']) is not bool:raise ValueError('Invalid coupon eligibility')
            if not isinstance(c['families'],list) or any(f not in stores[sid]['families'] for f in c['families']) or len(c['families'])!=len(set(c['families'])):raise ValueError('Invalid coupon families')
            if iso(c['valid_from'])>iso(c['valid_until']):raise ValueError('Inverted coupon dates')
        for o in account['orders']:
            required={'order_id','retailer_id','status','placed_date','estimated_delivery_date','delivered_date','cancelled_date','can_cancel','lines','subtotal_minor','shipping_minor','discount_minor','total_minor','currency','tracking_events'}
            if set(o)!=required or not isinstance(o['order_id'],str) or not o['order_id'] or o['order_id'] in order_ids or o['retailer_id']!=sid:raise ValueError('Invalid order identity')
            order_ids.add(o['order_id'])
            if o['status'] not in STATUSES or type(o['can_cancel']) is not bool or o['can_cancel']!=(o['status']=='processing') or o['currency']!='SEK':raise ValueError('Invalid order state')
            placed=iso(o['placed_date'])
            if placed>today or not isinstance(o['lines'],list) or not o['lines']:raise ValueError('Invalid order date/lines')
            for item in o['lines']:
                if set(item)!={'product_id','name','quantity','unit_price_minor'} or (sid,item['product_id']) not in pairs or item['name']!=products[item['product_id']]['name']:raise ValueError('Order SKU/retailer mismatch')
                if type(item['quantity']) is not int or item['quantity']<1 or type(item['unit_price_minor']) is not int or item['unit_price_minor']<=0:raise ValueError('Invalid order line numbers')
            for field in ('subtotal_minor','shipping_minor','discount_minor','total_minor'):
                if type(o[field]) is not int or o[field]<0:raise ValueError('Invalid order total')
            if o['subtotal_minor']!=sum(x['quantity']*x['unit_price_minor'] for x in o['lines']) or o['discount_minor']>o['subtotal_minor'] or o['total_minor']!=o['subtotal_minor']+o['shipping_minor']-o['discount_minor']:raise ValueError('Inconsistent order total')
            if (o['estimated_delivery_date'] is not None)!=(o['status'] in ('processing','shipped')):raise ValueError('Invalid delivery estimate state')
            if o['estimated_delivery_date'] is not None and iso(o['estimated_delivery_date'])<placed:raise ValueError('Invalid estimated delivery date')
            for field,status in (('delivered_date','delivered'),('cancelled_date','cancelled')):
                if (o[field] is not None)!=(o['status']==status) or o[field] is not None and not placed<=iso(o[field])<=today:raise ValueError('Invalid terminal order date')
            events=o['tracking_events']
            expected=['processing']+(['shipped'] if o['status'] in ('shipped','delivered') else [])+([o['status']] if o['status'] in ('delivered','cancelled') else [])
            if not isinstance(events,list) or [x['status'] for x in events]!=expected:raise ValueError('Inconsistent tracking state sequence')
            previous=placed
            for event in events:
                if set(event)!={'date','status','description'} or not isinstance(event['description'],str):raise ValueError('Invalid tracking event')
                when=iso(event['date'])
                if not previous<=when<=today:raise ValueError('Invalid tracking chronology')
                previous=when
            if o['delivered_date'] is not None and o['delivered_date']!=events[-1]['date'] or o['cancelled_date'] is not None and o['cancelled_date']!=events[-1]['date']:raise ValueError('Terminal date differs from tracking')
    if seen!=set(stores):raise ValueError('Missing retailer account initialization')
    return {'valid':True,'accounts':len(seen),'orders':len(order_ids),'coupons':len(coupon_ids),'sha256':digest(data)}


class AccountSession:
    def __init__(self,world,export):
        validate_accounts(world,export)
        self.world=deepcopy(world);self.initial=deepcopy(export);self.as_of=export['as_of']
        self._accounts={a['retailer_id']:deepcopy(a) for a in export['accounts']};self._events=[];self._lock=RLock()
        self._offers={o['offer_id']:o for o in world['public']['offers']};self._products={p['product_id']:p for p in world['public']['products']}

    def account(self,retailer_id):
        with self._lock:
            a=self._accounts[retailer_id]
            return {'retailer_id':retailer_id,'signed_in':a['signed_in'],'account':deepcopy(a) if a['signed_in'] else None}

    def orders(self,retailer_id):
        a=self.account(retailer_id)
        if not a['signed_in']:raise PermissionError('sign_in_required')
        return a['account']['orders']

    def track(self,retailer_id,order_id):
        order=next((o for o in self.orders(retailer_id) if o['order_id']==order_id),None)
        if order is None:raise KeyError('order_not_found')
        return order

    def cancel(self,retailer_id,order_id):
        with self._lock:
            before=None;after=None;error=None;changed=False
            try:
                before=self.track(retailer_id,order_id)
                if before['status']=='cancelled':after=before
                elif not before['can_cancel']:error='order_not_cancellable';after=before
                else:
                    o=next(o for o in self._accounts[retailer_id]['orders'] if o['order_id']==order_id)
                    o.update(status='cancelled',can_cancel=False,cancelled_date=self.as_of,estimated_delivery_date=None)
                    o['tracking_events'].append({'date':self.as_of,'status':'cancelled','description':'Order cancelled'})
                    after=deepcopy(o);changed=True
            except PermissionError:error='sign_in_required'
            except KeyError:error='order_not_found'
            result={'ok':error is None,'error':error,'order':after,'changed':changed}
            self._events.append({'sequence':len(self._events)+1,'action':'cancel','retailer_id':retailer_id,'order_id':order_id,
                'before':before,'after':after,'ok':result['ok'],'error':error,'changed':changed})
            return deepcopy(result)

    def quote(self,base_quote,coupon_code=None):
        q=deepcopy(base_quote);offer=self._offers.get(q.get('offer_id'))
        if offer is None or q.get('retailer_id')!=offer['retailer_id'] or q.get('product_id')!=offer['product_id']:raise ValueError('Account quote offer binding mismatch')
        if type(q.get('quantity')) is not int or q['quantity']<1:raise ValueError('Invalid quote quantity')
        subtotal=offer['price_minor']*q['quantity']
        if q.get('eligible') and q.get('method')!='inspect':
            if type(q.get('shipping_minor')) is not int or q['shipping_minor']<0 or q.get('total_minor')!=subtotal+q['shipping_minor']:
                raise ValueError('Expected undiscounted authoritative quote')
        q.update(subtotal_minor=subtotal,discount_minor=0,coupon_id=None,coupon_code=None)
        if coupon_code is None:return q
        if not isinstance(coupon_code,str) or not coupon_code:raise ValueError('Coupon code must be nonempty text')
        a=self._accounts[offer['retailer_id']];c=next((c for c in a['coupons'] if c['code']==coupon_code),None)
        reason=None;today=iso(self.as_of)
        if not a['signed_in']:reason='coupon_sign_in_required'
        elif c is None:reason='coupon_not_found'
        elif c['redeemed']:reason='coupon_already_redeemed'
        elif not iso(c['valid_from'])<=today<=iso(c['valid_until']):reason='coupon_not_active'
        elif c['families'] and self._products[offer['product_id']]['category'] not in c['families']:reason='coupon_wrong_family'
        elif subtotal<c['minimum_subtotal_minor']:reason='coupon_minimum_not_met'
        elif not q['eligible'] or q['total_minor'] is None:reason='coupon_requires_purchasable_quote'
        if reason:
            q.update(eligible=False,total_minor=None,coupon_error=reason,reason_codes=[*q['reason_codes'],reason]);return q
        discount=c['value'] if c['kind']=='fixed' else int((Decimal(subtotal)*Decimal(c['value'])/100).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
        discount=min(subtotal,discount)
        q.update(discount_minor=discount,total_minor=q['total_minor']-discount,coupon_id=c['coupon_id'],coupon_code=c['code'])
        return q

    def best_quote(self,base_quote):
        standard=self.quote(base_quote)
        if not standard['eligible'] or standard['total_minor'] is None:return standard
        a=self._accounts[base_quote['retailer_id']]
        choices=[standard]
        if a['signed_in']:
            choices += [self.quote(base_quote,c['code']) for c in a['coupons']]
        return min((q for q in choices if q['eligible']),key=lambda q:(q['total_minor'],q['coupon_code'] or ''))

    def snapshot(self):
        with self._lock:
            return {'schema_version':'shopping-account-session-v1','source_world_sha256':self.initial['source_world_sha256'],
                'as_of':self.as_of,'accounts':deepcopy(list(self._accounts.values())),'events':deepcopy(self._events)}
