"""Retailer account UI. All business rules/state live in Product's AccountSession.

An isolated connected Runtime represents one synthetic shopper/episode; browsers
attached to that Runtime deliberately share that shopper's account state.
"""
import secrets
from .pages import e,link,path_product,money,shell


class AccountPages:
    def __init__(self,owner,export):
        from environments.product_world.accounts import AccountSession
        self.owner=owner;self.session=AccountSession(owner.world,export);self.as_of=export['as_of']
        self.tokens={sid:secrets.token_urlsafe(32) for sid in owner.stores}

    def navigation(self,site):
        state=self.session.account(site)
        label='My account' if state['signed_in'] else 'Account (signed out)'
        return '<nav aria-label="Account">'+link('/account',label)+'</nav>'

    def render(self,site,path,q):
        if q:raise ValueError('Unexpected account parameter')
        state=self.session.account(site)
        if not state['signed_in']:
            return 200,shell(self.owner,site,'Account','<h1>Account</h1><p>You are not signed in at this retailer. Ask the user to sign in to access their account.</p>')
        account=state['account'];body='<nav aria-label="Account pages">'+link('/account','Account overview')+' · '+link('/account/coupons','Coupons')+' · '+link('/account/orders','Orders')+'</nav>'
        if path=='/account':
            body+='<h1>My account</h1><p>Signed in as '+e(account['display_name'])+'</p>'
            body+='<p>View your coupons, track deliveries or manage eligible orders.</p>'
        elif path=='/account/coupons':
            body+='<h1>Your coupons</h1>'
            for c in account['coupons']:
                discount=str(c['value'])+'%' if c['kind']=='percent' else money(c['value'])
                body+='<article><h2>'+e(c['code'])+'</h2><p>'+discount+' off the item subtotal. Shipping is not discounted.</p>'
                body+='<dl><dt>Minimum item subtotal</dt><dd>'+money(c['minimum_subtotal_minor'])+'</dd><dt>Applies to</dt><dd>'+e(', '.join(c['families']).replace('_',' ') or 'All products')+'</dd><dt>Valid from</dt><dd>'+e(c['valid_from'])+'</dd><dt>Valid through</dt><dd>'+e(c['valid_until'])+'</dd></dl>'
                body+='<p>'+('Already redeemed' if c['redeemed'] else 'Not redeemed')+'</p><p>Use one code on a delivery or pickup quote to check eligibility and the total. Codes cannot be combined.</p></article>'
            if not account['coupons']:body+='<p>You have no coupons.</p>'
            body+='<p>Current date: '+e(self.as_of)+'</p>'
        elif path=='/account/orders':
            body+='<h1>Your orders</h1>'
            orders=self.session.orders(site)
            for order in orders:
                body+='<article><h2>'+link('/account/orders/'+order['order_id'],'Order '+order['order_id'])+'</h2><p>'+e(order['status'])+' · '+e(order['placed_date'])+' · '+money(order['total_minor'])+'</p></article>'
            if not orders:body+='<p>No orders found.</p>'
        elif path.startswith('/account/orders/'):
            parts=path.strip('/').split('/')
            if len(parts) not in (3,4) or len(parts)==4 and parts[3]!='cancel':raise KeyError('Unknown account page')
            order=self.session.track(site,parts[2])
            body+=self.order_body(site,order,confirm=len(parts)==4)
        else:raise KeyError('Unknown account page')
        return 200,shell(self.owner,site,'My account',body)

    def order_body(self,site,order,confirm=False):
        oid=order['order_id'];body='<h1>Order '+e(oid)+'</h1><p id="order-status">Status: '+e(order['status'])+'</p>'
        body+='<p>Placed: '+e(order['placed_date'])+'</p><ul>'
        for line in order['lines']:
            body+='<li>'+link(path_product(line['product_id']),line['name'])+' · '+e(line['product_id'])+' · quantity '+str(line['quantity'])+' · '+money(line['unit_price_minor'])+' each</li>'
        body+='</ul><dl>'
        for label,key in [('Item subtotal','subtotal_minor'),('Shipping','shipping_minor'),('Discount','discount_minor'),('Order total','total_minor')]:body+='<dt>'+label+'</dt><dd>'+money(order[key])+'</dd>'
        body+='</dl>'
        for label,key in [('Estimated delivery','estimated_delivery_date'),('Delivered','delivered_date'),('Cancelled','cancelled_date')]:
            if order.get(key):body+='<p>'+label+': '+e(order[key])+'</p>'
        body+='<section aria-label="Tracking history"><h2>Tracking history</h2><ol>'
        for event in order['tracking_events']:body+='<li>'+e(event['date'])+' — '+e(event['description'])+' ('+e(event['status'])+')</li>'
        body+='</ol></section>'
        if order['can_cancel']:
            if confirm:
                body+='<h2>Cancel this order?</h2><p>This will cancel all items in order '+e(oid)+'.</p><form method="post" action="/account/orders/'+e(oid)+'/cancel"><input type="hidden" name="token" value="'+e(self.tokens[site])+'"><button name="confirm" value="yes">Confirm cancellation</button></form>'+link('/account/orders/'+oid,'Keep order')
            else:body+=link('/account/orders/'+oid+'/cancel','Cancel order')
        else:body+='<p>This order cannot be cancelled'+(' again.' if order['status']=='cancelled' else ' at its current stage.')+'</p>'
        return body+link('/account/orders','All orders')

    def action(self,site,path,fields):
        parts=path.strip('/').split('/')
        if len(parts)!=4 or parts[:2]!=['account','orders'] or parts[3]!='cancel':raise KeyError('Unknown action')
        if set(fields)!={'token','confirm'} or fields['confirm']!='yes':raise ValueError('Confirmation required')
        if not secrets.compare_digest(fields['token'],self.tokens[site]):return 403,'<h1>Invalid form token</h1>'
        result=self.session.cancel(site,parts[2])
        if not result['ok']:
            return 409,shell(self.owner,site,'Cancellation unavailable','<h1>Cancellation unavailable</h1><p>'+e(result['error'])+'</p>'+link('/account/orders','Your orders'))
        body='<p role="status">'+('Order cancelled.' if result['changed'] else 'Order was already cancelled; no new change made.')+'</p>'+self.order_body(site,result['order'])
        return 200,shell(self.owner,site,'Order cancellation',body)
