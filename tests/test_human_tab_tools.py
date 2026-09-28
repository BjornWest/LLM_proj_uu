import json
import os
from unittest.mock import patch
import unittest
from jsonschema.exceptions import ValidationError
from intent_browser.backend import Completion
from intent_browser.open_internet import (open_profile, with_human_handover,
    HUMAN_VERIFICATION_TEST_POLICY, HUMAN_VERIFICATION_WAIT_POLICY,
    HUMAN_VERIFICATION_RECOGNITION_POLICY)
from intent_browser.harness import native_tools_profile
from dataclasses import replace

class HumanTabToolsTests(unittest.TestCase):
    def tools(self):
        p=open_profile(native_tools_profile())
        return with_human_handover(replace(p,tools=replace(p.tools,batch_size=4))).tools

    def call(self,name,args):
        return Completion('',{'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
            'tool_calls':[{'id':'call-1','type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}}]})

    def test_opt_in_stable_schema(self):
        tools=self.tools();defs={d['function']['name']:d['function'] for d in tools.definitions()}
        self.assertEqual(defs['tab_focus']['parameters']['required'],['tab_id'])
        self.assertIn('handover_tab',defs)
        for name,args in [('handover_tab',{'tab_id':'tab-1','reason':'Human verification'}),('tab_focus',{'tab_id':'tab-2'})]:
            d,_=tools.parse_completion(self.call(name,args));self.assertEqual(d.arguments,args)
        with self.assertRaises(ValidationError):tools.parse_completion(self.call('tab_focus',{'index':0}))
        ordinary=open_profile(native_tools_profile()).tools
        self.assertNotIn('handover_tab',[d['function']['name'] for d in ordinary.definitions()])
        d,_=ordinary.parse_completion(self.call('tab_focus',{'index':0}));self.assertEqual(d.arguments,{'index':0})

    def test_yield_last_in_batch(self):
        c=self.call('handover_tab',{'tab_id':'tab-1','reason':'Please help'})
        c.raw['choices'][0]['message']['tool_calls'].append({'id':'call-2','type':'function','function':{'name':'noop','arguments':'{}'}})
        with self.assertRaisesRegex(ValueError,'handover_tab must be'):self.tools().parse_batch(c)

    def test_verification_testing_policy_is_handover_only(self):
        base=native_tools_profile()
        ordinary=open_profile(replace(base,tools=replace(base.tools,batch_size=4)))
        original_instructions=ordinary.instructions
        profile=with_human_handover(ordinary)
        self.assertNotIn(HUMAN_VERIFICATION_TEST_POLICY,base.instructions)
        self.assertNotIn(HUMAN_VERIFICATION_TEST_POLICY,ordinary.instructions)
        self.assertEqual(ordinary.instructions,original_instructions)
        self.assertEqual(profile.instructions.count(HUMAN_VERIFICATION_TEST_POLICY),1)
        self.assertIn(HUMAN_VERIFICATION_TEST_POLICY,profile.describe()['instructions'])
        self.assertIn('Keep the verification tab open',profile.instructions)
        self.assertIn('reuse it instead of creating another',profile.instructions)

    def test_cli_uses_same_controller_and_current_capture_selection(self):
        from intent_browser.cli import main
        argv=['intent-browser','run','--open-internet','--human-handover','--headful','--no-subagents',
              '--url','https://example.test/','--goal','Information only','--no-preview',
              '--model','offline','--base-url','http://localhost:9990/v1']
        with patch('sys.argv',argv),patch.dict(os.environ,{},clear=True), \
             patch('intent_browser.cli.ChatCompletionsBackend'), \
             patch('intent_browser.human_handover_ui.HumanHandoverUI') as panel, \
             patch('intent_browser.cli.run_episode',return_value=('unused',{'error':None})) as run:
            main()
        kwargs=run.call_args.kwargs
        self.assertIs(panel.call_args.args[0],kwargs['human_handover'])
        self.assertIs(panel.return_value,kwargs['human_handover_ui'])
        self.assertEqual(kwargs['observation_pipeline'],'auto')
        self.assertTrue(kwargs['harness_profile'].tools.stable_frame_capture)
        self.assertTrue(kwargs['harness_profile'].tools.human_handover_tools)
        self.assertIsNone(kwargs['harness_profile'].agent_limits)
        self.assertNotIn('before_observation',kwargs)
        panel.return_value.close.assert_called_once()

    def test_recognized_challenge_requires_immediate_handover_in_both_modes(self):
        base=native_tools_profile()
        ordinary=open_profile(replace(base,tools=replace(base.tools,batch_size=4)))
        before=ordinary.describe()
        for wait in (False,True):
            with self.subTest(wait_for_human=wait):
                profile=with_human_handover(ordinary,wait_for_human=wait)
                text=profile.describe()['instructions']
                self.assertEqual(text.count(HUMAN_VERIFICATION_RECOGNITION_POLICY),1)
                for required in ('a title alone is not sufficient evidence',
                    'request handover_tab immediately', 'no checkbox is yet visible',
                    'Do not first use noop/wait, reload',
                    'Waiting for the human begins after requesting handover',
                    'If page evidence is insufficient, inspect it'):
                    self.assertIn(required,text)
                self.assertIn('+verification-prompt-v2',profile.name)
                self.assertEqual(profile.tools.human_handover_wait,wait)
                if wait:
                    self.assertIn(HUMAN_VERIFICATION_WAIT_POLICY,text)
                    self.assertNotIn(HUMAN_VERIFICATION_TEST_POLICY,text)
                    self.assertNotIn('then continue in another tab',text)
                    self.assertIn('Do not open another tab',text)
                else:
                    self.assertIn(HUMAN_VERIFICATION_TEST_POLICY,text)
                    self.assertNotIn(HUMAN_VERIFICATION_WAIT_POLICY,text)
                    self.assertIn('reuse it instead of creating another',text)
        self.assertEqual(ordinary.describe(),before)
        self.assertNotIn(HUMAN_VERIFICATION_RECOGNITION_POLICY,ordinary.instructions)
        self.assertNotIn(HUMAN_VERIFICATION_RECOGNITION_POLICY,base.instructions)

    def test_runner_rejects_missing_or_disabled_controller_before_browser(self):
        from intent_browser.runner import run_episode
        from intent_browser.human_handover import HumanHandoverController
        from intent_browser.observation_pipeline import ObservationPipelineConfig
        from intent_browser.ax_explorer import AXConfig
        from intent_browser.standard_profile import tokenizer_path
        p=with_human_handover(open_profile(native_tools_profile(parallel_tool_calls=None,compact_feedback=True,
            ax_config=AXConfig(tokenizer_path(),incremental=True),batch_size=8)))
        for profile,controller in [(p,None),(native_tools_profile(),HumanHandoverController())]:
            with self.assertRaises(ValueError):
                run_episode(lambda _:self.fail('Created browser'),object(),{},harness_profile=profile,
                    human_handover=controller,observation_pipeline=ObservationPipelineConfig((),full_capture_only=True))
