import unittest
from copy import deepcopy
from types import SimpleNamespace
from intent_browser.dynamic_preview import DynamicPreview, main_nodes, semantics
from intent_browser.observation_pipeline import ObservationChanged, ObservationPipelineConfig
from intent_browser.ax_context import AXContext
from intent_browser.ax_explorer import AXConfig
from intent_browser.standard_profile import tokenizer_path
from tests.test_observation_pipeline import obs


class DynamicTests(unittest.TestCase):
    def test_explicit_mode_and_bounds(self):
        for kwargs in ({'dynamic_preview':1}, {'dynamic_preview':True}, {'preview_node_limit':True},
                       {'preview_node_limit':0}, {'preview_node_limit':129}):
            with self.assertRaises(ValueError):ObservationPipelineConfig(('http://fixture',),**kwargs)
        self.assertFalse(ObservationPipelineConfig((),full_capture_only=True).dynamic_preview)
        self.assertTrue(ObservationPipelineConfig((),full_capture_only=True,dynamic_preview=True).dynamic_preview)

    def validator(self):
        value=obs();value['axtree_object']['nodes'][0]['frameId']='main'
        value['human_tab_capture']={'document':{'frame_id':'main'}}
        p=DynamicPreview.__new__(DynamicPreview)
        p.pending={'identity':{'document':{'frame_id':'main'}},
                   'semantics':[semantics(n) for n in value['axtree_object']['nodes']]}
        p.identity=lambda:p.pending['identity'];p.full=value
        return p

    def test_semantics_and_shared_dom_text_ids(self):
        p=self.validator();n=deepcopy(p.full['axtree_object']['nodes'][1]);n.update(nodeId='inline',role={'value':'InlineTextBox'})
        p.full['axtree_object']['nodes'][0]['childIds'].append('inline')
        p.full['axtree_object']['nodes'].append(n);p.validate()
        p.full['axtree_object']['nodes'][1]['name']={'value':'Changed'}
        with self.assertRaises(ObservationChanged):p.validate()

    def test_child_same_dom_id_cannot_substitute_main(self):
        p=self.validator();n=p.full['axtree_object']['nodes'][1];n['frameId']='child'
        self.assertNotIn((2,'button'),main_nodes(p.full['axtree_object'],'main'))
        with self.assertRaises(ObservationChanged):p.validate()

    def test_custody_or_document_fence(self):
        p=self.validator();p.identity=lambda:{'different':'document or custody cycle'}
        with self.assertRaises(ObservationChanged):p.validate()

    def test_partial_policy_retains_full_visit_ledger_and_budget(self):
        ax=AXContext(AXConfig(tokenizer_path(),incremental=True,overview_tokens=512))
        value=obs();ax.prepare_observation(value);ax.acknowledge();seen=deepcopy(ax.seen)
        value['observation_capture']={'coverage':'partial','version':'dynamic-main-preview-v1',
            'node_limit':64,'preview_nodes_omitted':1000}
        for n in value['axtree_object']['nodes']:n.pop('browsergym_id',None)
        text=ax.prepare_observation(value);ax.acknowledge()
        self.assertLessEqual(ax.tokens(text),512);self.assertEqual(seen,ax.seen)
        self.assertIn('No clickable BIDs',text);self.assertNotIn('"bid"',text)

if __name__=='__main__':unittest.main()


def test_preview_bid_must_survive_full_capture():
    p=DynamicTests().validator()
    node=p.full['axtree_object']['nodes'][1]
    node['browsergym_id']='7'
    p.pending['bids']=[(node['backendDOMNodeId'],node['role']['value'],'7')]
    p.validate()
    node['browsergym_id']='8'
    with __import__('pytest').raises(ObservationChanged,match='BID'):
        p.validate()


def test_preview_bid_duplicate_fails_closed():
    p=DynamicTests().validator()
    node=p.full['axtree_object']['nodes'][1];node['browsergym_id']='7'
    p.pending['bids']=[(node['backendDOMNodeId'],node['role']['value'],'7')]
    duplicate=deepcopy(node);duplicate.update(nodeId='other',backendDOMNodeId=999)
    p.full['axtree_object']['nodes'].append(duplicate)
    with __import__('pytest').raises(ObservationChanged,match='ambiguous'):
        p.validate()


def test_v2_partial_delivers_bid_without_acknowledging_full_tree():
    ax=AXContext(AXConfig(tokenizer_path(),incremental=True,overview_tokens=512))
    value=obs();ax.prepare_observation(value);ax.acknowledge();seen=deepcopy(ax.seen)
    value['observation_capture']={'coverage':'partial','version':'dynamic-main-preview-v2',
        'preview_bids':True,'node_limit':64,'preview_nodes_omitted':0}
    text=ax.prepare_observation(value);ax.acknowledge()
    assert '"bid"' in text
    assert 'validates identity' in text
    assert ax.seen==seen
    assert ax.tokens(text)<=512
