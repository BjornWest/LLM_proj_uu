"""Generated-world fast capture: selection, lazy overview packing, BID/fact plumbing.

Model-free unit tests. Real-browser behaviour is covered by the scripted
latency driver (scripts/generated_world_latency.py) and its saved evidence.
"""
from types import SimpleNamespace as NS
import json
import pytest

from intent_browser.runtime_defaults import select_observation_pipeline
from intent_browser.observation_pipeline import ObservationPipelineConfig


class Background:
    supports_background_completion = True


class BrowserThreadBackend:
    supports_background_completion = True
    requires_browser_thread = True


def generated_profile(**tools):
    values = dict(human_handover_tools=False, open_internet=False, stable_frame_capture=False,
                  parse_completion=lambda *a: None)
    values.update(tools)
    return NS(tools=NS(**values), agent_limits=None, ax_config=NS(incremental=True))


def generated_task(**changes):
    values = dict(supports_observation_pipeline='native_full_only', supports_dynamic_preview=True,
                  supports_targeted_observations=True, supports_agent_fast_capture=True)
    values.update(changes)
    return NS(**values)


def choose(value='auto', **changes):
    args = dict(profile=generated_profile(), backend=Background(), task=generated_task(), trace_screenshots=None)
    args.update(changes)
    return select_observation_pipeline(value, **args)


def test_declared_generated_world_selects_agent_budgeted_targeted_capture():
    config, record = choose()
    assert config == ObservationPipelineConfig((), full_capture_only=True, dynamic_preview=True, preview_bids=True,
        trace_screenshots=False, targeted_actions=True, agent_custody=True, decision_capture='budgeted_overview')
    assert record == {'version': 'browser-runtime-defaults-v2', 'requested': 'auto',
                      'selected': 'agent_budgeted_targeted', 'reason': 'reviewed_capabilities'}


def test_explicit_screenshots_keep_full_post_action_capture():
    config, record = choose(trace_screenshots=True)
    assert config.agent_custody and config.trace_screenshots and not config.targeted_actions
    assert record['selected'] == 'agent_budgeted_full_post_action'


def test_explicit_native_and_concrete_configs_are_not_upgraded():
    assert choose('native')[0] is None and choose('native')[1]['reason'] == 'explicit_native'
    concrete = ObservationPipelineConfig((), full_capture_only=True)
    assert choose(concrete)[0] is concrete


@pytest.mark.parametrize('task,reason', [
    (None, 'requires_live_web_tab_tracking'),
    (generated_task(supports_agent_fast_capture=False), 'requires_live_web_tab_tracking'),
    (generated_task(supports_dynamic_preview=False), 'adapter_not_agent_fast_capture_certified'),
    (generated_task(supports_targeted_observations=False), 'adapter_not_agent_fast_capture_certified'),
    (generated_task(supports_observation_pipeline=False), 'adapter_not_agent_fast_capture_certified'),
])
def test_adapter_declarations_are_required(task, reason):
    config, record = choose(task=task)
    assert config is None and record['selected'] == 'native' and record['reason'] == reason


def test_backend_and_profile_gates_fall_back_with_reasons():
    assert choose(backend=BrowserThreadBackend())[1]['reason'] == 'backend_not_background_certified'

    class Inherited(Background):
        pass
    assert choose(backend=Inherited())[1]['reason'] == 'backend_not_background_certified'
    helpers = generated_profile(); helpers.agent_limits = object()
    assert choose(profile=helpers)[1]['reason'] == 'requires_incremental_ax_without_helpers'
    assert choose(profile=generated_profile(open_internet=True))[1]['reason'] == \
        'open_internet_requires_live_web_tab_tracking'


def test_budgeted_config_requires_agent_custody_and_dynamic_capture():
    with pytest.raises(ValueError):
        ObservationPipelineConfig((), full_capture_only=True, dynamic_preview=True, decision_capture='budgeted_overview')
    with pytest.raises(ValueError):
        ObservationPipelineConfig(('https://a.test',), full_capture_only=False, agent_custody=True)
    with pytest.raises(ValueError):
        ObservationPipelineConfig((), full_capture_only=True, decision_capture='unknown')


# -- overview packing ----------------------------------------------------------

def _ax_tree(width=40, depth=3):
    """Synthetic AX tree: nested regions with named links and text."""
    nodes = [{'nodeId': '1', 'role': {'value': 'RootWebArea'}, 'name': {'value': 'Shop'}, 'childIds': [],
              'backendDOMNodeId': 1, 'frameId': 'F'}]
    counter = [1]
    def add(parent, level):
        for i in range(width if level == 0 else 4):
            counter[0] += 1
            ident = str(counter[0])
            role = 'region' if level < depth - 1 else 'link'
            node = {'nodeId': ident, 'role': {'value': role}, 'name': {'value': f'{role} {ident} ' + 'x' * (i % 7)},
                    'childIds': [], 'backendDOMNodeId': counter[0], 'browsergym_id': ident}
            nodes.append(node); parent['childIds'].append(ident)
            if level < depth - 1:
                add(node, level + 1)
    add(nodes[0], 0)
    return {'nodes': nodes}


@pytest.fixture(scope='module')
def ax_config():
    from intent_browser.standard_profile import standard_profile
    return standard_profile(helpers=False, data_tools=False).ax_config


@pytest.mark.parametrize('budget', [512, 1000, 2000, 4000])
@pytest.mark.parametrize('repeat', [False, True])
def test_lazy_overview_packing_matches_eager_packing(ax_config, budget, repeat):
    from intent_browser.ax_context import AXContext, LazyEntries
    observation = {'url': 'https://shop.test/', 'axtree_object': _ax_tree(), 'open_pages_urls': ['https://shop.test/']}
    outputs = []
    for lazy in (False, True):
        context = AXContext(ax_config)
        if not lazy:
            original = context._page_entries
            def eager(verbose, repeat, original=original, context=context):
                entries, full = original(verbose, repeat)
                if isinstance(entries, LazyEntries):
                    entries = context._entries(entries.refs, verbose, repeat)
                return entries, full
            context._page_entries = eager
        first = context.page_update(observation, budget=budget, stage=False, repeat=repeat or None)
        second = context.page_update(None, budget=budget, stage=False, repeat=True, offset=first.get('next_offset') or 0)
        outputs.append(json.dumps([first, second], sort_keys=True))
    assert outputs[0] == outputs[1]
    assert json.loads(outputs[1])[0]['items']


def test_lazy_entries_only_support_offset_slices(ax_config):
    from intent_browser.ax_context import LazyEntries
    entries = LazyEntries(None, ['a', 'b', 'c'], False, False)
    assert len(entries) == 3 and len(entries[1:]) == 2 and bool(entries[3:]) is False
    with pytest.raises(TypeError):
        entries[0]


# -- decision BIDs and validation ------------------------------------------------

def test_breadth_first_candidates_follow_overview_filter():
    from intent_browser.budgeted_decision import breadth_first_elements
    nodes = [
        {'nodeId': '1', 'role': {'value': 'RootWebArea'}, 'name': {'value': 'T'}, 'childIds': ['2', '5'],
         'backendDOMNodeId': 1, 'frameId': 'F'},
        {'nodeId': '2', 'role': {'value': 'generic'}, 'childIds': ['3'], 'backendDOMNodeId': 2},
        {'nodeId': '3', 'role': {'value': 'link'}, 'name': {'value': 'Deep'}, 'childIds': ['4'], 'backendDOMNodeId': 3},
        {'nodeId': '4', 'role': {'value': 'StaticText'}, 'name': {'value': 'Deep'}, 'childIds': [], 'backendDOMNodeId': 4},
        {'nodeId': '5', 'role': {'value': 'button'}, 'name': {'value': 'Buy'}, 'childIds': [], 'backendDOMNodeId': 5},
    ]
    # Unnamed generic wrapper is skipped, its link child joins the first level;
    # StaticText duplicating its parent name is not a candidate.
    assert breadth_first_elements(nodes, 'F', 10) == [3, 5]
    assert breadth_first_elements(nodes, 'F', 1) == [3]
    assert breadth_first_elements(nodes, 'OTHER', 10) == []


def test_bid_map_is_scoped_to_one_document():
    from intent_browser.agent_browser import AgentBrowser
    browser = AgentBrowser.__new__(AgentBrowser)
    browser.bid_map, browser.bid_document = {}, None
    browser.remember_bids({'doc': 1}, {5: '1'})
    assert browser.known_bids({'doc': 1}) == {5: '1'}
    assert browser.known_bids({'doc': 2}) == {}
    browser.remember_bids({'doc': 2}, {6: '9'})
    assert browser.known_bids({'doc': 2}) == {6: '9'} and browser.known_bids({'doc': 1}) == {}


def test_dom_bid_map_and_attach_skip_text_nodes():
    from intent_browser.agent_browser import dom_bid_map, attach_bids
    dom = {'strings': ['F', 'bid', '7', 'class', 'x'], 'documents': [{'frameId': 0, 'nodes': {
        'backendNodeId': [10, 11, 12], 'attributes': [[1, 2], [3, 4], []]}}]}
    bids = dom_bid_map(dom)
    assert bids == {10: '7'}
    tree = {'nodes': [{'nodeId': 'a', 'backendDOMNodeId': 10, 'role': {'value': 'link'}, 'browsergym_id': 'old'},
                      {'nodeId': 'b', 'backendDOMNodeId': 10, 'role': {'value': 'StaticText'}},
                      {'nodeId': 'c', 'backendDOMNodeId': 11, 'role': {'value': 'button'}, 'browsergym_id': 'stale'}]}
    attach_bids(tree, bids)
    assert [n.get('browsergym_id') for n in tree['nodes']] == ['7', None, None]


def _decision(pending_tree, full_tree, *, revision=(1, 1), bids=()):
    from intent_browser.budgeted_decision import BudgetedDecision
    decision = BudgetedDecision.__new__(BudgetedDecision)
    identity = {'tab': 't', 'cycle': None, 'document': {'frame_id': 'F'}}
    decision.identity = lambda: identity
    decision.pending = {'identity': identity, 'revision': {'revision': revision[0]}, 'tree': pending_tree,
                        'bids': list(bids)}
    decision.full = {'human_tab_capture': {'document': identity['document']}, 'axtree_object': full_tree,
                     'page_revision': {'revision': revision[1]}}
    return decision


def test_validation_accepts_unchanged_revision_and_matching_bids():
    tree = {'nodes': [{'nodeId': '1', 'role': {'value': 'link'}, 'backendDOMNodeId': 3, 'browsergym_id': '9'}]}
    _decision(tree, tree, bids=[(3, 'link', '9')]).validate()


def test_validation_rejects_changed_page_and_moved_bid():
    from intent_browser.observation_pipeline import ObservationChanged
    before = {'nodes': [{'nodeId': '1', 'role': {'value': 'link'}, 'name': {'value': 'A'}, 'backendDOMNodeId': 3}]}
    after = {'nodes': [{'nodeId': '1', 'role': {'value': 'link'}, 'name': {'value': 'B'}, 'backendDOMNodeId': 3}]}
    with pytest.raises(ObservationChanged):
        _decision(before, after, revision=(1, 2)).validate()
    # A revision change with identical AX semantics (e.g. an irrelevant attribute) is accepted.
    _decision(before, json.loads(json.dumps(before)), revision=(1, 2)).validate()
    moved = {'nodes': [{'nodeId': '1', 'role': {'value': 'link'}, 'backendDOMNodeId': 3, 'browsergym_id': '10'}]}
    with pytest.raises(ObservationChanged):
        _decision(moved, moved, bids=[(3, 'link', '9')]).validate()


# -- fact provenance from the harness DOM snapshot --------------------------------

def _snapshot():
    # <html><body><div id=app><p>Price<!--c--><b>480 kr</b></p></div></body></html>, li::marker pseudo.
    strings = ['F', '#document', 'HTML', 'BODY', 'DIV', 'id', 'app', 'P', '#text', 'Price', '#comment', 'c',
               'B', '480 kr', '::marker']
    nodes = {'parentIndex': [-1, 0, 1, 2, 3, 4, 4, 4, 7, 4],
             'nodeType': [9, 1, 1, 1, 1, 3, 8, 1, 3, 1],
             'nodeName': [1, 2, 3, 4, 7, 8, 10, 12, 8, 14],
             'nodeValue': [-1, -1, -1, -1, -1, 9, 11, -1, 13, -1],
             'backendNodeId': [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
             'attributes': [[], [], [], [5, 6], [], [], [], [], [], []],
             'pseudoType': {'index': [9], 'value': [14]}}
    return {'strings': strings, 'documents': [{'frameId': 0, 'nodes': nodes}]}


def test_snapshot_tree_follows_child_nodes_order_without_pseudo_elements():
    from training.browser_training.fact_render_capture import snapshot_tree
    app, document = snapshot_tree(_snapshot(), 'F', '#app')
    assert document == 1 and app['backendNodeId'] == 4
    paragraph = app['children'][0]
    assert [c['nodeType'] for c in paragraph['children']] == [3, 8, 1]  # text, comment, element; no ::marker
    assert paragraph['children'][2]['children'][0]['nodeValue'] == '480 kr'
    with pytest.raises(ValueError):
        snapshot_tree(_snapshot(), 'OTHER', '#app')
    with pytest.raises(ValueError):
        snapshot_tree(_snapshot(), 'F', '#missing')
