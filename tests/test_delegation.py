import json
import tempfile
import unittest
from pathlib import Path
from intent_browser.backend import Completion
from intent_browser.harness import native_tools_profile,with_subagents
from intent_browser.delegation import AgentLimits,AgentRuntime

class FakeBackend:
    supports_images=True
    def __init__(self):self.request_options={};self.session_id=None;self.records=[]
    def configure_tools(self,options):self.request_options.update(options)
    def begin_episode(self,ident):self.session_id=ident;return {'session_id':ident}
    def complete(self,messages):
        self.last_request={'messages':messages,'session_id':self.session_id,**self.request_options}
        self.records.append(self.last_request)
        return Completion('ok',{'answer':'ok'},self.last_request)

class DelegationTests(unittest.TestCase):
    def test_registry_inherits_except_spawn(self):
        from dataclasses import replace
        p=with_subagents(native_tools_profile(parallel_tool_calls=None,compact_feedback=True))
        parent=p.tools.definitions(allow_search=True)
        child=replace(p.tools,allow_spawn=False).definitions(allow_search=True)
        self.assertEqual(child,[d for d in parent if d['function']['name']!='spawn_agent'])
        self.assertEqual(p.agent_limits.max_active,2)
    def test_request_isolation_and_shared_limit(self):
        b=FakeBackend();r=AgentRuntime(b,AgentLimits(total_model_calls=2),None)
        def root(a):
            v=a['backend'];v.configure_tools({'tools':['root'],'tool_choice':'auto'});v.begin_episode('root-session')
            def helper(h):
                c=h['backend'];c.configure_tools({'tools':['child'],'tool_choice':'auto'});c.begin_episode('child-session')
                r.before_observation(h);return c.complete([{'role':'user','content':'child'}])
            h=r.add(helper,parent=a['id'],browser='none')
            r.before_observation(a);v.complete([{'role':'user','content':'parent'}])
            r.suspend(('wait',h['id'],float('inf')))
            self.assertEqual(h['state'],'finished')
            r.before_observation(a)
            with self.assertRaisesRegex(ValueError,'Shared'):v.complete([])
        r.run(root)
        self.assertEqual([q['session_id'] for q in b.records],['root-session','child-session'])
        self.assertEqual([q['tools'] for q in b.records],[['root'],['child']])
        self.assertEqual(b.request_options['tools'],['root'])
    def test_schema_and_launch_bound(self):
        p=with_subagents(native_tools_profile(parallel_tool_calls=None,compact_feedback=True))
        raw={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','tool_calls':[{'type':'function','id':'x','function':{'name':'spawn_agent','arguments':json.dumps({'task':'Inspect evidence','browser':'none'})}}]}}]}
        d,_=p.tools.parse_batch(Completion('',raw));self.assertEqual(d[0].name,'spawn_agent')
        raw['choices'][0]['message']['tool_calls'][0]['function']['arguments']='{"task":"x","browser":"parent"}'
        with self.assertRaises(Exception):p.tools.parse_batch(Completion('',raw))

if __name__=='__main__':unittest.main()

class LifecycleTests(unittest.TestCase):
    def test_cancel_retains_late_response_but_blocks_next_action(self):
        import threading
        entered=threading.Event();release=threading.Event()
        class Slow(FakeBackend):
            def complete(self,messages):
                entered.set();release.wait(5)
                return super().complete(messages)
        b=Slow();r=AgentRuntime(b,AgentLimits(),None)
        def root(a):
            a['backend'].configure_tools({'tools':['parent']})
            def helper(h):
                v=h['backend'];v.configure_tools({'tools':['child']});v.begin_episode('child')
                r.before_observation(h);answer=v.complete([{'role':'user','content':'retained'}])
                self.assertEqual(answer.text,'ok')
                self.assertEqual(v.last_request['session_id'],'child')
                with self.assertRaisesRegex(RuntimeError,'cancelled'):r.guard(h)
            h=r.add(helper,parent=a['id'],browser='none')
            # Let the child submit; cancellation does not terminate transport.
            while not entered.is_set():r.suspend(('wait',h['id'],0))
            h['cancelled']=True;release.set()
            r.suspend(('wait',h['id'],float('inf')))
            self.assertEqual(h['state'],'cancelled')
        r.run(root);self.assertEqual(len(b.records),1)
    def test_invalid_limits(self):
        for value in (True,float('inf'),float('nan'),0,-1):
            with self.assertRaises(ValueError):AgentLimits(child_seconds=value)
    def test_action_notices_have_no_foreign_bids_or_private_state(self):
        r=AgentRuntime(FakeBackend(),AgentLimits(),None)
        try:
            a={'id':'root'};r.action_notice({'id':'child'},'click','http://local/','')
            notice=r.notices(a)
            self.assertEqual(notice['other_agent_actions'][0]['tool'],'click')
            self.assertNotIn('bid',json.dumps(notice));self.assertIsNone(r.notices(a))
        finally:r.pool.shutdown()

class StandardTests(unittest.TestCase):
    def test_composable_standard(self):
        from intent_browser.standard_profile import standard_profile
        p=standard_profile(navigation_origins=('http://localhost:9000',))
        self.assertEqual(p.name,'core-tools-v12-ax-reuse')
        self.assertEqual(p.tools.batch_size,8)
        self.assertEqual(p.tools.reasoning_replay,'preserve')
        self.assertTrue(p.ax_config.incremental)
        self.assertEqual(p.vision_config.retention,'retain')
        self.assertIn('goto',p.tools.names)
        self.assertIn('spawn_agent',p.describe()['tools'])
        self.assertIsNone(standard_profile(helpers=False).agent_limits)

class BudgetIntegrationTests(unittest.TestCase):
    def test_two_sessions_one_real_reservation_ledger(self):
        from tests.test_native_probe_budget import BudgetTests
        helper=BudgetTests();self.addCleanup(helper.doCleanups)
        sent=[]
        b,path,cfg=helper.make(lambda req:sent.append(json.loads(req.content)) or helper.response(),
            carried_usd='0',cap_usd='.25',settle_reported_cost=True)
        # Start with the same native registry as the budget backend's configure.
        opts=dict(b.request_options)
        opts={k:v for k,v in opts.items() if k in ('tools','tool_choice','parallel_tool_calls')}
        r=AgentRuntime(b,AgentLimits(total_model_calls=2),None,hook=b.wait_until_ready)
        def root(a):
            v=a['backend'];v.configure_tools(opts);v.begin_episode('parent')
            def child(h):
                c=h['backend'];c.configure_tools(opts);c.begin_episode('helper')
                r.before_observation(h);return c.complete([{'role':'user','content':'helper question'}])
            h=r.add(child,parent=a['id'],browser='none')
            r.before_observation(a);v.complete([{'role':'user','content':'parent question'}])
            r.suspend(('wait',h['id'],float('inf')))
            self.assertEqual(h['state'],'finished',h.get('error'))
        r.run(root)
        ledger=json.loads(path.read_text())
        self.assertEqual([x['session_id'] for x in sent],['parent','helper'])
        self.assertEqual([x['model_request'] for x in ledger['requests']],sent)
        self.assertEqual(ledger['reported_cost_usd'],'0.002')
        self.assertEqual(ledger['unresolved_reserved_usd'],'0')
