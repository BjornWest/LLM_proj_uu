import json
import tempfile
import threading
import time
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from intent_browser.ax_context import AXContext
from intent_browser.ax_explorer import AXConfig
from intent_browser.standard_profile import tokenizer_path
from intent_browser.backend import Completion
from intent_browser.observation_pipeline import (ObservationPipeline, ObservationPipelineConfig,
    ObservationChanged, PartialFeedback, ax_node_signature)
from intent_browser.harness import SemanticFeedback, native_tools_profile
from intent_browser.runner import run_episode
from intent_browser.trace import Trace


def obs(name='Original'):
    return {'url':'http://fixture/','last_action_error':'','open_pages_urls':['http://fixture/'],
        'axtree_object':{'nodes':[
            {'nodeId':'root','backendDOMNodeId':1,'role':{'value':'RootWebArea'},'name':{'value':'Page'},'childIds':['a']},
            {'nodeId':'a','backendDOMNodeId':2,'browsergym_id':'7','role':{'value':'button'},'name':{'value':name},'childIds':[]}]}}


class PipelineTests(unittest.TestCase):
    def test_only_negative_layout_id_churn_is_normalized(self):
        a={'nodeId':'4','backendDOMNodeId':4,'childIds':['-123','5'],'name':{'value':'-123'}}
        b=deepcopy(a);b['childIds'][0]='-456'
        self.assertEqual(ax_node_signature(a),ax_node_signature(b))
        for key,value in [('backendDOMNodeId',9),('childIds',['-456','6']),('childIds',['-456']),
                          ('name',{'value':'Changed'}),('nodeId','7')]:
            changed={**b,key:value}
            self.assertNotEqual(ax_node_signature(a),ax_node_signature(changed))

    def test_preview_does_not_prune_or_acknowledge_omitted_nodes(self):
        ax=AXContext(AXConfig(tokenizer_path(),incremental=True))
        full=obs();ax.prepare_observation(full);ax.acknowledge()
        ref=next(ax.ref(i) for i,n in enumerate(ax.nodes) if n['bid']=='7')
        states=deepcopy(ax._states);seen=deepcopy(ax.seen)
        preview=obs();preview['axtree_object']['nodes']=preview['axtree_object']['nodes'][:1]
        preview['observation_capture']={'coverage':'partial'}
        value=json.loads(ax.prepare_observation(preview));ax.acknowledge()
        self.assertEqual(value['coverage'],'partial');self.assertEqual(ax._states,states)
        self.assertEqual(ax.seen,seen);self.assertIsNotNone(ax.resolve(ref))
        ax.capture(obs('Changed'));self.assertEqual(ax.ref(ax.resolve(ref)),ref)
        self.assertEqual(ax.nodes[ax.resolve(ref)]['name'],'Changed')

    def test_partial_feedback_does_not_report_fake_removals(self):
        wrapped=PartialFeedback(SemanticFeedback());before=wrapped.before_action(None,obs())
        preview=obs();preview['axtree_object']['nodes']=preview['axtree_object']['nodes'][:1]
        preview['observation_capture']={'coverage':'partial'}
        result=wrapped.after_action(None,before,preview)
        self.assertNotIn('removed_or_changed',result)
        self.assertIn('Partial AX',result['event_capture']['warnings'][0])

    def controller(self,prefetch):
        p=ObservationPipeline.__new__(ObservationPipeline)
        p.pending={'present':True};p.pool=None;p.prefetch=prefetch;p.dynamic=None
        self.addCleanup(lambda:p.pool.shutdown(wait=True) if p.pool else None)
        return p

    def test_overlap_keeps_browser_on_owner_and_retains_response_after_capture_failure(self):
        owner=threading.get_ident();entered=threading.Event();release=threading.Event();threads=[]
        completion=Completion('',{'usage':{'cost':.001}}, {'messages':[]})
        class Backend:
            supports_background_completion=True
            def complete(self,messages):
                threads.append(threading.get_ident());entered.set();release.wait(3);return completion
        def prefetch():
            self.assertEqual(threading.get_ident(),owner)
            self.assertTrue(entered.wait(2));release.set();raise RuntimeError('Capture failed')
        p=self.controller(prefetch);event={}
        result=p.complete(Backend(),[],event)
        self.assertIs(result,completion);self.assertNotEqual(threads,[owner])
        self.assertIn('Capture failed',event['observation_pipeline']['background_error'])
        self.assertIn('backend_completion_seconds',event['observation_pipeline'])

    def test_undeclared_subclass_is_sequential_and_capture_failure_prevents_dispatch(self):
        order=[]
        class Base:
            supports_background_completion=True
            def complete(self,messages):order.append('model');return Completion('',{})
        class Wrapper(Base):pass
        def prefetch():order.append('full');return None
        event={};self.controller(prefetch).complete(Wrapper(),[],event)
        self.assertEqual(order,['full','model']);self.assertFalse(event['observation_pipeline']['overlapped'])
        def fail():raise RuntimeError('No AX')
        order.clear()
        with self.assertRaises(ObservationChanged):self.controller(fail).complete(Wrapper(),[],{})
        self.assertEqual(order,[])

    def test_model_error_identity_is_not_masked_by_background_error(self):
        error=RuntimeError('HTTP failed');error.request_payload={'messages':['retained']}
        class Backend:
            supports_background_completion=True
            def complete(self,messages):raise error
        def fail():raise RuntimeError('No AX')
        event={}
        with self.assertRaises(RuntimeError) as caught:self.controller(fail).complete(Backend(),[],event)
        self.assertIs(caught.exception,error);self.assertIn('No AX',event['observation_pipeline']['background_error'])

    def test_dynamic_mode_records_actual_preview_bid_version(self):
        from types import SimpleNamespace
        class Backend:
            supports_background_completion=True
            def complete(self,messages):return Completion('',{})
        for enabled,version in ((False,'v1'),(True,'v2')):
            with self.subTest(preview_bids=enabled):
                p=self.controller(lambda:None)
                p.dynamic=SimpleNamespace(pending={'present':True},preview_bids=enabled)
                event={};p.complete(Backend(),[],event)
                self.assertEqual(event['observation_pipeline']['mode'],f'dynamic-main-preview-{version}')

    def test_unchanged_revision_reuses_full_but_changed_revision_rejects_pending_decision(self):
        p=self.controller(lambda:None);p.cache={'stamp':{'revision':1},'tree':{'nodes':[]}}
        p.stamp=lambda:{'revision':2}
        with self.assertRaises(ObservationChanged):p.full_after_completion()

    def test_pending_stale_preview_does_not_recapture_silently(self):
        p=ObservationPipeline.__new__(ObservationPipeline);p.pending={'stamp':{'revision':1}};p.dynamic=None
        p.stamp=lambda:{'revision':2}
        with self.assertRaises(ObservationChanged):p.prefetch()

    def test_trace_missing_recording_is_explicit_not_fake_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace=Trace(tmp,{})
            value=obs();value['screenshot']=None
            artifact=trace.observation(0,value,'partial',phase='background')
            self.assertIsNone(artifact['screenshot']);self.assertFalse(list(trace.directory.glob('*.png')))
            self.assertTrue((trace.directory/artifact['raw']).is_file())
            trace.finish({'stop_reason':'test'})

    def test_guard_rejects_unsupported_profile_before_environment(self):
        with self.assertRaisesRegex(ValueError,'incremental native'):
            run_episode(lambda _:self.fail('Environment created'),object(),{},harness_profile=native_tools_profile(),
                observation_pipeline=ObservationPipelineConfig(('http://fixture',)))

if __name__=='__main__':unittest.main()
