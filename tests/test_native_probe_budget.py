import json
from pathlib import Path
import sys
import tempfile
import unittest
from decimal import Decimal
import httpx
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from native_probe_budget import NativeProbeBackend,initial_ledger,reservation
from intent_browser.native_tools import NativeBrowserTools

class BudgetTests(unittest.TestCase):
    def make(self, handler, **changes):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);ledger=Path(tmp.name)/'budget.json'
        cfg={'budget_id':'test','model':'qwen/qwen3.8-27b','providers':['dekallm'],'max_tokens':4096,
             'max_steps':30,'input_byte_limit':1000000,'pace_seconds':0,'cap_usd':'1','carried_usd':'0.026007',
             'prompt_price_cap':'0.50','output_price_cap':'4',**changes}
        ledger.write_text(json.dumps(initial_ledger(cfg,[])))
        b=NativeProbeBackend('fake-key',ledger,lambda:None,cfg,'case');b.client.close()
        b.client=httpx.Client(transport=httpx.MockTransport(handler));self.addCleanup(b.close)
        b.configure_tools(NativeBrowserTools().request_options());b.begin_episode('session')
        return b,ledger,cfg
    def response(self):
        return httpx.Response(200,json={'model':'qwen/qwen3.8-27b','provider':'DekaLLM',
            'choices':[{'message':{'content':None,'tool_calls':[]}}],
            'usage':{'cost':0.001,'prompt_tokens':100,'completion_tokens':100}})
    def test_full_schemas_and_native_history_reserved_exactly(self):
        sent=[];b,l,c=self.make(lambda r:sent.append(json.loads(r.content)) or self.response())
        messages=[{'role':'user','content':'go'},{'role':'assistant','content':None,
            'reasoning_details':[{'type':'reasoning.text','text':'Synthetic plan '*1000}], 'tool_calls':[
            {'id':'old','type':'function','function':{'name':'click','arguments':'{"bid":"1"}'}}]},
            {'role':'tool','tool_call_id':'old','content':'worked'}]
        b.wait_until_ready();result=b.complete(messages);row=json.loads(l.read_text())['requests'][0]
        bound=len(json.dumps(sent[0],ensure_ascii=False,allow_nan=False).encode())+2048
        self.assertEqual(row['input_byte_bound'],bound);self.assertEqual(row['model_request'],sent[0])
        self.assertEqual(Decimal(row['reservation_usd']),reservation(bound,4096,c))
        self.assertGreater(bound,len(json.dumps(messages).encode())+2048)
        self.assertEqual(result.request,sent[0]);self.assertEqual(sent[0]['session_id'],'session')
    def test_timeout_retains_reservation_request_and_no_retry(self):
        sent=[]
        def fail(r):sent.append(r);raise httpx.ReadTimeout('timeout',request=r)
        b,l,_=self.make(fail);b.wait_until_ready()
        with self.assertRaises(httpx.ReadTimeout):b.complete([{'role':'user','content':'go'}])
        row=json.loads(l.read_text())['requests'][0]
        self.assertEqual(row['status'],'error');self.assertIn('tools',row['model_request'])
        self.assertGreater(Decimal(row['reservation_usd']),0)
        with self.assertRaises(ValueError):b.wait_until_ready()
        self.assertEqual(len(sent),1)
    def test_budget_or_fingerprint_blocks_dispatch(self):
        for mode in ['budget','source']:
            with self.subTest(mode=mode):
                sent=[];b,l,_=self.make(lambda r:sent.append(r) or self.response(),cap_usd='0.026008' if mode=='budget' else '1')
                if mode=='source':b.validate=lambda:(_ for _ in ()).throw(ValueError('changed'))
                b.wait_until_ready()
                with self.assertRaises(ValueError):b.complete([{'role':'user','content':'go'}])
                self.assertEqual(sent,[]);self.assertEqual(json.loads(l.read_text())['requests'],[])

    def test_settlement_releases_excess_but_preserves_reservation_audit(self):
        sent=[];b,l,c=self.make(lambda r:sent.append(r) or self.response(),settle_reported_cost=True,
                             carried_usd='0',cap_usd='0.023')
        for _ in range(3):
            b.wait_until_ready();b.complete([{'role':'user','content':'go'}])
        data=json.loads(l.read_text())
        self.assertEqual(len(sent),3)
        self.assertEqual(Decimal(data['committed_cost_usd']),Decimal('.003'))
        self.assertGreater(Decimal(data['reserved_cost_usd']),Decimal(c['cap_usd']))
        self.assertEqual(Decimal(data['unresolved_reserved_usd']),0)

    def test_settlement_timeout_keeps_full_reservation_and_no_retry(self):
        def fail(r):raise httpx.ReadTimeout('offline timeout',request=r)
        b,l,c=self.make(fail,settle_reported_cost=True,carried_usd='0')
        b.wait_until_ready()
        with self.assertRaises(httpx.ReadTimeout):b.complete([{'role':'user','content':'go'}])
        d=json.loads(l.read_text())
        self.assertEqual(d['committed_cost_usd'],d['reserved_cost_usd'])
        self.assertEqual(d['unresolved_reserved_usd'],d['reserved_cost_usd'])
        with self.assertRaises(ValueError):b.wait_until_ready()

    def test_settled_cap_and_raw_cost_mismatch_fail_before_dispatch(self):
        for mode in ('cap','cost'):
            with self.subTest(mode=mode):
                sent=[];b,l,c=self.make(lambda r:sent.append(r) or self.response(),settle_reported_cost=True,carried_usd='0')
                b.wait_until_ready();b.complete([{'role':'user','content':'go'}])
                if mode=='cost':
                    data=json.loads(l.read_text());data['requests'][0]['reported_cost_usd']=0;l.write_text(json.dumps(data))
                else:b.CAP=Decimal('.001');data=json.loads(l.read_text());data['approved_cap_usd']='.001';l.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    b.wait_until_ready();b.complete([{'role':'user','content':'go'}])
                self.assertEqual(len(sent),1)
if __name__=='__main__':unittest.main()
