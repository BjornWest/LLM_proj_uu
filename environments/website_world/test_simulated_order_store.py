"""Tiny native-maker stand-ins test store transactions, not quote correctness."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from types import SimpleNamespace
from threading import Event
import unittest
from .simulated_order_store import OrderStore


class StoreControls(unittest.TestCase):
    def test_sealed_ledger_rejects_new_commits_retries_and_rebinding(self):
        self.store.commit('a',self.request)
        expected=self.store.snapshot();self.store.seal(expected)
        self.assertEqual(self.store.snapshot(),expected)
        for request in (self.request,{**self.request,'idempotency_key':'two'}):
            with self.assertRaises(ValueError):self.store.commit('a',request)
        with self.assertRaises(ValueError):self.store.bind_episode({'episode_id':'other'})
        with self.assertRaises(ValueError):self.store.seal(expected)

    def test_inflight_commit_and_seal_cannot_omit_a_committed_record(self):
        expected=self.store.snapshot();entered=Event();release=Event()
        original=self.store._maker
        def held(*args,**kwargs):
            entered.set()
            if not release.wait(2):raise ValueError('Authored test timed out')
            return original(*args,**kwargs)
        self.store._maker=held
        with ThreadPoolExecutor(max_workers=2) as workers:
            commit=workers.submit(self.store.commit,'a',self.request)
            self.assertTrue(entered.wait(2))
            sealing=workers.submit(self.store.seal,expected)
            release.set();commit.result(timeout=2)
            with self.assertRaisesRegex(ValueError,'ledger changed'):sealing.result(timeout=2)
        self.assertEqual(len(self.store.snapshot()['orders']),1)
        with self.assertRaises(ValueError):self.store.commit('a',{**self.request,'idempotency_key':'two'})

    def setUp(self):
        self.calls=[]
        self.baskets=SimpleNamespace(adapter=SimpleNamespace(world={'world_id':'world'},retailers={'a':{},'b':{}}),plan_id='plan',domain_id='domain')
        def maker(baskets,retailer,submission,*,order_id):
            self.calls.append(deepcopy(submission))
            if submission.get('reject'):raise ValueError('Native rejected stale quote')
            return {'order_id':order_id,'retailer_id':retailer,'submission':deepcopy(submission)}
        self.store=OrderStore(self.baskets,runtime_id='runtime',record_maker=maker)
        self.request={'idempotency_key':'one','native_quote':{'selected':'choice'}}

    def test_identical_concurrent_retry_commits_one_detached_record(self):
        with ThreadPoolExecutor(max_workers=2) as workers:
            rows=list(workers.map(lambda _:self.store.commit('a',self.request),range(2)))
        self.assertEqual(rows[0],rows[1]);self.assertEqual(len(self.calls),1)
        rows[0]['submission']['native_quote']['selected']='tampered'
        self.assertEqual(self.store.commit('a',self.request)['submission']['native_quote']['selected'],'choice')
        snapshot=self.store.snapshot();self.assertEqual(len(snapshot['orders']),1);self.assertEqual(len(snapshot['events']),1)
        snapshot['orders'].clear();self.assertEqual(len(self.store.snapshot()['orders']),1)

    def test_conflict_rejects_and_distinct_keys_and_retailers_preserve_all_orders(self):
        first=self.store.commit('a',self.request)
        with self.assertRaises(ValueError):self.store.commit('a',{**self.request,'new_field':'changed'})
        second=self.store.commit('b',self.request)
        third=self.store.commit('a',{**self.request,'idempotency_key':'two'})
        self.assertEqual(len({x['order_id'] for x in (first,second,third)}),3)
        self.assertEqual([e['sequence'] for e in self.store.snapshot()['events']],[1,2,3])

    def test_native_failure_has_no_commit_or_idempotency_success(self):
        for _ in range(2):
            with self.assertRaises(ValueError):self.store.commit('a',{**self.request,'reject':True})
        self.assertEqual(self.store.snapshot()['orders'],[])
        self.assertEqual(self.store.snapshot()['events'],[])
        self.assertEqual(len(self.calls),2)
        self.assertEqual(self.store.commit('a',self.request)['order_id'],OrderStore(self.baskets,runtime_id='runtime',record_maker=lambda *args,**kw:{'order_id':kw['order_id']}).commit('a',self.request)['order_id'])

    def test_unrenderable_confirmation_rejects_before_private_commit(self):
        def rejected(retailer, record):
            record.clear()
            raise ValueError('Receipt cannot be projected to this retailer')
        self.store._precommit=rejected
        with self.assertRaises(ValueError):self.store.commit('a',self.request)
        self.assertEqual(self.store.snapshot()['orders'],[])
        self.assertEqual(self.store.snapshot()['events'],[])
        self.store._precommit=lambda retailer,record:record.clear()
        receipt=self.store.commit('a',self.request)
        self.assertIn('order_id',receipt)
        self.assertEqual(len(self.store.snapshot()['orders']),1)

    def test_episode_binding_immutable_and_malformed_inputs_do_not_reach_maker(self):
        self.store.bind_episode({'episode_id':'episode','source':'pin'})
        self.store.bind_episode({'episode_id':'episode','source':'pin'})
        with self.assertRaises(ValueError):self.store.bind_episode({'episode_id':'other'})
        for request in (None,{}, {'idempotency_key':1},{'idempotency_key':'one','bad':float('nan')}):
            with self.assertRaises(ValueError):self.store.commit('a',request)
        with self.assertRaises(ValueError):self.store.commit('unknown',self.request)
        self.assertEqual(self.calls,[])
        self.store.commit('a',self.request)
        with self.assertRaises(ValueError):self.store.bind_episode({'episode_id':'episode','source':'pin'})


if __name__=='__main__':unittest.main()
