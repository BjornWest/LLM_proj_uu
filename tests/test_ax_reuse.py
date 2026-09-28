"""Revisit matching and policy-controlled automatic AX, without inference."""
from copy import deepcopy
from dataclasses import replace
import json
import unittest

from intent_browser.ax_context import AXContext
from intent_browser.ax_explorer import AXConfig, encoded
from intent_browser.harness import native_tools_profile
from intent_browser.standard_profile import standard_profile
from tests.test_ax_explorer import TOKENIZER, node, observation
from tests.test_native_tools import completion, response


@unittest.skipUnless(TOKENIZER.is_file(), 'Local tokenizer required')
class ReuseTests(unittest.TestCase):
    def fixture(self, **kwargs):
        nodes=[node(0,'RootWebArea','Store',[1,2]),
               node(1,'button','A long distinctive product description '*24,bid=11),
               node(2,'checkbox','Marketing',bid=12)]
        for i,n in enumerate(nodes): n['backendDOMNodeId']=100+i
        return AXContext(AXConfig(str(TOKENIZER),incremental=True,revisit_reuse=True,
                                 agent_overview=True,**kwargs)), observation(nodes)

    def deliver(self,x,o):
        result=json.loads(x.prepare_observation(o));x.acknowledge();return result

    def revisit(self,x,o):
        other=deepcopy(o);other['url']='http://fixture/other'
        self.deliver(x,other)
        returned=deepcopy(o)
        for n in returned['axtree_object']['nodes']:
            if 'backendDOMNodeId' in n:n['backendDOMNodeId']+=1000
            if 'browsergym_id' in n:n['browsergym_id']='new-'+n['browsergym_id']
        return returned

    def test_revisit_uses_delivered_descriptions_and_current_handles(self):
        x,o=self.fixture();first=self.deliver(x,o);oldref=first['items'][1]['ref']
        returned=self.revisit(x,o);current=self.deliver(x,returned)
        self.assertTrue(all('reused_from' in i for i in current['items']))
        self.assertLess(x.tokens(encoded(current)),x.tokens(encoded(first)))
        item=current['items'][1]
        self.assertEqual(item['reused_from'],oldref)
        self.assertEqual(item['bid'],'new-11')
        self.assertNotEqual(item['ref'],oldref)
        with self.assertRaisesRegex(ValueError,'Stale'): x.resolve(oldref)
        self.assertEqual(x.resolve(item['ref']),1)
        self.assertNotIn('reused_from',encoded(x.search('Marketing',repeat=True)))

    def test_url_equality_never_hides_content_state_or_structure_change(self):
        for kind in ('text','checked','order','descendant','url'):
            with self.subTest(kind=kind):
                x,o=self.fixture();self.deliver(x,o);returned=self.revisit(x,o)
                nodes=returned['axtree_object']['nodes']
                if kind=='text':nodes[1]['name']['value']+=' changed'
                if kind=='checked':nodes[2]['properties']=[{'name':'checked','value':{'value':True}}]
                if kind=='order':nodes[0]['childIds'].reverse()
                if kind=='descendant':nodes[0]['childIds'].append('3');nodes.append(node(3,'button','New'))
                if kind=='url':returned['url']+='different'
                self.assertNotIn('reused_from',encoded(self.deliver(x,returned)))

    def test_unacknowledged_or_trace_only_content_not_reused(self):
        for mode in ('trace','pending','discard'):
            with self.subTest(mode=mode):
                x,o=self.fixture()
                if mode=='trace':x.overview(o)
                else:x.prepare_observation(o)
                if mode=='discard':x.discard_pending()
                self.assertNotIn('reused_from',encoded(self.deliver(x,self.revisit(x,o))))

    def test_only_delivered_subset_reused_and_partial_still_expandable(self):
        x,o=self.fixture(overview_tokens=512)
        o['axtree_object']['nodes'][0]['childIds']=[str(i) for i in range(1,50)]
        o['axtree_object']['nodes'].extend(node(i,'button',f'Unseen {i}',bid=i) for i in range(3,50))
        first=self.deliver(x,o);known={i['ref'] for i in first['items']}
        self.assertLess(len(known),50)
        returned=self.revisit(x,o);x.capture(returned)
        result=x.page_update(repeat=False,budget=4000)
        self.assertTrue(all(i['reused_from'] in known for i in result['items'] if 'reused_from' in i))
        self.assertTrue(any('name' in i for i in result['items']))
        x.acknowledge();long=x.read(x.ref(1),view='node')
        self.assertIn('text',long)  # earlier 60-token preview was not full text

    def test_explicit_context_reset_drops_reuse(self):
        x,o=self.fixture();self.deliver(x,o);returned=self.revisit(x,o)
        x.reset_delivery()
        self.assertNotIn('reused_from',encoded(self.deliver(x,returned)))

    def test_omission_does_not_acknowledge_changes_and_errors_survive(self):
        x,o=self.fixture();self.deliver(x,o)
        o['axtree_object']['nodes'][2]['name']['value']='Changed marketing'
        o['last_action_error']='TimeoutError: element could not be clicked'
        x.request_overview(0);omitted=self.deliver(x,o)
        self.assertTrue(omitted['ax_nodes_omitted']);self.assertEqual(omitted['items'],[])
        self.assertIn('Timeout',omitted['last_action_error'])
        self.assertNotIn('visited_content_unchanged',omitted)
        self.assertIn('Changed marketing',encoded(x.execute('ax_changes',{})))

    def test_choice_one_shot_trace_capture_does_not_consume_it(self):
        x,o=self.fixture();x.request_overview(0);x.overview(o)
        self.assertTrue(self.deliver(x,o)['ax_nodes_omitted'])
        self.assertEqual(self.deliver(x,o)['items'],[])
        self.assertEqual(x.last_overview['automatic_budget_tokens'],2000)
        self.assertIn('Marketing',encoded(x.page_update(repeat=True)))
        for budget in (512,1000,2000,4000):
            x.reset_delivery();x.request_overview(budget)
            result=self.deliver(x,o)
            self.assertLessEqual(x.tokens(encoded(result)),budget)
        for invalid in (-1,True,900,8192,'512'):
            with self.assertRaises(ValueError):x.request_overview(invalid)

    def test_zero_on_revisit_keeps_search_available(self):
        x,o=self.fixture();self.deliver(x,o);returned=self.revisit(x,o)
        x.request_overview(0);self.deliver(x,returned)
        found=x.search('Marketing')['items'][0]
        self.assertIn('reused_from',found);self.assertEqual(found['bid'],'new-12')

    def test_zero_followed_by_targeted_query_does_not_dump_initial_overview(self):
        x,o=self.fixture();x.request_overview(0);self.deliver(x,o)
        self.assertEqual(x.seen,{})
        self.assertIn('Marketing',encoded(x.search('Marketing')))
        current=self.deliver(x,o)
        self.assertEqual(current['items'],[])
        self.assertNotIn('A long distinctive',encoded(current))
        self.assertIn('A long distinctive',encoded(x.page_update(repeat=True)))

    def test_schema_static_optional_and_not_forwarded_to_browsergym(self):
        x,_=self.fixture();tools=native_tools_profile(ax_config=x.config).tools
        before=tools.definitions()
        d,assistant=tools.parse_completion(completion(response('click',{'bid':'11','ax_overview_tokens':0})))
        self.assertEqual(d.ax_overview_tokens,0)
        self.assertEqual(d.arguments,{'bid':'11'});self.assertEqual(d.code,"click(bid='11')")
        self.assertIn('ax_overview_tokens',assistant['tool_calls'][0]['function']['arguments'])
        self.assertEqual(before,tools.definitions())
        for args in ({'bid':'11','ax_overview_tokens':True},{'bid':'11','ax_overview_tokens':8192}):
            with self.assertRaises(Exception):tools.parse_completion(completion(response('click',args)))
        legacy=native_tools_profile(ax_config=replace(x.config,agent_overview=False,revisit_reuse=False)).tools
        self.assertNotIn('ax_overview_tokens',encoded(legacy.definitions()))
        with self.assertRaises(Exception):legacy.parse_completion(completion(response('click',{'bid':'11','ax_overview_tokens':0})))

    def test_standard_profile_metadata_and_cache_bound(self):
        profile=standard_profile(tokenizer=str(TOKENIZER),helpers=False,data_tools=False)
        self.assertEqual(profile.ax_config.overview_tokens,1000)
        self.assertTrue(profile.tools.agent_overview)
        self.assertEqual(profile.describe()['ax_exploration']['revisit_reuse'],'exact-public-tree-v1')
        x,o=self.fixture()
        for i in range(66):
            o['url']=f'http://fixture/{i}';self.deliver(x,o)
        self.assertEqual(len(x._revisit_cache),64)


if __name__=='__main__':unittest.main()
