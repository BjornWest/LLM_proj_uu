import json
from pathlib import Path
import unittest
from intent_browser.ax_explorer import AXConfig, AXExplorer, encoded
from intent_browser.harness import native_tools_profile
from tests.test_native_tools import completion, response

TOKENIZER = Path(__file__).resolve().parents[1]/'training/.cache/qwen38-tokenizer/tokenizer.json'


def node(i, role, name, children=(), bid=None):
    return {'nodeId': str(i), 'role': {'value': role}, 'name': {'value': name},
            'childIds': [str(c) for c in children], 'ignored': False,
            **({'browsergym_id': str(bid)} if bid is not None else {})}


def observation(nodes):
    return {'url': 'http://fixture/', 'last_action_error': '', 'axtree_object': {'nodes': nodes}}


@unittest.skipUnless(TOKENIZER.is_file(), 'Requires existing local Qwen tokenizer asset')
class AXTests(unittest.TestCase):
    def make(self, nodes, budget=2000):
        x = AXExplorer(AXConfig(str(TOKENIZER), overview_tokens=budget))
        o = observation(nodes); x.overview(o); return x,o

    def sections(self):
        return [node(0,'RootWebArea','Store',[1,3]), node(1,'navigation','Header',[2]),
                node(2,'button','Remove',bid=12), node(3,'main','Cart',[4]), node(4,'button','Remove',bid=14)]

    def test_small_page_whole_and_budget(self):
        x,o = self.make(self.sections())
        self.assertTrue(x.last_overview['complete'])
        self.assertLessEqual(x.tokens(x.overview(o)), 2000)
        self.assertIn('[14]', x.overview(o))

    def test_duplicate_names_have_location_and_scoped_search(self):
        x,_ = self.make(self.sections())
        all_results = x.search('Remove')
        self.assertEqual(all_results['total_entries'], 2)
        first,second = all_results['items']
        self.assertEqual(first['location']['ancestors'][-1]['name'],'Header')
        self.assertEqual(second['location']['ancestors'][-1]['name'],'Cart')
        self.assertNotEqual(first['ref'],second['ref'])
        self.assertNotIn('neighbors',first)
        scoped = x.search('Remove',scope_ref=second['parent_ref'],context=8)
        self.assertEqual(scoped['total_entries'],1)
        self.assertEqual(scoped['items'][0]['bid'],'14')
        self.assertNotIn('12',[n['bid'] for n in scoped['items'][0]['neighbors']])
        self.assertIn('Remove',scoped['items'][0]['match_excerpt'])

    def test_traversal_and_pagination(self):
        x,_ = self.make(self.sections())
        root = x.ref(0)
        result = x.read(root,limit=1)
        self.assertEqual(result['total_entries'],2)
        self.assertEqual(result['next_offset'],1)
        second = x.read(root,offset=1,limit=1)
        self.assertEqual(second['items'][0]['name'],'Cart')
        self.assertIsNone(second['next_offset'])
        result = x.read(root,view='subtree',depth=1)
        self.assertEqual([n['name'] for n in result['items']],['Store','Header','Cart'])
        parents = x.read(x.ref(4),view='ancestors')
        self.assertEqual([n['name'] for n in parents['items']],['Cart','Store'])
        near = x.read(x.ref(4),view='neighborhood',context=1)
        self.assertEqual([n['name'] for n in near['items']],['Cart','Remove'])

    def test_late_match_outside_overview_and_pageable_results(self):
        nodes = [node(0,'RootWebArea','Large',[1]),node(1,'main','Content',range(2,502))]
        nodes += [node(i,'button',f'Option {i}',bid=i) for i in range(2,502)]
        x,o = self.make(nodes,512)
        self.assertFalse(x.last_overview['complete'])
        self.assertNotIn('Option 501',x.overview(o))
        result=x.search('Option 501')
        self.assertEqual(result['items'][0]['bid'],'501')
        self.assertLessEqual(x.tokens(encoded(result)),1500)
        a=x.search('Option',limit=2);b=x.search('Option',limit=2,offset=a['next_offset'])
        self.assertEqual(a['total_entries'],500)
        self.assertNotEqual(a['items'][0]['ref'],b['items'][0]['ref'])

    def test_stale_ref_cannot_bind_to_new_tree(self):
        x,o=self.make(self.sections());old=x.ref(4)
        o['axtree_object']['nodes'][4]['name']['value']='Different action'
        x.capture(o)
        for name,args in [('ax_read',{'node_ref':old}),('ax_search',{'query':'Remove','scope_ref':old})]:
            result=x.execute(name,args)
            self.assertIn('Stale',result['error'])
            self.assertEqual(result['items'],[])

    def test_synthetic_text_ids_stable_but_real_dom_replacement_invalidates(self):
        nodes=[node(0,'RootWebArea','Page',[1]),node(1,'paragraph','',[-1]),node(-1,'StaticText','Example')]
        nodes[0]['backendDOMNodeId']=10
        nodes[1]['backendDOMNodeId']=11
        x,o=self.make(nodes);ref=x.ref(2)
        nodes[1]['childIds']=['-2'];nodes[2]['nodeId']='-2'
        x.capture(o)
        self.assertEqual(x.ref(2),ref)
        nodes[1]['backendDOMNodeId']=99
        x.capture(o)
        self.assertNotEqual(x.ref(2),ref)

    def test_search_cannot_leak_other_section_via_scoped_neighbors(self):
        x,_=self.make(self.sections())
        cart=x.search('Cart',role='main')['items'][0]['ref']
        found=x.search('Remove',scope_ref=cart,context=8)
        self.assertEqual([i['bid'] for i in found['items']],['14'])
        self.assertTrue(all(n['name']!='Header' for n in found['items'][0]['neighbors']))

    def test_strict_query_schema_accepts_explicit_nullable_scope(self):
        tools=native_tools_profile(ax_config=AXConfig(str(TOKENIZER)),strict=True).tools
        decision,_=tools.parse_completion(completion(response('ax_search',{
            'query':'Remove','role':None,'scope_ref':None,'limit':5,'context':0,'offset':0})))
        self.assertIsNone(decision.arguments['scope_ref'])

    def test_deep_text_match_and_token_pagination_preserve_original(self):
        name=('Ordinary content. '*5000)+'UniqueTarget Exact Capitalization'
        x,o=self.make([node(0,'RootWebArea','Page',[1]),node(1,'paragraph',name)])
        found=x.search('uniquetarget')['items'][0]
        self.assertIn('UniqueTarget',found['match_excerpt'])
        match_text=x.read(found['ref'],view='node',text_offset=found['suggested_text_offset'])
        self.assertIn('UniqueTarget Exact Capitalization',match_text['text'])
        text=x.read(found['ref'],view='node')
        self.assertIsNotNone(text['next_text_offset'])
        self.assertLessEqual(x.tokens(encoded(text)),1500)
        tail=x.read(found['ref'],view='node',text_offset=text['total_text_tokens']-40)
        self.assertIn('UniqueTarget Exact Capitalization',tail['text'])
        self.assertIsNone(tail['next_text_offset'])

    def test_native_tool_schema_limits_and_default_catalog(self):
        config=AXConfig(str(TOKENIZER));tools=native_tools_profile(ax_config=config).tools
        decision,_=tools.parse_completion(completion(response('ax_search',{'query':'Remove','context':0,'limit':3})))
        self.assertEqual(decision.arguments['limit'],3)
        with self.assertRaises(Exception):tools.parse_completion(completion(response('ax_search',{'query':'x','context':99})))
        with self.assertRaises(ValueError):native_tools_profile().tools.parse_completion(completion(response('ax_read',{'node_ref':'ax:x:0'})))

if __name__=='__main__':unittest.main()
