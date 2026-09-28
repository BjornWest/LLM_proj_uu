import json
import unittest
from unittest.mock import patch
from tests import test_decision_retry as retry_fixtures
from jsonschema import ValidationError
from intent_browser.backend import Completion
from intent_browser.completion_diagnostics import completion_diagnostic
from intent_browser.native_tools import NativeBrowserTools, FINAL_MESSAGE_CHAR_LIMIT
from intent_browser.retry_policy import DecisionRetryPolicy
from tests.test_native_tools import response, completion

class CompletionLimitTests(unittest.TestCase):
    def test_long_final_and_unicode_escape_roundtrip(self):
        tools=NativeBrowserTools()
        for text in ('Detailed result. '*600, '😀'*FINAL_MESSAGE_CHAR_LIMIT):
            with self.subTest(length=len(text)):
                decision,assistant=tools.parse_completion(completion(response('send_msg_to_user',{'text':text})))
                self.assertEqual(decision.arguments,{'text':text})
                self.assertEqual(json.loads(assistant['tool_calls'][0]['function']['arguments'])['text'],text)

    def test_message_schema_bound_and_other_limits_retained(self):
        tools=NativeBrowserTools()
        with self.assertRaises(ValidationError):
            tools.parse_completion(completion(response('send_msg_to_user',{'text':'a'*(FINAL_MESSAGE_CHAR_LIMIT+1)})))
        with self.assertRaisesRegex(ValueError,'encoding or size'):
            tools.parse_completion(completion(response('fill',{'bid':'1','value':'a'*5000})))
        with self.assertRaises(ValidationError):
            tools.parse_completion(completion(response('send_msg_to_user',{'text':'Done','extra':True})))

    def test_bad_json_at_cap_is_probable_despite_tool_calls_finish(self):
        raw=response('send_msg_to_user',{'text':'test'})
        raw['choices'][0]['native_finish_reason']='tool_calls'
        raw['choices'][0]['message']['tool_calls'][0]['function']['arguments']='{"text":"Incomplete'
        raw['usage']={'completion_tokens':4096,'completion_tokens_details':{'reasoning_tokens':3438}}
        request={'max_tokens':4096}
        evidence=completion_diagnostic(raw,request)
        self.assertEqual(evidence['kind'],'probable_output_truncation')
        self.assertEqual(evidence['reasoning_tokens'],3438)
        try:NativeBrowserTools().parse_completion(Completion('',raw,request))
        except json.JSONDecodeError as error:
            self.assertIsNone(DecisionRetryPolicy().select(error,'action_parse',
                {'model_response':raw,'model_request':request},used=0,remaining_calls=10))
        else:self.fail('Truncated JSON was accepted')

    def test_valid_call_at_cap_still_executes_and_lower_usage_can_recover(self):
        raw=response('send_msg_to_user',{'text':'Done'});raw['usage']={'completion_tokens':4096}
        request={'max_tokens':4096}
        self.assertEqual(completion_diagnostic(raw,request)['kind'],'output_limit_reached')
        self.assertEqual(NativeBrowserTools().parse_completion(Completion('',raw,request))[0].name,'send_msg_to_user')
        raw['usage']['completion_tokens']=100
        raw['choices'][0]['message']['tool_calls'][0]['function']['arguments']='{"text":"Incomplete'
        self.assertIsNone(completion_diagnostic(raw,request))
        try:NativeBrowserTools().parse_completion(Completion('',raw,request))
        except json.JSONDecodeError as error:
            self.assertEqual(DecisionRetryPolicy().select(error,'action_parse',
                {'model_response':raw,'model_request':request},used=0,remaining_calls=10)['reason'],'invalid_tool_arguments')

    def test_runner_retains_classification_without_replaying_or_losing_response(self):
        harness=retry_fixtures.DecisionRetryTests();self.addCleanup(harness.doCleanups)
        raw=response('send_msg_to_user',{'text':'x'})
        raw['choices'][0]['message']['tool_calls'][0]['function']['arguments']='{"text":"Cut'
        # The test backend is a local endpoint with an explicit default128.
        raw['usage']={'completion_tokens':128}
        with patch('tests.test_decision_retry.reply',return_value=raw):
            env,requests,steps,result,_=harness.run_case()
        self.assertEqual(len(requests),1);self.assertEqual(env.count,0)
        self.assertEqual(result['decision_retry_count'],0)
        self.assertEqual(steps[0]['completion_diagnostic']['kind'],'probable_output_truncation')
        self.assertEqual(steps[0]['model_response'],raw)

    def test_runner_delivers_long_complete_terminal_once(self):
        harness=retry_fixtures.DecisionRetryTests();self.addCleanup(harness.doCleanups)
        text='Detailed final answer. '*500
        with patch('tests.test_decision_retry.reply',return_value=response('send_msg_to_user',{'text':text})):
            env,requests,steps,result,_=harness.run_case()
        self.assertEqual(len(requests),1);self.assertEqual(env.count,1)
        self.assertIsNone(result['error']);self.assertEqual(result['stop_reason'],'agent_finished')
        self.assertIn(repr(text),steps[0]['action'])

    def test_length_and_unknown_usage(self):
        raw=response();raw['choices'][0]['finish_reason']='length'
        self.assertEqual(completion_diagnostic(raw,None)['kind'],'reported_incomplete_output')
        raw['choices'][0]['finish_reason']='tool_calls'
        self.assertIsNone(completion_diagnostic(raw,None))

if __name__=='__main__':unittest.main()
