from copy import deepcopy
import json
import unittest
from unittest.mock import patch
from intent_browser.ax_context import AXContext, CONTEXT_TOOLS
from intent_browser.ax_explorer import AXConfig, encoded
from intent_browser.harness import native_tools_profile
from tests.test_ax_explorer import TOKENIZER, node, observation
from tests.test_native_tools import completion, response


@unittest.skipUnless(TOKENIZER.is_file(),'Existing tokenizer required')
class ContextTests(unittest.TestCase):
    def fixture(self,large=False):
        nodes=[node(0,'RootWebArea','Store',[1,3]),node(1,'navigation','Header',[2]),
            node(2,'button','Remove',bid=12),node(3,'main','Cart',[4]),node(4,'checkbox','Marketing',bid=14)]
        nodes[4]['properties']=[{'name':'checked','value':{'value':True}}]
        if large:
            nodes[3]['childIds']=[str(i) for i in range(4,104)]
            nodes.extend(node(i,'button',f'Option {i}',bid=i) for i in range(5,104))
        for n in nodes:n['backendDOMNodeId']=int(n['nodeId'])+100
        o=observation(nodes);x=AXContext(AXConfig(str(TOKENIZER),incremental=True))
        return x,o

    def delivered(self,x,o):
        result=json.loads(x.prepare_observation(o));x.acknowledge();return result

    def test_unchanged_queries_and_page_do_not_resend_nodes(self):
        x,o=self.fixture();first=self.delivered(x,o)
        self.assertIn('Marketing',encoded(first))
        page=self.delivered(x,o);self.assertTrue(page['visited_content_unchanged'])
        self.assertEqual(page['items'],[])
        found=x.search('Marketing');x.acknowledge()
        again=x.search('Marketing')
        self.assertEqual(again['items'][0]['ref'],found['items'][0]['ref'])
        self.assertNotIn('name',again['items'][0]);self.assertNotIn('match',again['items'][0])
        full=x.search('Marketing',repeat=True)
        self.assertEqual(full['items'][0]['name'],'Marketing')
        self.assertLess(x.tokens(encoded(again)),x.tokens(encoded(full)))

    def test_trace_rendering_does_not_mark_delivery(self):
        x,o=self.fixture();x.overview(o);x.overview(o)
        self.assertEqual(x.seen,{});self.assertEqual(x.pending,{})
        actual=json.loads(x.prepare_observation(o));self.assertIn('Marketing',encoded(actual))
        self.assertFalse(x.seen);self.assertTrue(x.pending)

    def test_short_full_node_already_delivered_is_not_repeated(self):
        x,o=self.fixture();self.delivered(x,o)
        result=x.read(x.ref(4),view='node')
        self.assertTrue(result['unchanged']);self.assertNotIn('text',result)
        self.assertIn('Marketing',x.read(x.ref(4),view='node',repeat=True)['text'])

    def test_node_radius_structural_not_flattened(self):
        nodes=[node(0,'RootWebArea','Root',[1,8]),node(1,'main','Main',[2,5,6]),
               node(2,'paragraph','',[3,4]),node(3,'StaticText','Paragraph text'),
               node(4,'link','Link'),node(5,'button','Sibling'),node(6,'group','Sibling group',[7]),
               node(7,'button','Cousin'),node(8,'contentinfo','Footer'),node(9,'RootWebArea','Other frame')]
        x=AXContext(AXConfig(str(TOKENIZER),incremental=True));x.capture(observation(nodes));ref=x.ref(2)
        own=x.read(ref,view='node')
        self.assertEqual(own['radius'],0);self.assertEqual(own['scope'],'own_fields_only')
        self.assertNotIn('Paragraph text',encoded(own));self.assertEqual(own['expand_with']['radius'],1)
        near=x.read(ref,view='node',radius=1,repeat=True,limit=50)
        got={x.resolve(i['ref']):i['distance'] for i in near['items']}
        self.assertEqual(got,{2:0,1:1,3:1,4:1,5:1,6:1})
        self.assertEqual(near['items'][0]['ref'],ref)
        self.assertNotIn('Cousin',encoded(near));self.assertNotIn('Footer',encoded(near))
        wide=x.read(ref,view='node',radius=2,repeat=True,limit=50)
        self.assertEqual({x.resolve(i['ref']) for i in wide['items']},set(range(9)))
        self.assertNotIn('Other frame',encoded(wide))
        self.assertEqual(len(wide['items']),len({i['ref'] for i in wide['items']}))
        self.assertEqual([i['distance'] for i in wide['items']],sorted(i['distance'] for i in wide['items']))

    def test_node_radius_pagination_delivery_and_changes(self):
        x,o=self.fixture(large=True);x.capture(o);ref=x.ref(4);seen=set();offset=0
        while True:
            result=x.read(ref,view='node',radius=1,offset=offset,limit=50)
            self.assertLessEqual(x.tokens(encoded(result)),1500)
            refs={i['ref'] for i in result['items']};self.assertFalse(seen&refs)
            self.assertEqual(set(x.pending),refs)
            seen.update(refs);x.acknowledge();offset=result['next_offset']
            if offset is None:break
        self.assertEqual(len(seen),101)  # main, focused checkbox and 99 siblings
        repeated=x.read(ref,view='node',radius=1,limit=5)
        self.assertTrue(all(i['unchanged'] for i in repeated['items']))
        self.assertTrue(all('distance' in i for i in repeated['items']))
        o['axtree_object']['nodes'][5]['name']['value']='Updated sibling'
        x.capture(o);changed=x.read(ref,view='node',radius=1,limit=5)
        self.assertIn('Updated sibling',encoded(changed))
        self.assertNotIn('metadata',encoded(changed))
        verbose=x.read(ref,view='node',radius=1,limit=5,verbose=True,repeat=True)
        self.assertIn('metadata',verbose);self.assertIn('checked',encoded(verbose))

    def test_node_radius_partial_text_still_expandable(self):
        x,o=self.fixture();o['axtree_object']['nodes'][4]['name']['value']='Long '*3000+'TAIL'
        x.capture(o);ref=x.ref(4);result=x.read(ref,view='node',radius=1)
        item=next(i for i in result['items'] if i['ref']==ref)
        self.assertTrue(item['name_partial']);x.acknowledge()
        full=x.read(ref,view='node',radius=0)
        self.assertIn('text',full);self.assertIsNotNone(full['next_text_offset'])

    def test_node_radius_errors_and_legacy_schema(self):
        x,o=self.fixture();x.capture(o);ref=x.ref(4)
        for radius in (True,-1,9,1.5,'1'):
            self.assertIn('error',x.execute('ax_read',{'node_ref':ref,'view':'node','radius':radius}))
        for extra in ({'view':'children','radius':1},{'view':'node','radius':1,'text_offset':4}):
            self.assertIn('error',x.execute('ax_read',{'node_ref':ref,**extra}))
        tools=native_tools_profile(ax_config=x.config).tools
        args={'node_ref':ref,'view':'node','radius':1}
        d,_=tools.parse_completion(completion(response('ax_read',args)));self.assertEqual(d.arguments,args)
        definition=next(d['function'] for d in tools.definitions() if d['function']['name']=='ax_read')
        self.assertEqual(definition['parameters']['properties']['radius']['default'],0)
        self.assertIn('OWN',definition['description']);self.assertIn('siblings count as ONE hop',definition['description'])
        legacy=native_tools_profile(ax_config=AXConfig(str(TOKENIZER))).tools
        with self.assertRaises(Exception):legacy.parse_completion(completion(response('ax_read',args)))
        for radius in (-1,9,True):
            with self.assertRaises(Exception):tools.parse_completion(completion(response('ax_read',{**args,'radius':radius})))

    def test_multiterm_any_all_dedup_and_scope(self):
        x,o=self.fixture();self.delivered(x,o)
        union=x.search(['Remove','Marketing'],repeat=True)
        self.assertEqual(union['total_entries'],2)
        self.assertEqual([i['matched_terms'] for i in union['items']],[['Remove'],['Marketing']])
        self.assertEqual(x.search(['Remove','Marketing'],match='all')['total_entries'],0)
        one=x.search(['checkbox','Marketing'],match='all',repeat=True)
        self.assertEqual(one['total_entries'],1)
        self.assertEqual(one['items'][0]['matched_terms'],['checkbox','Marketing'])
        same=x.search(['Remove','remove','button'])
        self.assertEqual(same['total_entries'],1)
        self.assertEqual(same['items'][0]['matched_terms'],['Remove','button'])
        scoped=x.search(['Remove','Marketing'],scope_ref=x.ref(3),context=8,repeat=True)
        self.assertEqual(scoped['total_entries'],1)
        self.assertNotIn('Remove',encoded(scoped['items'][0].get('neighbors',[])))
        self.assertEqual(x.search(['Remove','Marketing'],role='button')['total_entries'],1)

    def test_multiterm_limits_literal_matching_and_pagination(self):
        x,o=self.fixture(large=True);self.delivered(x,o)
        first=x.search(['Option','Marketing'],limit=2)
        second=x.search(['Option','Marketing'],limit=2,offset=first['next_offset'])
        self.assertEqual(first['total_entries'],100)
        self.assertFalse(set(i['ref'] for i in first['items'])&set(i['ref'] for i in second['items']))
        self.assertEqual(x.search(['.*','Option 103'])['total_entries'],1)
        for invalid in ([],[' '],['a']*9,[None],False):
            with self.subTest(invalid=invalid):self.assertIn('error',x.execute('ax_search',{'query':invalid}))
        self.assertIn('error',x.execute('ax_search',{'query':'x','match':'regex'}))
        self.assertTrue(x.search('',role='button')['total_entries'])

    def test_multiterm_new_excerpt_in_previously_seen_long_node(self):
        x,o=self.fixture();o['axtree_object']['nodes'][4]['name']['value']='Prefix '*1000+'AlphaTarget '+('Middle '*1000)+'BetaTarget'
        self.delivered(x,o)
        first=x.search(['AlphaTarget']);x.acknowledge()
        second=x.search(['AlphaTarget','BetaTarget'])
        self.assertEqual(first['items'][0]['matched_terms'],['AlphaTarget'])
        self.assertIn('BetaTarget',encoded(second['items'][0]['excerpts']))
        self.assertNotIn('AlphaTarget',[e['term'] for e in second['items'][0]['excerpts']])

    def test_stringified_array_notice_preserves_literal_search(self):
        x,o=self.fixture();x.capture(o)
        for q in ('["Marketing", "Remove"]','["%"]','["listitem"]'):
            out=x.search(q)
            self.assertEqual(out['query'],q);self.assertEqual(out['items'],[])
            self.assertEqual(out['total_entries'],0)
            self.assertEqual(out['query_notice']['array_query_example'],{'query':json.loads(q)})
            self.assertFalse(out['query_notice']['search_was_reinterpreted'])
            self.assertEqual(x.pending,{})
            self.assertLessEqual(x.tokens(encoded(out)),1500)
        corrected=x.search(['Marketing','Remove'])
        self.assertEqual(corrected['total_entries'],2);self.assertNotIn('query_notice',corrected)
        # A page may genuinely contain an array-looking literal. Keep that hit.
        o['axtree_object']['nodes'][4]['name']['value']='["Marketing", "Remove"]';x.capture(o)
        literal=x.search('["Marketing", "Remove"]')
        self.assertEqual(literal['total_entries'],1);self.assertNotIn('query_notice',literal)
        self.assertEqual(literal['items'][0]['ref'],x.ref(4))

    def test_array_notice_is_bounded_and_does_not_guess_other_syntax(self):
        x,o=self.fixture();x.capture(o)
        for q in ('No such phrase','[]','[1,2]','[" "]',"['Marketing']",'{"query":["Marketing"]}',
                  json.dumps(['x']*9)):
            self.assertNotIn('query_notice',x.search(q))
        scoped=x.search('["Remove"]',scope_ref=x.ref(3),role='checkbox',match='all')
        self.assertEqual(scoped['scope_ref'],x.ref(3));self.assertEqual(scoped['role'],'checkbox')
        self.assertEqual(scoped['match'],'all');self.assertEqual(scoped['total_entries'],0)
        tools=native_tools_profile(ax_config=x.config).tools
        raw=response('ax_search',{'query':'["Marketing"]'})
        d,a=tools.parse_completion(completion(raw))
        self.assertIsInstance(d.arguments['query'],str)
        self.assertEqual(a['tool_calls'],raw['choices'][0]['message']['tool_calls'])
        self.assertIn('query_notice',x.execute(d.name,d.arguments))
        schema=next(t['function'] for t in tools.definitions() if t['function']['name']=='ax_search')
        self.assertEqual(schema['parameters']['properties']['query']['examples'],['reviews',['reviews','ratings']])
        self.assertIn('{"query":["reviews","ratings"],"match":"any"}',schema['description'])

    def test_stringified_array_notice_respects_small_token_budget(self):
        x=AXContext(AXConfig(str(TOKENIZER),incremental=True,result_tokens=512))
        x.capture(observation([node(0,'RootWebArea','Fixture')]))
        q=json.dumps(['🧪'*70],ensure_ascii=False)
        out=x.search(q)
        self.assertEqual(out['items'],[]);self.assertEqual(out['query'],q)
        self.assertEqual(out['query_notice']['example_omitted'],'token_budget')
        self.assertNotIn('array_query_example',out['query_notice'])
        self.assertLessEqual(x.tokens(encoded(out)),512)

    def test_native_multiterm_schema_and_legacy_string_schema(self):
        tools=native_tools_profile(ax_config=AXConfig(str(TOKENIZER),incremental=True)).tools
        d,_=tools.parse_completion(completion(response('ax_search',{'query':['reviews','ratings'],'match':'any'})))
        self.assertEqual(d.arguments['query'],['reviews','ratings'])
        for arguments in ({'query':[]},{'query':['x']*9},{'query':['x'],'match':'regex'}):
            with self.assertRaises(Exception):tools.parse_completion(completion(response('ax_search',arguments)))
        legacy=native_tools_profile(ax_config=AXConfig(str(TOKENIZER))).tools
        with self.assertRaises(Exception):legacy.parse_completion(completion(response('ax_search',{'query':['x','y']})))

    def test_common_metadata_and_repeat_controls(self):
        x,o=self.fixture();self.delivered(x,o);ref=x.ref(4)
        calls=[lambda v,r:x.search('Marketing',verbose=v,repeat=r),
               lambda v,r:x.read(ref,view='subtree',verbose=v,repeat=r),
               lambda v,r:x.page_update(o,verbose=v,repeat=r)]
        for call in calls:
            with self.subTest(call=call):
                compact=call(False,True);verbose=call(True,True)
                self.assertNotIn('metadata',encoded(compact));self.assertIn('metadata',verbose)
                self.assertIn('checked',encoded(compact));self.assertIn('Marketing',encoded(compact))

    def test_changed_field_not_whole_section(self):
        x,o=self.fixture();self.delivered(x,o);ref=x.ref(4)
        o['axtree_object']['nodes'][4]['properties'][0]['value']['value']=False
        changed=self.delivered(x,o)
        self.assertEqual(len(changed['items']),1)
        self.assertEqual(changed['items'][0]['ref'],ref)
        self.assertEqual(changed['items'][0]['state'],{'checked':False})
        self.assertNotIn('name',changed['items'][0])
        self.assertEqual(self.delivered(x,o)['items'],[])

    def test_reorder_move_remove_and_replacement(self):
        x,o=self.fixture();self.delivered(x,o);old=x.ref(4)
        nodes=o['axtree_object']['nodes'];nodes[1]['childIds'].append('4');nodes[3]['childIds']=[]
        changed=self.delivered(x,o)
        moved=next(i for i in changed['items'] if i['ref']==old)
        self.assertIn('parent',moved['changed'])
        nodes[1]['childIds']=['4','2'];changed=self.delivered(x,o)
        self.assertTrue(any('position' in i.get('changed',[]) for i in changed['items']))
        nodes[4]['backendDOMNodeId']=999
        changed=self.delivered(x,o)
        self.assertIn({'ref':old,'removed':True},changed['items'])
        self.assertIn('Stale',x.execute('ax_read',{'node_ref':old})['error'])

    def test_new_children_and_unseen_content(self):
        x,o=self.fixture(large=True);first=self.delivered(x,o)
        self.assertIsNotNone(first['next_offset'])
        found=x.search('Option 103');self.assertIn('Option 103',encoded(found))
        x.acknowledge();ref=found['items'][0]['ref']
        o['axtree_object']['nodes'][103]['name']['value']='Changed distant control'
        changed=self.delivered(x,o)
        self.assertTrue(any(i['ref']==ref and i.get('name')=='Changed distant control' for i in changed['items']))
        o['axtree_object']['nodes'][3]['childIds'].append('104')
        n=node(104,'button','New option',bid=104);n['backendDOMNodeId']=204;o['axtree_object']['nodes'].append(n)
        changed=self.delivered(x,o);self.assertIn('New option',encoded(changed))

    def test_partial_text_never_counts_as_full(self):
        x,o=self.fixture();o['axtree_object']['nodes'][4]['name']['value']='Prefix '*3000+'NeedleOne '+('Middle '*3000)+'NeedleTwo'
        self.delivered(x,o);ref=x.ref(4)
        one=x.search('NeedleOne');x.acknowledge();two=x.search('NeedleTwo');x.acknowledge()
        self.assertIn('NeedleOne',encoded(one));self.assertIn('NeedleTwo',encoded(two))
        first=x.read(ref,view='node');self.assertIn('text',first);self.assertIsNotNone(first['next_text_offset'])
        x.acknowledge();again=x.read(ref,view='node');self.assertTrue(again['unchanged']);self.assertNotIn('text',again)
        second=x.read(ref,view='node',text_offset=first['next_text_offset']);self.assertIn('text',second)
        self.assertLessEqual(x.tokens(encoded(second)),1500)
        repeated=x.read(ref,view='node',repeat=True);self.assertEqual(first['text'],repeated['text'])

    def test_budget_omitted_nodes_not_marked_seen(self):
        x,o=self.fixture(large=True);x.capture(o)
        result=x.read(x.ref(3),view='subtree',depth=2,limit=50)
        delivered={i['ref'] for i in result['items']}
        self.assertEqual(set(x.pending),delivered)
        self.assertLessEqual(x.tokens(encoded(result)),1500)
        x.acknowledge();tail=x.read(x.ref(3),view='subtree',offset=result['next_offset'],limit=50)
        self.assertTrue(any('name' in i for i in tail['items']))

    def test_reset_context_and_navigation_restore_information(self):
        x,o=self.fixture();self.delivered(x,o);old=x.ref(4)
        x.reset_delivery();self.assertIn('Marketing',x.prepare_observation(o));x.acknowledge()
        o['url']='http://fixture/new';fresh=self.delivered(x,o)
        self.assertIn('Marketing',encoded(fresh));self.assertNotEqual(old,x.ref(4))

    def test_large_delta_pages_do_not_drop_undelivered_changes(self):
        x,o=self.fixture(large=True);self.delivered(x,o)
        root=x.ref(3);offset=0
        while True:
            result=x.read(root,view='subtree',offset=offset,limit=50);x.acknowledge()
            offset=result['next_offset']
            if offset is None:break
        for n in o['axtree_object']['nodes'][5:]:n['name']['value']+=' changed'
        delivered=set()
        for _ in range(30):
            result=self.delivered(x,o)
            self.assertLessEqual(x.tokens(encoded(result)),2000)
            delivered.update(i['ref'] for i in result['items'] if 'name' in i.get('changed',[]))
            if result['next_offset'] is None:break
            self.assertEqual(result['next_offset'],0)
        self.assertEqual(len(delivered),99)
        self.assertEqual(self.delivered(x,o)['items'],[])

    def test_later_change_outside_preview_is_signalled(self):
        x,o=self.fixture();o['axtree_object']['nodes'][4]['name']['value']='Word '*300+'Original'
        self.delivered(x,o);o['axtree_object']['nodes'][4]['name']['value']='Word '*300+'Changed'
        result=self.delivered(x,o)
        self.assertEqual(result['items'][0]['changed'],['name'])
        self.assertTrue(result['items'][0]['name_partial'])

    def test_all_context_tool_schemas_share_controls_and_v6_is_unchanged(self):
        profile=native_tools_profile(ax_config=AXConfig(str(TOKENIZER),incremental=True))
        self.assertEqual(profile.name,'core-tools-v7-context')
        definitions={d['function']['name']:d['function']['parameters'] for d in profile.tools.definitions()}
        for name in CONTEXT_TOOLS:
            for control in ('verbose','repeat'):
                self.assertEqual(definitions[name]['properties'][control],{'type':'boolean','default':False})
        decision,_=profile.tools.parse_completion(completion(response('ax_changes',{'verbose':True,'repeat':False})))
        self.assertEqual(decision.arguments['verbose'],True)
        old=native_tools_profile(ax_config=AXConfig(str(TOKENIZER))).tools
        self.assertNotIn('ax_changes',[d['function']['name'] for d in old.definitions()])
        with self.assertRaises(Exception):old.parse_completion(completion(response('ax_search',{'query':'x','verbose':True})))

    def test_feedback_metadata_controls_keep_gaps_errors_and_events(self):
        x,o=self.fixture();self.delivered(x,o)
        raw={'scope':'capture details','selection':{'raw_events':2,'capture_omitted':1},'execution':'action_error',
             'error':'TimeoutError: uncertain effect','events':[{'sequence':9,'kind':'page_announcement','text':'Saved'}],
             'added_or_changed':['status Saved']}
        concise=x.feedback(raw,kind='browser_feedback')
        self.assertNotIn('selection',concise);self.assertNotIn('scope',concise);self.assertNotIn('metadata',concise)
        self.assertEqual(concise['partial_capture'],{'capture_omitted':1});self.assertEqual(concise['error'],raw['error'])
        self.assertEqual(concise['events'][0]['text'],'Saved')
        verbose=x.feedback(raw,kind='browser_feedback',verbose=True)
        self.assertEqual(verbose['metadata']['event_sequences'],[9])
        self.assertIn('recent_action_capture',x.page_update(o,verbose=True)['metadata'])
        self.assertEqual(x.feedback(raw,kind='browser_feedback')['events'],concise['events'])

    def test_discard_unconfirmed_pending_and_preserve_known_history(self):
        x,o=self.fixture(large=True);self.delivered(x,o)
        known=set(x.seen);result=x.search('Option 103');ref=result['items'][0]['ref']
        self.assertNotIn(ref,known);self.assertIn(ref,x.pending)
        x.discard_pending();self.assertEqual(set(x.seen),known)
        self.assertIn('Option 103',encoded(x.search('Option 103')))

    def test_removed_identity_never_rebinds_after_reinsertion(self):
        x,o=self.fixture();self.delivered(x,o);ref=x.ref(4)
        saved=deepcopy(o['axtree_object']['nodes'][4])
        o['axtree_object']['nodes'].pop();o['axtree_object']['nodes'][3]['childIds']=[]
        self.delivered(x,o)
        o['axtree_object']['nodes'].append(saved);o['axtree_object']['nodes'][3]['childIds']=['4']
        self.delivered(x,o);self.assertNotEqual(x.ref(4),ref)

    def test_cli_selects_correct_context_profile_without_network(self):
        from intent_browser import cli
        for version in ('core-tools-v6-ax','core-tools-v7-context'):
            with self.subTest(version=version), patch.dict('os.environ',{},clear=True), patch('sys.argv',[
                'intent-browser','run','--model','scripted','--base-url','http://localhost:1/v1','--no-preview',
                '--allow-ungraded','--ungraded-reason','Offline CLI context-profile fixture',
                '--harness-profile',version,'--ax-tokenizer-file',str(TOKENIZER)]), \
                patch.object(cli,'ChatCompletionsBackend'),patch.object(cli,'run_episode',return_value=(None,{'error':None})) as runner:
                cli.main()
                self.assertEqual(runner.call_args.kwargs['harness_profile'].name,version)

if __name__=='__main__':unittest.main()
