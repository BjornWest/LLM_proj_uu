"""Read-only account-page projection audit against a frozen, local publication."""
import argparse,json,hashlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError
from urllib.parse import urlsplit
from environments.connected_shopping.conformance import Document
from environments.product_world.generator import digest


def main():
    p=argparse.ArgumentParser();p.add_argument('--pin',type=Path,required=True);p.add_argument('--runtime',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    scenario=json.loads((a.pin/'scenario.private.json').read_text());data=scenario['accounts']
    origins=json.loads((a.runtime/'bindings.json').read_text())['origins'];provenance=json.loads((a.runtime/'provenance.json').read_text())
    assert provenance['accounts_sha256']==digest(data)
    assert json.loads((a.runtime/'accounts.private.json').read_text())==data
    rows=[]
    def get(sid,path):
        origin=origins[sid];u=urlsplit(origin)
        if u.scheme!='http' or u.hostname not in ('localhost','127.0.0.1') or u.username:raise ValueError('Local publication required')
        with urlopen(origin+path,timeout=10) as r:body=r.read().decode()
        rows.append({'site':sid,'path':path,'sha256':hashlib.sha256(body.encode()).hexdigest()})
        return Document(body).root
    public=json.dumps(json.loads((a.runtime/'manifest.json').read_text()))+json.dumps(json.loads((a.runtime/'index-documents.public.json').read_text()))
    def audit_account(account):
        sid=account['retailer_id'];home=get(sid,'/account');coupons=get(sid,'/account/coupons');orders=get(sid,'/account/orders')
        if account['signed_in']:
            assert account['display_name'] in home.text()
            for coupon in account['coupons']:
                assert any(n.text()==coupon['code'] for n in coupons.find('h2'))
                assert coupon['valid_until'] in coupons.text()
            for o in account['orders']:
                assert o['order_id'] in orders.text()
                detail=get(sid,'/account/orders/'+o['order_id'])
                assert detail.one(id='order-status').text()=='Status: '+o['status']
                assert [n.text() for n in detail.one('section',**{'aria-label':'Tracking history'}).find('li')]==[e['date']+' — '+e['description']+' ('+e['status']+')' for e in o['tracking_events']]
                assert bool([n for n in detail.find('a') if n.text()=='Cancel order'])==o['can_cancel']
                for line in o['lines']:assert line['product_id'] in detail.text()
                other=next(v['retailer_id'] for v in data['accounts'] if v['signed_in'] and v['retailer_id']!=sid)
                try:get(other,'/account/orders/'+o['order_id'])
                except HTTPError as e:assert e.code==404
                else:raise AssertionError('Cross-store order exposed')
        else:
            for root in (home,coupons,orders):
                assert 'not signed in' in root.text()
                for o in account['orders']:assert o['order_id'] not in root.text()
                for c in account['coupons']:assert c['code'] not in root.text()
        for o in account['orders']:assert o['order_id'] not in public
        for c in account['coupons']:assert c['code'] not in public
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(audit_account,data['accounts']))
    rows.sort(key=lambda row:(row['site'],row['path']))
    report={'passed':True,'rows':rows,'accounts_sha256':digest(data),'model_calls':0,'mutations':0,'scope':'Exact initial account projection, tracking/controls, signed-out and cross-retailer isolation; GET only','source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (a.output/'report.json').write_text(json.dumps(report,indent=2));print(json.dumps({'passed':True,'pages':len(rows)}))
if __name__=='__main__':main()
