"""Actual mocked HTTP boundary, persistent budget/pacing and sweep scheduling."""
import copy
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import httpx
import run_sweep as sweep
from sweep_backend import SweepBackend, initial_ledger, reservation
from intent_browser.trace import write_json


class BackendTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'budget.json'
        self.config=copy.deepcopy(sweep.DEFAULT)
        write_json(self.path,initial_ledger(self.config,{}))
        self.time=1000.; self.sent=[]; self.waits=[]; self.validations=0
        self.status=200; self.headers={}; self.transport_error=False
        self.reply={'model':self.config['model'],'provider':'Cloudflare','id':'fake',
                    'choices':[{'message':{'content':'noop()'}}],
                    'usage':{'cost':0.0001,'prompt_tokens':100,'completion_tokens':3}}
        self.messages=[{'role':'system','content':'Act'}, {'role':'user','content':'Goal and page'}]

    def ledger(self): return json.loads(self.path.read_text())
    def validate(self): self.validations+=1
    def sleep(self,seconds):
        self.assertEqual(len(self.sent),len(self.ledger()['requests']))
        self.waits.append(seconds); self.time+=seconds
    def transport(self,req):
        self.sent.append(json.loads(req.content)); self.time+=2
        if self.transport_error: raise httpx.ReadTimeout('offline timeout',request=req)
        return httpx.Response(self.status,json=self.reply,headers=self.headers)
    def backend(self,case='suite/case1'):
        b=SweepBackend('fake',self.path,self.validate,self.config,case,clock=lambda:self.time,sleep=self.sleep)
        hooks=b.client.event_hooks; b.client.close()
        b.client=httpx.Client(transport=httpx.MockTransport(self.transport),event_hooks=hooks)
        b.begin_episode('episode-'+case); self.addCleanup(b.close); return b
    def send(self,b): b.wait_until_ready(); return b.complete(self.messages)

    def test_exact_session_request_response_and_dynamic_reservation(self):
        b=self.backend(); result=self.send(b); row=self.ledger()['requests'][0]
        self.assertEqual(result.request,self.sent[0]);self.assertEqual(result.raw,row['model_response'])
        self.assertEqual(row['session_id'],self.sent[0]['session_id'])
        self.assertNotIn('preset',self.sent[0]);self.assertNotIn('order',self.sent[0]['provider'])
        bound=len(json.dumps(self.messages,ensure_ascii=False).encode())+2048
        self.assertEqual(Decimal(row['reservation_usd']),reservation(bound,512,self.config))
        self.assertEqual(self.validations,1)

    def test_wait_before_reservation_within_case_and_restart(self):
        b=self.backend();self.send(b); self.assertEqual(self.waits,[])
        self.send(b); self.assertEqual(self.waits,[10.])
        b2=self.backend('suite/case2');self.send(b2)
        self.assertEqual(self.waits,[10.,10.]); self.assertEqual(len(self.sent),3)
        self.assertNotEqual(self.sent[1]['session_id'],self.sent[2]['session_id'])

    def test_missing_hook_and_consumed_hook_no_dispatch(self):
        b=self.backend()
        with self.assertRaises(ValueError):b.complete(self.messages)
        self.send(b)
        with self.assertRaises(ValueError):b.complete(self.messages)
        self.assertEqual(len(self.sent),1)

    def test_changed_ledger_after_hook_rejects_without_wait(self):
        b=self.backend();b.wait_until_ready();data=self.ledger();data['not_before_epoch']=1100;write_json(self.path,data)
        with self.assertRaises(ValueError):b.complete(self.messages)
        self.assertEqual(self.sent,[]);self.assertEqual(self.waits,[])

    def test_source_validation_after_wait_before_reserve(self):
        b=self.backend();self.send(b)
        def fail():raise ValueError('source mismatch')
        b.validate=fail;b.wait_until_ready()
        with self.assertRaises(ValueError):b.complete(self.messages)
        self.assertEqual(self.waits,[10]);self.assertEqual(len(self.ledger()['requests']),1)

    def test_429_retry_after_whitelist_persisted_no_retry(self):
        self.status=429;self.headers={'Retry-After':'120','Secret-Test':'must-not-archive'}
        b=self.backend()
        with self.assertRaises(Exception):self.send(b)
        row=self.ledger()['requests'][0]
        self.assertEqual(self.ledger()['not_before_epoch'],self.time+120)
        self.assertEqual(row['http']['retry_after'],'120')
        self.assertNotIn('Secret-Test',str(row));self.assertEqual(len(self.sent),1)
        with self.assertRaises(ValueError):self.backend('new').wait_until_ready()
        self.assertEqual(len(self.sent),1)

    def test_transport_error_keeps_current_request_unknown_response_reservation(self):
        self.transport_error=True
        with self.assertRaises(httpx.ReadTimeout):self.send(self.backend())
        row=self.ledger()['requests'][0]
        self.assertIsNone(row['model_response']);self.assertIsNone(row['http'])
        self.assertEqual(row['model_request'],self.sent[0]);self.assertGreater(Decimal(row['reservation_usd']),0)
        self.assertEqual(row['status'],'error')

    def test_oversized_multimodal_and_missing_session_rejected(self):
        b=self.backend();b.wait_until_ready()
        for messages in ([{'role':'user','content':'x'*24000}], [{'role':'user','content':[]} ]):
            with self.assertRaises(ValueError):b.complete(messages)
        self.assertEqual(self.sent,[])
        b.session_id=None
        with self.assertRaises(ValueError):b.wait_until_ready()

    def test_cost_token_and_provider_audit_errors_pause(self):
        for field in ('cost','prompt_tokens','provider'):
            with self.subTest(field=field):
                write_json(self.path,initial_ledger(self.config,{}));self.reply['provider']='Cloudflare'
                self.reply['usage']={'cost':0.0001,'prompt_tokens':100,'completion_tokens':3}
                if field=='provider':self.reply['provider']='Other'
                else:self.reply['usage'][field]=99999
                b=self.backend()
                with self.assertRaises(Exception):self.send(b)
                self.assertTrue(self.ledger()['requests'][0]['audit_issue'])
                self.assertTrue(b.stopped)

    def test_corrupt_ledger_refund_rejected(self):
        self.send(self.backend());data=self.ledger();data['reserved_cost_usd']='0';write_json(self.path,data)
        with self.assertRaises(ValueError):self.backend().wait_until_ready()
        self.assertEqual(len(self.sent),1)

    def test_per_case_limit_does_not_block_next_case(self):
        self.config['max_steps']=1;b=self.backend();self.send(b)
        with self.assertRaises(ValueError):b.wait_until_ready()
        self.send(self.backend('suite/case2'));self.assertEqual(len(self.sent),2)

    def test_budget_cap_checked_before_http(self):
        self.config['cap_usd']=self.config['carried_usd']
        write_json(self.path,initial_ledger(self.config,{}));b=self.backend();b.wait_until_ready()
        with self.assertRaises(ValueError):b.complete(self.messages)
        self.assertEqual(self.sent,[]);self.assertEqual(self.ledger()['requests'],[])

    def test_reserved_interruption_blocks_restart(self):
        self.send(self.backend());data=self.ledger();data['requests'][0]['status']='reserved';write_json(self.path,data)
        with self.assertRaises(ValueError):self.backend('other').wait_until_ready()
        self.assertEqual(len(self.sent),1)


class SweepTests(unittest.TestCase):
    def test_14_conditions_round_robin_pairs_and_unique_ids(self):
        rows=sweep.cases(sweep.DEFAULT)
        self.assertEqual(len(rows),42);self.assertEqual(len({r['case_id'] for r in rows}),42)
        self.assertEqual({r['repeat'] for r in rows[:14]},{1})
        for r in range(1,4):
            for task in ('P07','P10','P11'):
                pair=[x for x in rows if x['task']==task and x['repeat']==r]
                self.assertEqual(len({x['pair_id'] for x in pair}),1)
                self.assertEqual({x['condition'] for x in pair},{'clean','injected'})

    def test_invalid_config_rejected(self):
        for key,value in [('pace_seconds',float('nan')),('max_steps',13),('max_tokens',513),('cap_usd','4'),('tasks',[]),('providers',['other'])]:
            with self.subTest(key=key):
                c=copy.deepcopy(sweep.DEFAULT);c[key]=value
                with self.assertRaises(ValueError):sweep.validate_config(c)

    def test_exclusive_output_preserves_existing_and_dangling(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'record.json';sweep.exclusive(p,{'original':1});old=p.read_bytes()
            with self.assertRaises(FileExistsError):sweep.exclusive(p,{'replacement':1})
            self.assertEqual(p.read_bytes(),old)
            link=Path(d)/'dangling';link.symlink_to(Path(d)/'missing')
            with self.assertRaises(FileExistsError):sweep.exclusive(link,{})

    def test_report_preserves_unknown_and_unexecuted(self):
        with tempfile.TemporaryDirectory() as d:
            suite=Path(d)/'suite';c=copy.deepcopy(sweep.DEFAULT);c['repeats']=1;c['tasks']=c['tasks'][:2]
            rows=sweep.cases(c);sweep.exclusive(suite/'profile.json',{'cases':rows})
            sweep.exclusive(suite/'cases'/f"{rows[0]['case_id']}.json",{'status':'completed',
                'evaluation':{'task_completed':True,'authorization_satisfied':True,'safe_success':None,
                              'technical_error':'parser error','injection_exposed':None,'injection_avoided':None}})
            with patch.object(sweep,'BUDGET',Path(d)/'missing'):
                r=sweep.report(suite)
            self.assertEqual(r['groups'][0]['metrics']['safe_success'],{'true':0,'false':0,'unknown':1})
            self.assertEqual(r['groups'][0]['technical_failures'],1)
            self.assertEqual(r['groups'][1]['executed'],0)


if __name__=='__main__':unittest.main()
