"""Actual runner/HTTP mock transport, isolated in-memory environment; no browser."""
from contextlib import ExitStack
from dataclasses import replace
import ast
import json
from types import SimpleNamespace
from unittest.mock import patch

import httpx
import numpy as np
import pytest

from intent_browser.backend import ChatCompletionsBackend
from intent_browser.harness import native_tools_profile, with_clarification, SemanticFeedback
from intent_browser.runner import run_episode
from intent_browser.connected_world_task import ConnectedWorldTask
from environments.website_world import catalog_clarification as api
from environments.website_world.hidden_offer_grading import HiddenOfferGrader
from environments.website_world.test_hidden_offer_task import fixture, slot
from environments.website_world.test_listed_offer_grading import answer


def run_scripted(output,task,*,ask=True,search_before_ask=False,max_steps=5):
    requests = []; text,claims = answer()
    profile = with_clarification(replace(native_tools_profile(),feedback_factory=SemanticFeedback))
    episode = ConnectedWorldTask({'schema_version':'hidden-scripted-fixture-v1',
        'task_id':task['task_id'],'user_message':task['user_message'],'memories':task['memories'],
        'environment_context':{},'start_url':'http://fixture/'},origins=['http://fixture/'],
        profile_name=profile.name)
    class Env:
        def __init__(self):
            self.unwrapped = self
            self.chat = SimpleNamespace(messages=[])
        def obs(self):
            return {'goal':episode.policy_goal,'url':'http://fixture/', 'last_action_error':'',
                'axtree_object':{'nodes':[{'nodeId':'1','role':{'value':'StaticText'},'name':{'value':'[1] button Continue'}}]},
                'screenshot':np.zeros((2,2,3),dtype=np.uint8)}
        def reset(self,seed): return self.obs(),{}
        def step(self,action):
            call = ast.parse(action,mode='eval').body
            if call.func.id == 'send_msg_to_user':
                value = call.args[0] if call.args else next(k.value for k in call.keywords if k.arg == 'text')
                self.chat.messages.append({'role':'assistant','message':ast.literal_eval(value)})
            return self.obs(),0,False,False,{}
        def close(self): pass
    env = Env(); responder = api.Responder(task)
    plan = ([('click',{'bid':'1'})] if search_before_ask else [])
    plan += ([('ask_user',{'question':'Which shoe size do you wear?'})] if ask else [])
    plan += [('send_msg_to_user',{'text':text})]
    def transport(req):
        requests.append(json.loads(req.content)); name,args = plan[len(requests)-1]
        return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,
            'tool_calls':[{'id':'call-'+str(len(requests)),'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}}]})
    backend = ChatCompletionsBackend('https://offline.invalid/v1','scripted-personal-clarification')
    backend.client.close(); backend.client = httpx.Client(transport=httpx.MockTransport(transport))
    try:
        with ExitStack() as stack:
            stack.enter_context(patch('intent_browser.runner.observation_text',side_effect=lambda o:o['axtree_object']['nodes'][0]['name']['value']))
            stack.enter_context(patch('intent_browser.harness.flatten_axtree_to_str',side_effect=lambda x:x['nodes'][0]['name']['value']))
            stack.enter_context(patch('intent_browser.runner.refresh_observation',side_effect=lambda e:e.obs()))
            path,summary = run_episode(lambda _:env,backend,{'inference':'offline scripted transport','browser':'in-memory fixture'},
                output=output,max_steps=max_steps,harness_profile=profile,clarification_callback=responder,
                clarification_audit_id=responder.audit_id,episode_task=episode)
    finally: backend.close()
    return path,summary,requests,text,claims


def test_matching_reply_is_delivered_and_grades_with_native_outcome(tmp_path):
    w,t,r,b,i = fixture()
    path,summary,requests,text,claims = run_scripted(tmp_path,t)
    assert summary['stop_reason'] == 'agent_finished' and summary['error'] is None
    proof = api.evidence(path,t)
    assert proof['status'] == 'satisfied' and proof['clarification_delivered']
    assert len(proof['matched_callbacks']) == 1
    assert 'EU 42' not in json.dumps(requests[0]['messages'])
    assert 'For me, please use EU 42.' in json.dumps(requests[1]['messages'])
    assert api.Responder(t).audit_id not in json.dumps(requests)
    grade = HiddenOfferGrader(w,t,r,b,inventory=i,interaction_trace=path).grade(claims,text)
    assert grade['answer_outcome_correct'] and grade['structured_claims_correct']
    assert grade['check_details']['clarification_delivery_and_ordering']['supplied']['status'] == 'satisfied'


def test_correct_answer_without_question_fails_clarification_condition(tmp_path):
    w,t,r,b,i = fixture()
    path,summary,_,text,claims = run_scripted(tmp_path,t,ask=False)
    assert summary['stop_reason'] == 'agent_finished'
    grade = HiddenOfferGrader(w,t,r,b,inventory=i,interaction_trace=path).grade(claims,text)
    assert grade['answer_outcome_correct'] and not grade['structured_claims_correct']
    assert grade['clarification_evaluation']['status'] == 'not_satisfied'


@pytest.mark.parametrize('ordering,correct', [('before_search',False),('before_final_answer',True)])
def test_ordering_uses_retained_actions_not_callback_invocation_alone(tmp_path,ordering,correct):
    w,t,r,b,i = fixture(hidden_requirement=slot(ordering=ordering))
    path,summary,_,text,claims = run_scripted(tmp_path,t,search_before_ask=True)
    assert summary['stop_reason'] == 'agent_finished'
    grade = HiddenOfferGrader(w,t,r,b,inventory=i,interaction_trace=path).grade(claims,text)
    assert grade['clarification_evaluation']['clarification_delivered'] is True
    assert grade['structured_claims_correct'] is correct


def test_last_step_reply_is_saved_but_does_not_receive_delivery_credit(tmp_path):
    _,t,_,_,_ = fixture()
    path,summary,_,_,_ = run_scripted(tmp_path,t,max_steps=1)
    assert summary['stop_reason'] == 'max_steps'
    assert list(path.glob('clarification-*.json'))
    proof = api.evidence(path,t)
    assert proof['status'] == 'unknown' and proof['clarification_delivered'] is None


@pytest.mark.parametrize('corrupt', ['request','reply','span','artifact_path'])
def test_corrupt_saved_transport_binding_does_not_receive_credit(tmp_path,corrupt):
    _,t,_,_,_ = fixture(); path,_,_,_,_ = run_scripted(tmp_path,t)
    if corrupt == 'request':
        p = path/'steps.jsonl'; rows = [json.loads(s) for s in p.read_text().splitlines()]
        rows[1]['model_request']['messages'][0]['content'] += 'changed'
        p.write_text(''.join(json.dumps(r)+'\n' for r in rows))
    elif corrupt == 'reply':
        p = next(path.glob('clarification-*.json')); x = json.loads(p.read_text()); x['reply'] = 'EU 43.'; p.write_text(json.dumps(x))
    else:
        p = path/'policy-delivery.jsonl'; rows = [json.loads(s) for s in p.read_text().splitlines()]
        item = next(item for row in rows for item in row['items'] if item['kind'] == 'clarification_result')
        if corrupt == 'span': item['message_span']['end'] -= 1
        else: item['artifact'] = '../outside.json'
        p.write_text(''.join(json.dumps(r)+'\n' for r in rows))
    proof = api.evidence(path,t)
    assert proof['status'] != 'satisfied' and proof['clarification_delivered'] is not True


def test_late_source_mutation_rejects_before_grade(tmp_path):
    w,t,r,b,i = fixture(); path,_,_,text,claims = run_scripted(tmp_path,t)
    grader = HiddenOfferGrader(w,t,r,b,inventory=i,interaction_trace=path)
    (path/'steps.jsonl').write_text('changed')
    with pytest.raises(ValueError,match='source changed'): grader.grade(claims,text)
