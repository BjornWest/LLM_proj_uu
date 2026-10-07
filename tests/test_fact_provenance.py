"""Exact private AX provenance over real context formatting, without a browser/model."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from intent_browser.ax_context import AXContext
from intent_browser.ax_explorer import AXConfig
from intent_browser.fact_provenance import FactRecorder, digest, encoded, json_layout, slice16, u16
from intent_browser.policy_delivery import PolicyDelivery
from tests.test_ax_explorer import TOKENIZER, node, observation


@unittest.skipUnless(TOKENIZER.is_file(), 'Existing Qwen tokenizer required')
class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name); self.events=[]
        self.trace=SimpleNamespace(directory=self.path,event=lambda name,**kw:self.events.append((name,kw)))
        self.exports=[]; self.state='state-1'

    def fixture(self, text='Price €29.90', *, value='', budget=1500):
        nodes=[node(0,'RootWebArea','Shop',[1]),node(1,'button',text,bid=1)]
        for n in nodes:n['backendDOMNodeId']=100+int(n['nodeId'])
        nodes[0]['frameId']='frame-real'
        if value:nodes[1]['value']={'value':value}
        obs=observation(nodes)
        x=AXContext(AXConfig(str(TOKENIZER),incremental=True,result_tokens=budget))
        r=FactRecorder(self.trace,self.provider);r.attach(x);self.addCleanup(r.close)
        return x,obs,r

    def provider(self, env, obs, context):
        self.exports.append(deepcopy(context))
        sources=[]
        for n in obs['axtree_object']['nodes']:
            for field in ('name','value'):
                if not n.get(field,{}).get('value'):continue
                text=n[field]['value']
                sources.append({'id':f"export-{n['nodeId']}-{field}", 'text':text,'sha256':digest(text),
                    'binding':{'snapshot_id':context['snapshot_id'],'document_id':'actual-document-1',
                        'frame_id':'frame-real','node_id':n['nodeId'],'field':field},
                    'opaque_binding':{'state_id':self.state,'occurrence_id':'private-fact'}})
        return {'schema':'ax-fact-sources-v1','sources':sources,'private_context':{'secret':'producer-only'},
                'mapping_inventory_complete':False}

    def policy(self, r, value, *, output=None):
        ledger=PolicyDelivery(self.trace);ledger.fact_recorder=r
        text=value if isinstance(value,str) else encoded(value)
        cid=ledger.register('ax_result',text,step=0,fact_output=output or r.select(value))
        return ledger,cid

    def receipt(self,ledger,cid, *, ack=True, retained=True, aligned=True,recipient='main',step=0):
        text=ledger.sources[cid]['text'];messages=[{'role':'tool','content':text if aligned else 'rewritten'}]
        event={'step':step,'messages':messages,'model_request':{'messages':messages} if retained else None}
        bindings=[{'content_id':cid,'message_index':0,'start':0,'end':len(text)}]
        ledger.record(event,bindings,acknowledged=ack,recipient=recipient)
        return json.loads((self.path/'fact-delivery.jsonl').read_text().splitlines()[-1])

    def mapped(self,r,value):
        selected=r.select(value);self.assertIsNotNone(selected)
        sources={s['id']:s for s in json.loads((self.path/selected['record']['capture']).read_text())['sources']}
        for p in selected['record']['projections']:
            out=selected['body']
            for key in p['output_path']:out=out[key]
            actual=slice16(out,p['output_start'],p['output_end'])
            if p['encoding']=='json_string':actual=json.loads('"'+actual+'"')
            source=sources[p['source_id']]
            self.assertEqual(actual,slice16(source['text'],p['source_start'],p['source_end']))
        return selected,sources

    def test_public_parity_and_no_private_context(self):
        x,obs,r=self.fixture('Quote "€" 😀\nnext',value='29.90')
        raw=AXContext(x.config)
        self.assertEqual(x.prepare_observation(obs),raw.prepare_observation(obs))
        result=x.search('Quote',repeat=True)
        self.assertEqual(result,raw.search('Quote',repeat=True))
        selected,sources=self.mapped(r,result)
        self.assertGreater(len(selected['record']['projections']),0)
        self.assertNotIn('producer-only',encoded(result));self.assertNotIn('private-fact',encoded(result))
        ledger,cid=self.policy(r,result)
        self.assertNotIn('private-fact',ledger.sources[cid]['text'])
        self.assertTrue(self.receipt(ledger,cid)['items'][0]['confirmed'])

    def test_confirmed_only_with_exact_retained_ack(self):
        for ack,retained,aligned in [(True,True,True),(False,True,True),(True,False,True),(True,True,False)]:
            with self.subTest(ack=ack,retained=retained,aligned=aligned):
                x,obs,r=self.fixture();out=x.prepare_observation(obs);ledger,cid=self.policy(r,out)
                self.assertEqual(self.receipt(ledger,cid,ack=ack,retained=retained,aligned=aligned)['items'][0]['confirmed'],
                                 ack and retained and aligned)

    def test_current_state_not_credited_by_old_generation(self):
        x,obs,r=self.fixture();x.capture(obs);old=x.search('Price');frozen=r.select(old)
        self.state='state-2';r.step=1;x.capture(obs);new=x.search('Price',repeat=True)
        self.assertNotEqual(frozen['record']['capture'],r.select(new)['record']['capture'])
        ledger,cid=self.policy(r,old,output=r.lookup(frozen['artifact']))
        policy=json.loads((self.path/ledger.sources[cid]['provenance']['fact_projection_artifact']).read_text())
        old_ids={p['source_id'] for p in policy['projections']}
        self.assertTrue(old_ids);self.assertTrue(all(s.startswith('fact-capture-0000') for s in old_ids))
        self.assertTrue(all(s['opaque_binding']['state_id']=='state-1' for s in json.loads((self.path/frozen['record']['capture']).read_text())['sources']))
        self.assertEqual(len(self.exports),2) # even identical public AX must consult effective private state

    def test_changed_fields_do_not_emit_old_unchanged_name(self):
        x,obs,r=self.fixture(value='29.90');x.prepare_observation(obs);x.acknowledge()
        obs['axtree_object']['nodes'][1]['value']['value']='31.00'
        out=x.prepare_observation(obs);selected,sources=self.mapped(r,out)
        fields={sources[p['source_id']]['binding']['field'] for p in selected['record']['projections']}
        self.assertEqual(fields,{'value'})

    def test_unchanged_reference_is_recipient_scoped_and_historical(self):
        x,obs,r=self.fixture();first=x.prepare_observation(obs);ledger,cid=self.policy(r,first)
        self.receipt(ledger,cid);x.acknowledge();self.state='state-2';x.capture(obs)
        same=x.read(x.ref(1),view='node');sel=r.select(same)
        self.assertEqual(sel['record']['projections'],[])
        self.assertTrue(sel['record']['references'])
        second=ledger.register('ax_result',encoded(same),step=1,fact_output=sel)
        main=self.receipt(ledger,second,step=1)
        helper=self.receipt(ledger,second,step=1,recipient='helper')
        self.assertEqual(main['items'][0]['references'][0]['acknowledged_content_ids'],[cid])
        self.assertEqual(helper['items'][0]['references'][0]['acknowledged_content_ids'],[])

    def test_padded_scalar_query_maps_the_actual_first_repeated_neighborhood(self):
        term='TARGET '+'x '*110+'END'
        text=('lead '*25)+term+'X '+('gap '*150)+('lead '*25)+term+' '
        x,obs,r=self.fixture(text);x.capture(obs)
        result=x.search(term+' ',repeat=True);selected,sources=self.mapped(r,result)
        matches=[p for p in selected['record']['projections']
                 if p['output_path']==['items',0,'match']]
        self.assertTrue(matches)
        # AXContext strips the padded query and selects its first occurrence.
        first=text.index(term);second=text.index(term,first+len(term))
        self.assertTrue(all(p['source_start']<second for p in matches))
        self.assertEqual(min(p['source_start'] for p in matches),first-48)

    def test_exact_search_neighborhood_maps_only_emitted_slices(self):
        x,obs,r=self.fixture('x '*180+'TARGET'+' y'*180);x.capture(obs)
        out=x.search('TARGET',repeat=True);sel,sources=self.mapped(r,out)
        excerpts=[p for p in sel['record']['projections'] if p['output_path'][-1]=='match']
        self.assertTrue(excerpts)
        self.assertTrue(any(p['source_start']>0 for p in excerpts))
        self.assertTrue(all(p['source_end']<u16(obs['axtree_object']['nodes'][1]['name']['value']) for p in excerpts))

    def test_json_token_pages_never_split_unicode_or_escapes(self):
        x,obs,r=self.fixture(('Quote "a" 😀\n\\ b '*100),budget=512);x.capture(obs)
        offset=0;pages=0;mapped=0
        while True:
            out=x.read(x.ref(1),view='node',text_offset=offset,repeat=True)
            sel,_=self.mapped(r,out);mapped+=len(sel['record']['projections']);pages+=1
            offset=out['next_text_offset']
            if offset is None:break
            self.assertLess(pages,60)
        self.assertGreater(pages,1);self.assertGreater(mapped,0)

    def test_wrapped_observation_exact_escape_composition(self):
        x,obs,r=self.fixture('Quote "a" 😀\n\\ b');out=x.prepare_observation(obs);sel=r.select(out)
        ledger,cid=self.policy(r,'Tabs here\n'+out+'\nSupervisor note',output=sel)
        record=json.loads((self.path/ledger.sources[cid]['provenance']['fact_projection_artifact']).read_text())
        sources={s['id']:s for s in json.loads((self.path/sel['record']['capture']).read_text())['sources']}
        for p in record['projections']:
            self.assertEqual(p['output_path'],[])
            part=slice16(ledger.sources[cid]['text'],p['output_start'],p['output_end'])
            self.assertEqual(json.loads('"'+part+'"'),slice16(sources[p['source_id']]['text'],p['source_start'],p['source_end']))
        self.assertTrue(record['projections'])

    def test_output_object_selection_does_not_guess_from_equal_text(self):
        x,obs,r=self.fixture();x.capture(obs);out=x.search('Price')
        self.assertIsNone(r.select(deepcopy(out)))
        ledger,cid=self.policy(r,deepcopy(out))
        self.assertFalse(json.loads((self.path/ledger.sources[cid]['provenance']['fact_projection_artifact']).read_text())['projections'])

    def test_static_text_suppression_requires_real_contents_provenance(self):
        for contents,duplicate in [(True,False),(False,False),(True,True)]:
            with self.subTest(contents=contents,duplicate=duplicate):
                x,obs,r=self.fixture('Buy at €29.90')
                parent=obs['axtree_object']['nodes'][1];parent['childIds']=['2']
                if contents:parent['name']['sources']=[{'type':'contents','value':{'value':parent['name']['value']}}]
                obs['axtree_object']['nodes'].append(node(2,'StaticText','€29.90'))
                if duplicate:
                    parent['childIds'].append('3');obs['axtree_object']['nodes'].append(node(3,'StaticText','€29.90'))
                out=x.prepare_observation(obs);sel,sources=self.mapped(r,out)
                childids={s['id'] for s in sources.values() if s['binding']['node_id'] in ('2','3')}
                emitted={p['source_id'] for p in sel['record']['projections']}
                self.assertEqual(bool(childids&emitted),contents and not duplicate)

    def test_stale_frame_hash_and_ignored_bindings_remain_unknown(self):
        for change in ['frame','snapshot','hash','ignored']:
            with self.subTest(change=change):
                x,obs,r=self.fixture();original=r.provider
                def provider(env,o,c):
                    data=original(env,o,c);data['sources']=data['sources'][1:]
                    source=data['sources'][0]
                    if change=='frame':source['binding']['frame_id']='wrong'
                    if change=='snapshot':source['binding']['snapshot_id']='stale'
                    if change=='hash':source['sha256']='bad'
                    return data
                r.provider=provider
                if change=='ignored':obs['axtree_object']['nodes'][1]['ignored']=True
                out=x.prepare_observation(obs);sel=r.select(out)
                self.assertEqual(sel['record']['projections'],[])

    def test_provider_failure_does_not_change_browser_output_or_leak_error(self):
        x,obs,r=self.fixture();raw=AXContext(x.config)
        def fail(*args):raise RuntimeError('private secret')
        r.provider=fail
        out=x.prepare_observation(obs);self.assertEqual(out,raw.prepare_observation(obs))
        self.assertEqual(r.select(out)['record']['projections'],[])
        capture=json.loads(next(self.path.glob('fact-capture-*')).read_text())
        self.assertNotIn('private secret',encoded(capture))
        self.assertEqual(capture['diagnostics'][0]['error_type'],'RuntimeError')

    def test_instrumentation_failure_is_private_unknown(self):
        x,obs,r=self.fixture();raw=AXContext(x.config)
        with patch.object(r,'stage',side_effect=OSError('disk error')):
            out=x.prepare_observation(obs)
        self.assertEqual(out,raw.prepare_observation(obs));self.assertIsNone(r.select(out))
        self.assertTrue(any(e[0]=='fact_recording_unknown' for e in self.events))

    def test_cache_eviction_and_hook_cleanup(self):
        x,obs,r=self.fixture();x.capture(obs);old=x.search('Price')
        for _ in range(65):x.search('Price',repeat=True)
        self.assertLessEqual(len(r.outputs),64);self.assertIsNone(r.select(old))
        r.close();before=len(self.exports);x.capture(obs);self.assertEqual(len(self.exports),before)

    def test_partial_preview_maps_only_visible_preview_text(self):
        x,obs,r=self.fixture('Word '*300)
        obs['observation_capture']={'coverage':'partial'}
        out=x.prepare_observation(obs);sel,_=self.mapped(r,out)
        self.assertTrue(sel['record']['projections'])
        self.assertTrue(all(p['source_end']<u16('Word '*300) for p in sel['record']['projections'] if p['source_start']==0 and p['source_end']>4))

    def test_real_normalizer_packet_preserves_native_part_binding(self):
        import os, sys
        training=os.environ.get('FACT_PROVENANCE_CONSUMER_ROOT',str(Path(__file__).resolve().parents[1]/'training'))
        sys.path.insert(0,training);self.addCleanup(lambda:sys.path.remove(training))
        from browser_training.website_projection import direct_sources
        from browser_training.fact_render_capture import harness_source_packet
        x,obs,r=self.fixture('Buy at €29.90')
        parent=obs['axtree_object']['nodes'][1];parent['childIds']=['2']
        parent['name']['sources']=[{'type':'contents','value':{'value':parent['name']['value']}}]
        child=node(2,'StaticText','€29.90');child['backendDOMNodeId']=102
        obs['axtree_object']['nodes'].append(child)
        def callback(env,o,context):
            sources,diagnostics=direct_sources(o['axtree_object']['nodes'],
                [{'id':'actual-dom-run','kind':'text_node','text':'€29.90','sha256':digest('€29.90'),
                  'backend_node_id':102}],snapshot_id=context['snapshot_id'],document_id='actual-document',frame_id='frame-real')
            normalized={'schema':'fact-render-normalized-v1','render_revision':'renderer-v1',
                'ax_sources':sources,'ax_diagnostics':diagnostics,'diagnostics':[],
                'occurrences':[{'id':'native-occurrence','binding':{'native_product':'real-SKU'},
                    'effective_state':{'price':'29.90'},'parts':[{'part':'price',
                    'spans':[{'source_id':'actual-dom-run','start':0,'end':u16('€29.90')}]}]}]}
            return harness_source_packet(normalized)
        r.provider=callback
        out=x.prepare_observation(obs);sel,sources=self.mapped(r,out)
        self.assertTrue(sel['record']['projections']);source=next(iter(sources.values()))
        self.assertEqual(source['export_id'],'actual-dom-run')
        self.assertEqual(source['binding']['node_id'],'2')
        self.assertEqual(source['opaque_binding']['parts'][0]['occurrence_id'],'native-occurrence')
        self.assertNotIn('real-SKU',out)

    def test_conflicting_raw_identity_clears_source_mapping(self):
        x,obs,r=self.fixture();x.capture(obs);conflict=deepcopy(obs['axtree_object']['nodes'][1])
        conflict['name']['value']='Other';obs['axtree_object']['nodes'].append(conflict)
        x.capture(obs)
        self.assertIsNone(r.current)
        result=x.search('Other',repeat=True);self.assertEqual(r.select(result)['record']['projections'],[])

    def test_multi_term_and_neighbor_paths_are_real_output_paths(self):
        x,obs,r=self.fixture('Price €29.90',value='In stock');x.capture(obs)
        result=x.search(['Price','stock'],context=1,repeat=True)
        selected,_=self.mapped(r,result)
        self.assertTrue(any('excerpts' in p['output_path'] for p in selected['record']['projections']))
        self.assertTrue(any('neighbors' in p['output_path'] for p in selected['record']['projections']))

    def test_unicode_casefold_excerpt_remains_unknown(self):
        x,obs,r=self.fixture('Die Straße');x.capture(obs)
        result=x.search('STRASSE',repeat=True);selected,_=self.mapped(r,result)
        self.assertTrue(any('normalized_match' in item for item in result['items']))
        self.assertFalse(any(p['output_path'][-1]=='normalized_match' for p in selected['record']['projections']))
        self.assertTrue(any(d['reason']=='normalized_match_not_identity' for d in selected['record']['diagnostics']))

    def test_utf16_layout_and_surrogate_boundaries(self):
        value={'name':'😀"\n\\','items':[{'value':'é'}]};text,positions=json_layout(value)
        self.assertEqual(text,encoded(value));a,b=positions[('name',)]
        self.assertEqual(json.loads('"'+slice16(text,a,b)+'"'),value['name'])
        with self.assertRaises((ValueError,UnicodeError)):slice16('😀',0,1)


if __name__=='__main__':unittest.main()
