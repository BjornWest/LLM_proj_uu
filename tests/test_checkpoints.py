"""Private capsule integrity, exact history and identity rebinding; no inference."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import concurrent.futures
import json
import unittest

from intent_browser.checkpoints import (CheckpointStore,conversation_state,
    restore_conversation,ax_state,restore_ax,CheckpointControl)
from intent_browser.native_tools import NativeConversation
from intent_browser.ax_context import AXContext
from intent_browser.ax_explorer import AXConfig
from intent_browser.trace import Trace
from tests.test_ax_explorer import TOKENIZER,node,observation

class CapsuleTests(unittest.TestCase):
    def test_corrupt_object_manifest_paths_and_symlinks_rejected(self):
        with TemporaryDirectory() as root:
            store=CheckpointStore(Path(root)/'store');trace=Trace(Path(root)/'runs',{})
            (trace.directory/'draft.txt').write_text('unchanged')
            trace.flush_observations()
            key=store.save({'state':{'effect':1}},trace)
            record=store.load(key);self.assertEqual(record['payload']['state']['effect'],1)
            obj=record['prefix']['draft.txt'];self.assertEqual(store.get(obj),b'unchanged')
            store.materialize_prefix(record,Path(root)/'inherited')
            self.assertEqual((Path(root)/'inherited/draft.txt').read_bytes(),b'unchanged')
            with self.assertRaises(FileExistsError):store.materialize_prefix(record,Path(root)/'inherited')
            path=store.objects/obj['sha256'];path.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'changed'):store.load(key)
            trace.finish({})

    def test_concurrent_equal_objects_share_one_verified_blob(self):
        with TemporaryDirectory() as root:
            store=CheckpointStore(root)
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                records=list(pool.map(store.put,[b'identical image bytes']*32))
            self.assertTrue(all(r==records[0] for r in records))
            self.assertEqual(len(list(store.objects.iterdir())),1)

    def test_exact_reasoning_and_tool_ids_restored_no_duplicate_request(self):
        c=NativeConversation();c.initialize('System','Goal');c.request('System','Goal','Start')
        assistant={'role':'assistant','reasoning':'Keep my plan intact.','content':'Visible reply',
            'tool_calls':[{'id':'old-call','type':'function','function':{'name':'click','arguments':'{"bid":"12"}'}}]}
        c.record_batch(assistant,[({'result':'Done'},None)])
        messages=c.request('System','Goal','Current')
        state=conversation_state(c);fresh=NativeConversation()
        restore_conversation(fresh,state,'System','Goal')
        self.assertEqual(fresh._messages,messages)
        self.assertTrue(fresh.has_call_id('old-call'))
        with self.assertRaisesRegex(ValueError,'preceding'):fresh.request('System','Goal','Duplicate')
        self.assertIn('Keep my plan',json.dumps(fresh._messages))
        with self.assertRaisesRegex(ValueError,'differs'):restore_conversation(NativeConversation(),state,'Other','Goal')
        c.add_human_message('Pending',source_id='private')
        with self.assertRaisesRegex(ValueError,'assembled'):conversation_state(c)

    @unittest.skipUnless(TOKENIZER.is_file(),'Local tokenizer required')
    def test_ax_rebind_new_chromium_ids_preserves_delivered_and_pending_refs(self):
        cfg=AXConfig(str(TOKENIZER),incremental=True,revisit_reuse=True,agent_overview=True)
        nodes=[node(0,'RootWebArea','Shop',[1,2]),node(1,'button','Cancel order',bid=12),node(2,'textbox','Query',bid=13)]
        for i,n in enumerate(nodes):n['backendDOMNodeId']=100+i
        old=AXContext(cfg);obs=observation(nodes)
        old.prepare_observation(obs);old.acknowledge();old.search('Cancel')
        state=ax_state(old);live=deepcopy(obs)
        for n in live['axtree_object']['nodes']:n['backendDOMNodeId']+=10000
        fresh=AXContext(cfg);restore_ax(fresh,state,live)
        ref=old._refs[1];self.assertEqual(fresh.resolve(ref),1)
        self.assertEqual(fresh.seen,old.seen);self.assertEqual(fresh.pending,old.pending)
        fresh.capture(live);self.assertEqual(fresh._refs,old._refs)
        for mode in ('label','bid','checked','order'):
            changed=deepcopy(live);nodes=changed['axtree_object']['nodes']
            if mode=='label':nodes[1]['name']['value']='Different'
            if mode=='bid':nodes[1]['browsergym_id']='77'
            if mode=='checked':nodes[1]['properties']=[{'name':'checked','value':{'value':True}}]
            if mode=='order':nodes[0]['childIds'].reverse()
            with self.subTest(mode=mode),self.assertRaisesRegex(ValueError,'semantics'):
                restore_ax(AXContext(cfg),state,changed)


class BridgeTests(unittest.TestCase):
    def run_route(self,location=None,unknown=False):
        import httpx
        from intent_browser.checkpoint_browser import LogicalOrigins
        class Request:
            url='http://logical.test/search' if not unknown else 'https://foreign.invalid/'
            method='POST';post_data_buffer=b'x=1'
            def all_headers(self):return {'origin':'http://logical.test','referer':'http://logical.test/','host':'logical.test'}
        class Route:
            result=None
            def abort(self,value):self.result=('abort',value)
            def fulfill(self,**value):self.result=value
        bridge=LogicalOrigins({'store':'http://logical.test'},{'store':'http://127.0.0.1:43123'})
        self.addCleanup(bridge.close);bridge.client.close();requests=[]
        def transport(request):
            requests.append(request)
            headers=([('location',location)] if location else [('content-type','text/html'),('set-cookie','a=1; Path=/'),('set-cookie','b=2; Path=/')])
            return httpx.Response(302 if location else 200,headers=headers,content=b'<a href="http://127.0.0.1:43123/path">Next</a>')
        bridge.client=httpx.Client(transport=httpx.MockTransport(transport))
        route=Route();bridge.route(route,Request());return route.result,requests

    def test_unknown_destination_never_forwarded_and_post_origin_rewritten(self):
        result,requests=self.run_route(unknown=True)
        self.assertEqual(result,('abort','blockedbyclient'));self.assertEqual(requests,[])
        result,requests=self.run_route()
        self.assertEqual(str(requests[0].url),'http://127.0.0.1:43123/search')
        self.assertEqual(requests[0].headers['origin'],'http://127.0.0.1:43123')
        self.assertEqual(requests[0].content,b'x=1')
        self.assertIn(b'http://logical.test/path',result['body'])
        self.assertIn('a=1',result['headers']['set-cookie']);self.assertIn('b=2',result['headers']['set-cookie'])

    def test_redirects_normalized_and_ambiguous_or_foreign_rejected(self):
        for location in ('///outside.invalid','http:////outside.invalid','//outside.invalid','/\\outside.invalid',
                         'https://outside.invalid/',' http://127.0.0.1:43123/path'):
            with self.subTest(location=location):
                result,_=self.run_route(location)
                self.assertEqual(result['status'],502)
        for location in ('/account','http://127.0.0.1:43123/account'):
            result,_=self.run_route(location)
            self.assertEqual(result['headers']['location'],'http://logical.test/account')

    def test_replacements_do_not_cascade_when_ports_overlap(self):
        from intent_browser.checkpoint_browser import LogicalOrigins
        bridge=LogicalOrigins({'a':'http://127.0.0.1:10','b':'http://127.0.0.1:20'},
                              {'a':'http://127.0.0.1:20','b':'http://127.0.0.1:30'})
        self.addCleanup(bridge.close)
        self.assertEqual(bridge.replace('http://127.0.0.1:30/ http://127.0.0.1:20/ http://127.0.0.1:300/'),
                         'http://127.0.0.1:20/ http://127.0.0.1:10/ http://127.0.0.1:300/')

class BoundaryTests(unittest.TestCase):
    def test_noncanonical_paths_and_invalid_object_records(self):
        from intent_browser.checkpoints import safe_name
        for value in ('../secret','/secret','a//b','a/./b','a/','a\\b','',None):
            with self.subTest(value=value),self.assertRaises(ValueError):safe_name(value)
        with TemporaryDirectory() as root:
            store=CheckpointStore(root)
            for record in ({'sha256':None,'bytes':0},{'sha256':'a'*64,'bytes':True},{'sha256':'a'*64,'bytes':-1}):
                with self.subTest(record=record),self.assertRaises(ValueError):store.get(record)

    @unittest.skipUnless(TOKENIZER.is_file(),'Local tokenizer required')
    def test_label_echo_reconciliation_is_narrow_and_checked_state_not_hidden(self):
        cfg=AXConfig(str(TOKENIZER),incremental=True)
        original=[node(0,'RootWebArea','Shop',[1]),node(1,'LabelText','',[2]),node(2,'checkbox','Marketing',bid=7)]
        old=AXContext(cfg);obs=observation(original);old.capture(obs);state=ax_state(old)
        live=deepcopy(original);live[1]['childIds'].append('3');live.append(node(3,'StaticText','Marketing'))
        fresh=AXContext(cfg);restore_ax(fresh,state,observation(live));self.assertEqual(fresh._refs,old._refs)
        live[-1]['name']['value']='A separate explanation'
        with self.assertRaisesRegex(ValueError,'semantics'):restore_ax(AXContext(cfg),state,observation(live))
        live[-1]['name']['value']='Marketing';live[2]['properties']=[{'name':'checked','value':{'value':True}}]
        with self.assertRaisesRegex(ValueError,'semantics'):restore_ax(AXContext(cfg),state,observation(live))

    def test_unsupported_features_and_nonadopted_world_fail_before_inference(self):
        from intent_browser.standard_profile import standard_profile
        class World:
            def checkpoint_state(self):pass
            def restore_state(self,value):pass
            def checkpoint_hydration(self):pass
            def state_fingerprint(self):raise ValueError('Explicit adoption required')
        with TemporaryDirectory() as root:
            control=CheckpointControl(CheckpointStore(root),World());profile=standard_profile(helpers=False)
            for feature in ('retry','memory','clarification','video','delegated','handover','search'):
                with self.subTest(feature=feature),self.assertRaisesRegex(ValueError,'requires native'):
                    control.validate(profile,None,**{feature:True})
            with self.assertRaisesRegex(ValueError,'adoption'):control.validate(profile,None)

    def test_replay_exact_request_schema_and_exhaustion(self):
        from intent_browser.checkpoint_replay import RecordedDecisionReplay
        messages=[{'role':'system','content':'Exact'}]
        row={'step':4,'messages':messages,'model_request':{'messages':messages,'tools':[]},'model_response':{'choices':[]},'model_output':''}
        backend=RecordedDecisionReplay([row],source='source');backend.configure_tools({'tools':[]})
        with self.assertRaisesRegex(ValueError,'request differs'):backend.complete([{'role':'system','content':'Changed'}])
        self.assertEqual(backend.calls,0)
        backend.configure_tools({'tools':[{'different':'schema'}]})
        with self.assertRaisesRegex(ValueError,'configuration'):backend.complete(messages)
        self.assertEqual(backend.calls,0);backend.configure_tools({'tools':[]})
        result=backend.complete(messages);self.assertEqual(result.raw,row['model_response'])
        self.assertFalse(backend.replay_evidence[0]['new_inference'])
        with self.assertRaisesRegex(ValueError,'exhausted'):backend.complete(messages)

class ReplaySelectionTests(unittest.TestCase):
    def test_explicit_range_and_partial_or_failed_batches_rejected(self):
        from intent_browser.checkpoint_replay import selected_rows,RecordedDecisionReplay
        messages=[{'role':'system','content':'Exact'}]
        row={'step':0,'messages':messages,'model_request':{'messages':messages},'model_response':{'choices':[]},'model_output':''}
        with TemporaryDirectory() as root:
            path=Path(root)/'steps.jsonl';path.write_text(json.dumps(row)+'\n')
            self.assertEqual(selected_rows(root,0,1),[row])
            for start,stop in ((1,None),(0,2),(-1,1),(0,True)):
                with self.subTest(start=start,stop=stop),self.assertRaises(ValueError):selected_rows(root,start,stop)
            for call in ({'kind':'skipped'},{'action_error':'Timeout'},{'tool_error':'Unknown ref'},{'batch_guard_error':{'phase':'guard'}}):
                bad={**row,'batch_calls':[call]}
                with self.subTest(call=call),self.assertRaises(ValueError):RecordedDecisionReplay([bad],source='source')

if __name__=='__main__':unittest.main()
