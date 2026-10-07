"""Actual runner, retained offline HTTP requests, no browser/model dispatch."""
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
import numpy as np

from intent_browser.ax_explorer import AXConfig
from intent_browser.backend import ChatCompletionsBackend
from intent_browser.fact_provenance import digest, slice16
from intent_browser.harness import native_tools_profile, SemanticFeedback
from tests.runner_diagnostics import run_episode
from tests.test_ax_explorer import TOKENIZER, node, observation


@unittest.skipUnless(TOKENIZER.is_file(), 'Existing Qwen tokenizer required')
class RunnerFactTests(unittest.TestCase):
    def execute(self, enabled=False, provider_failure=False):
        requests=[];exports=[];actions=[]
        class Env:
            def obs(self):
                nodes=[node(0,'RootWebArea','Shop',[1]),node(1,'button','Price €29.90',bid=1)]
                nodes[0]['frameId']='real-frame'
                for n in nodes:n['backendDOMNodeId']=100+int(n['nodeId'])
                return {**observation(nodes),'goal':'Read the price','screenshot':np.zeros((2,2,3),dtype=np.uint8)}
            def reset(self,seed):return self.obs(),{}
            def step(self,action):actions.append(action);return self.obs(),0,False,False,{}
            def close(self):pass
        def provider(env,obs,context):
            exports.append(context)
            if provider_failure:raise RuntimeError('producer-only exception')
            return {'schema':'ax-fact-sources-v1','sources':[{'id':'real-export-id','text':'Price €29.90',
                'sha256':digest('Price €29.90'),'binding':{'snapshot_id':context['snapshot_id'],
                    'document_id':'real-document','frame_id':'real-frame','node_id':'1','field':'name'},
                'opaque_binding':{'state_id':'private-state-id'}}],
                'private_context':{'oracle':'private-fact-answer'},'mapping_inventory_complete':False}
        def transport(req):
            request=json.loads(req.content);requests.append(request)
            calls=([('ax_search',{'query':'Price','repeat':True}),('ax_search',{'query':'Price','repeat':True})]
                if len(requests)==1 else [('send_msg_to_user',{'text':'The price is €29.90.'})])
            return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant',
                'content':None,'tool_calls':[{'id':f'call-{len(requests)}-{i}','type':'function',
                'function':{'name':name,'arguments':json.dumps(args)}} for i,(name,args) in enumerate(calls)]}}],
                'usage':{'cost':0}})
        backend=ChatCompletionsBackend('https://offline.invalid/v1','mock')
        backend.client.close();backend.client=httpx.Client(transport=httpx.MockTransport(transport));self.addCleanup(backend.close)
        profile=replace(native_tools_profile(ax_config=AXConfig(str(TOKENIZER),incremental=True)),feedback_factory=SemanticFeedback)
        profile=replace(profile,tools=replace(profile.tools,batch_size=4))
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        with ExitStack() as stack:
            stack.enter_context(patch('intent_browser.runner.refresh_observation',side_effect=lambda e:e.obs()))
            stack.enter_context(patch('intent_browser.batching.document_signature',return_value=['stable-document']))
            path,summary=run_episode(lambda _:Env(),backend,{},temp.name,max_steps=3,harness_profile=profile,
                record_fact_provenance=enabled,fact_source_provider=provider)
        rows=[json.loads(l) for l in (path/'steps.jsonl').read_text().splitlines()]
        return path,summary,rows,requests,exports,actions

    def test_opt_out_installs_no_hooks_no_callback_no_artifacts(self):
        path,s,rows,req,exports,actions=self.execute()
        self.assertIsNone(s['error']);self.assertEqual(exports,[]);self.assertEqual(list(path.glob('fact-*')),[])
        self.assertNotIn('fact_recording',json.loads((path/'metadata.json').read_text()))

    def test_same_policy_bytes_and_batch_acknowledgments(self):
        _,old,oldrows,oldreq,_,oldactions=self.execute()
        path,s,rows,req,exports,actions=self.execute(True)
        self.assertIsNone(s['error']);self.assertEqual(req,oldreq);self.assertEqual(actions,oldactions)
        self.assertTrue(exports)
        self.assertNotIn('private-state-id',json.dumps(req));self.assertNotIn('private-fact-answer',json.dumps(req))
        first=json.loads((path/'fact-delivery.jsonl').read_text().splitlines()[0])
        self.assertEqual(first['step'],0);self.assertTrue(first['items'][0]['confirmed'])
        self.assertEqual(first['messages_sha256'],rows[0]['policy_delivery']['messages_sha256'])
        self.assertTrue(all(x['step'] in (0,1) for x in exports))
        members=rows[0]['batch_calls'];self.assertEqual(len(members),2)
        outputs=[m['fact_output_artifact'] for m in members]
        self.assertEqual(len(set(outputs)),2)
        confirmed=[i for i in rows[1]['policy_delivery']['items'] if i['kind']=='ax_result']
        self.assertEqual(len(confirmed),2)
        for item,output in zip(confirmed,outputs):
            content=json.loads((path/item['artifact']).read_text())
            recorded=json.loads((path/content['provenance']['fact_projection_artifact']).read_text())
            self.assertEqual(recorded['output_artifact'],output);self.assertTrue(recorded['projections'])
        deliveries=[json.loads(l) for l in (path/'fact-delivery.jsonl').read_text().splitlines()]
        self.assertTrue(all(i['confirmed'] for i in deliveries[-1]['items']))
        meta=json.loads((path/'metadata.json').read_text())
        self.assertTrue(meta['fact_recording']['enabled']);self.assertFalse(meta['fact_recording']['extra_ax_captures'])

    def test_source_failure_is_unknown_but_same_successful_episode(self):
        _,_,_,reference,_,_=self.execute()
        path,s,rows,req,exports,actions=self.execute(True,True)
        self.assertIsNone(s['error']);self.assertEqual(req,reference)
        for file in path.glob('fact-policy-*'):
            self.assertEqual(json.loads(file.read_text())['projections'],[])
        self.assertNotIn('producer-only exception',json.dumps(req))

    def test_existing_offline_consumer_rechecks_actual_retained_request(self):
        # Offline training consumer is a test-only dependency, not a runtime import.
        import sys
        training=str(Path(__file__).resolve().parents[1]/'training')
        sys.path.insert(0,training);self.addCleanup(lambda:sys.path.remove(training))
        from browser_training.fact_exposure import extract, object_digest, utf16_length
        path,s,rows,req,_,_=self.execute(True)
        capture=json.loads(sorted(path.glob('fact-capture-*'))[0].read_text())
        source=capture['sources'][0]
        assertion={'id':'synthetic.price','kind':'field_value','authority':'catalog_fact',
            'subject_id':'synthetic-product','field':'price','value':'29.90'}
        projections=[]
        for filename in path.glob('fact-policy-*'):
            entry=json.loads(filename.read_text())
            projections.extend(dict(p,content_id=entry['content_id']) for p in entry['projections'])
        manifest={'schema':'normalized-fact-exposure-v1','episode_id':path.name,
            'offset_unit':'utf16_code_units','states':[{'id':'synthetic-state','recorded_step':0,
            'values':{'price':'29.90'},'sha256':object_digest({'price':'29.90'})}],
            'sources':[src for f in path.glob('fact-capture-*') for src in json.loads(f.read_text())['sources']],
            'facts':[{'id':'synthetic-price','assertion':assertion,'site_id':'synthetic',
                'entity_id':'synthetic-product','state_id':'synthetic-state','required_parts':['statement'],
                'mapping_complete':True}],
            'publications':[{'id':'synthetic-publication','mapping_status':'complete',
                'formulation_id':'synthetic/price','metadata_sha256':'a'*64,'source_sha256':'b'*64,
                'assertions':[assertion]}],
            'occurrences':[{'id':'synthetic-occurrence','fact_id':'synthetic-price',
                'publication_id':'synthetic-publication','part':'statement',
                'spans':[{'source_id':source['id'],'start':0,'end':utf16_length(source['text'])}]}],
            'projection_complete_through_step':{'main':1},'projections':projections}
        result=extract(manifest,path,step=1)
        self.assertEqual(result['facts'][0]['status'],'complete')
        # Saved evidence is independently rechecked rather than trusting our receipt.
        first=json.loads((path/'steps.jsonl').read_text().splitlines()[0])
        first['model_request']['messages']=[{'role':'user','content':'different request'}]
        lines=(path/'steps.jsonl').read_text().splitlines();lines[0]=json.dumps(first)
        # Remove later receipt so corrupted original cannot borrow later exposure.
        (path/'steps.jsonl').write_text('\n'.join(lines)+'\n')
        (path/'policy-delivery.jsonl').write_text((path/'policy-delivery.jsonl').read_text().splitlines()[0]+'\n')
        result=extract(manifest,path,step=0)
        self.assertEqual(result['facts'][0]['status'],'unknown')

    def test_invalid_opt_in_fails_before_environment(self):
        for options in ({'record_fact_provenance':'yes'}, {'record_fact_provenance':True},
                        {'record_fact_provenance':True,'harness_profile':native_tools_profile(), 'fact_source_provider':4}):
            with self.subTest(options=options),self.assertRaises(ValueError):
                run_episode(lambda _:self.fail('environment started'),object(),{},**options)


if __name__=='__main__':unittest.main()
