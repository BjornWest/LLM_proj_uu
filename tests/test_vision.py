import base64
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import numpy as np
from intent_browser.vision import VisionConfig, VisionConversation, VisionSession, positioning
from intent_browser.native_tools import NativeBrowserTools
from intent_browser.backend import Completion, ChatCompletionsBackend
from intent_browser.actions import ACTION_NAMES, VISION_ACTION_NAMES, make_action_set
from intent_browser.policy_delivery import PolicyDelivery


def assistant(name, args=None, i=0):
    return {'role':'assistant','content':None,'tool_calls':[{'id':f'call-{i}','type':'function',
        'function':{'name':name,'arguments':json.dumps(args or {})}}]}

class VisionTests(unittest.TestCase):
    def setup_session(self, mode='agent'):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        c=VisionConversation();c.request('System','Goal','First')
        v=VisionSession(VisionConfig(mode),Path(tmp.name))
        obs={'screenshot':np.zeros((48,64,3),dtype=np.uint8)}
        r=v.capture(obs,c,0);c.record('',r,assistant_message=assistant('screenshot'))
        sent=c.request('System','Goal','Next')
        return c,v,r,sent

    def test_retain_append_prefix_and_exact_original(self):
        c,v,r,first=self.setup_session('retain')
        original=deepcopy(first)
        part=first[-1]['content'][1]
        data=base64.b64decode(part['image_url']['url'].split(',')[1])
        self.assertEqual(data,(v.directory/r['artifact']).read_bytes())
        result=v.release(r['image_id'],'notes',c);self.assertIn('error',result)
        c.record('',result,assistant_message=assistant('release_image',i=1))
        second=c.request('System','Goal','Later')
        self.assertEqual(second[:len(first)],original)
        self.assertTrue(v.delivery({'messages':second},True)[0]['acknowledged'])
        self.assertFalse(v.delivery({'messages':second},False)[0]['acknowledged'])

    def test_release_changes_only_image_part_not_prior_request(self):
        c,v,r,first=self.setup_session()
        original=deepcopy(first);result=v.release(r['image_id'],'blue squares',c)
        c.record('',result,assistant_message=assistant('release_image',i=1))
        second=c.request('System','Goal','Later')
        expected=deepcopy(first);expected[-1]['content'][1]={'type':'text','text':
            '[Image image-000 explicitly released from context. Agent notes: blue squares]'}
        self.assertEqual(second[:len(first)],expected)
        self.assertEqual(first,original)
        self.assertEqual(v.delivery({'messages':second},True),[])
        self.assertTrue((v.directory/r['artifact']).exists())
        self.assertIn('error',v.release(r['image_id'],'again',c))
        self.assertIn('error',v.release('missing','again',c))

    def test_definitions_fixed_and_arguments_validated(self):
        tools=NativeBrowserTools(names=ACTION_NAMES+VISION_ACTION_NAMES,vision_tools=True)
        before=tools.request_options()
        for name,args in [('screenshot',{}),('release_image',{'image_id':'image-000','keep_notes':'note'}),
                          ('scroll_into_view',{'bid':'4'})]:
            raw={'choices':[{'finish_reason':'tool_calls','message':assistant(name,args)}]}
            self.assertEqual(tools.parse_completion(Completion('',raw))[0].name,name)
        self.assertEqual(before,tools.request_options())
        bad={'choices':[{'finish_reason':'tool_calls','message':assistant('release_image',{'image_id':'x'})}]}
        with self.assertRaises(Exception):tools.parse_completion(Completion('',bad))
        self.assertNotIn('screenshot',[d['function']['name'] for d in NativeBrowserTools().definitions()])

    def test_scroll_timeout_configured_without_click(self):
        code=make_action_set(ACTION_NAMES+VISION_ACTION_NAMES).to_python_code("scroll_into_view('1')")
        self.assertIn('scroll_into_view_if_needed(timeout=5000)',code)

    def test_text_only_backend_rejects_before_http(self):
        b=ChatCompletionsBackend('https://offline.invalid','text-only');self.addCleanup(b.close)
        with self.assertRaisesRegex(ValueError,'image input'):
            b.complete([{'role':'tool','content':[{'type':'image_url','image_url':{'url':'data:image/png;base64,AA=='}}]}])
        self.assertFalse(hasattr(b,'last_request'))

    def test_profile_modes_have_identical_tool_schema(self):
        from intent_browser.harness import native_tools_profile
        from intent_browser.ax_explorer import AXConfig
        cfg=AXConfig('training/.cache/qwen38-tokenizer/tokenizer.json',incremental=True)
        modes=[native_tools_profile(ax_config=cfg,vision_config=VisionConfig(mode)) for mode in ('retain','agent')]
        self.assertEqual(modes[0].tools.request_options(),modes[1].tools.request_options())
        self.assertEqual(modes[0].describe()['vision']['retention'],'retain')

    def test_invalid_config(self):
        with self.assertRaises(ValueError):VisionConfig('automatic')

    def test_position_states(self):
        for ratio,want in [(1,'in_viewport'),(.5,'partially_in_viewport'),(0,'outside_viewport'),(None,'unknown')]:
            self.assertEqual(positioning({'extra_element_properties':{'1':{'visibility':ratio}}},'1')['status'],want)

    def test_text_binding_in_multimodal_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            class Trace:
                directory=Path(tmp)
                def event(self,*a,**kw): pass
            d=PolicyDelivery(Trace())
            sid=d.register('vision_result','exact evidence',step=0)
            event={'step':1,'model_request':{'messages':[{'role':'tool','content':[
                {'type':'text','text':'prefix exact evidence suffix'},
                {'type':'image_url','image_url':{'url':'data:image/png;base64,AA=='}}]}]}}
            record=d.record(event,[{'content_id':sid,'message_index':0,'start':7,'end':21}],acknowledged=True)
            self.assertTrue(record['items'][0]['confirmed'])

if __name__=='__main__':unittest.main()
