"""Real router checks: final submission cannot bypass the flow controller."""
import http.client
from urllib.parse import urlencode,urlsplit
from html.parser import HTMLParser
from environments.procedural_commerce.generator import generate_world
from environments.procedural_commerce.runtime import Runtime

class Inputs(HTMLParser):
    def __init__(self,html):
        super().__init__();self.values={};self.feed(html)
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='input' and a.get('name'):self.values[a['name']]=a.get('value','')

def request(runtime,path,fields=None):
    u=urlsplit(runtime.origins['nordhem']);c=http.client.HTTPConnection(u.hostname,u.port,timeout=3)
    c.request('POST' if fields is not None else 'GET',path,body=urlencode(fields) if fields is not None else None,headers={'Content-Type':'application/x-www-form-urlencoded'})
    r=c.getresponse();result=(r.status,dict(r.getheaders()),r.read().decode());c.close();return result

def test_http_express_commit_replay_and_read_only_get():
    world=generate_world(37)
    with Runtime(world,checkout_flows={'nordhem':'express'}) as runtime:
        offer=next(o for o in world['offers'] if o['retailer_id']=='nordhem' and o['stock_quantity']>0)
        assert request(runtime,'/cart/set',dict(offer_id=offer['offer_id'],method='standard',extra='false'))[0]==303
        before=runtime.session.snapshot()
        status,_,html=request(runtime,'/checkout');assert status==200
        assert runtime.session.snapshot()==before
        token=Inputs(html).values['review_token'];assert token
        fields=dict(email='alex@example.test',method='standard',review_token=token,confirm='yes')
        status,headers,_=request(runtime,'/checkout',fields);assert status==303
        assert headers['Location'].startswith('/receipt/')
        receipt=request(runtime,headers['Location']);assert receipt[0]==200
        assert 'Testgatan 12' in receipt[2]
        request(runtime,'/checkout',fields)
        assert len(runtime.snapshot()['orders'])==1
        assert request(runtime,'/checkout',dict(fields,total_minor='1'))[0]==400

def test_http_wizard_cannot_use_legacy_commit_path():
    world=generate_world(37)
    with Runtime(world,checkout_flows={'nordhem':'wizard'}) as runtime:
        offer=next(o for o in world['offers'] if o['retailer_id']=='nordhem' and o['stock_quantity']>0)
        request(runtime,'/cart/set',dict(offer_id=offer['offer_id'],method='standard',extra='false'))
        assert request(runtime,'/checkout',dict(confirm='yes',review_token='forged'))[0]==303
        assert runtime.snapshot()['orders']==[]
        assert request(runtime,'/checkout/review')[0]==200
        assert runtime.snapshot()['orders']==[]
        assert request(runtime,'/checkout/unknown')[0]==404
