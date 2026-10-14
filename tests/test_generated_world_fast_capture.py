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


class _StubPage:
    """Playwright connection-wrapper boundary only; optional stalled RPC."""
    def __init__(self):
        import asyncio
        self.loop = asyncio.new_event_loop()
        async def wrap(cb, *args, **kwargs):
            return await cb()
        self.connection = NS(wrap_api_call=wrap, _callbacks={}, _loop=self.loop)
        self._impl_obj = NS(_connection=self.connection)

    def stalled(self, *args):
        import asyncio
        async def rpc():
            return await asyncio.Future()
        return self.loop.run_until_complete(self.connection.wrap_api_call(rpc))


def _decision(pending_tree, full_tree, *, revision=(1, 1), bids=(), live=None, current_tree=None, monkeypatch=None):
    """BudgetedDecision with stubbed identity; live settle state and fresh AX read are injectable."""
    from intent_browser import budgeted_decision
    from intent_browser.budgeted_decision import BudgetedDecision
    decision = BudgetedDecision.__new__(BudgetedDecision)
    identity = {'tab': 't', 'cycle': None, 'document': {'frame_id': 'F'}}
    decision.identity = lambda: identity
    decision.human = NS(env=NS(page=_StubPage()), capture_timeout_mode='bounded')
    decision.trace = NS(event=lambda *a, **k: None)
    decision.pending = {'identity': identity, 'revision': {'revision': revision[0]}, 'tree': pending_tree,
                        'bids': list(bids)}
    decision.full = {'human_tab_capture': {'document': identity['document']}, 'axtree_object': full_tree,
                     'page_revision': {'revision': revision[1]}}
    if monkeypatch is not None:
        state = {'revision': revision[0]} if live is None else live
        monkeypatch.setattr(budgeted_decision, 'settle_call', lambda page, expression, argument=None: state)
        monkeypatch.setattr(budgeted_decision, 'extract_json',
                            lambda extractor, page: current_tree if current_tree is not None else pending_tree)
    return decision


def test_validation_accepts_unchanged_revision_and_matching_bids(monkeypatch):
    tree = {'nodes': [{'nodeId': '1', 'role': {'value': 'link'}, 'backendDOMNodeId': 3, 'browsergym_id': '9'}]}
    decision = _decision(tree, tree, bids=[(3, 'link', '9')], monkeypatch=monkeypatch)
    decision.validate()
    assert decision.revision_proven is True


def test_validation_rejects_changed_page_and_moved_bid(monkeypatch):
    from intent_browser.observation_pipeline import ObservationChanged
    before = {'nodes': [{'nodeId': '1', 'role': {'value': 'link'}, 'name': {'value': 'A'}, 'backendDOMNodeId': 3}]}
    after = {'nodes': [{'nodeId': '1', 'role': {'value': 'link'}, 'name': {'value': 'B'}, 'backendDOMNodeId': 3}]}
    with pytest.raises(ObservationChanged):
        _decision(before, after, revision=(1, 2), live={'revision': 2}, monkeypatch=monkeypatch).validate()
    # A revision change with identical AX semantics (e.g. an irrelevant attribute)
    # is accepted for actions, but the revision is not proven for fact binding.
    same = _decision(before, json.loads(json.dumps(before)), revision=(1, 2), live={'revision': 2},
                     monkeypatch=monkeypatch)
    same.validate()
    assert same.revision_proven is False
    moved = {'nodes': [{'nodeId': '1', 'role': {'value': 'link'}, 'backendDOMNodeId': 3, 'browsergym_id': '10'}]}
    with pytest.raises(ObservationChanged):
        _decision(moved, moved, bids=[(3, 'link', '9')], monkeypatch=monkeypatch).validate()


def test_cached_bid_renumbered_by_marking_invalidates_decision(monkeypatch):
    # Review finding 1: a clone copied the original's cached BID; native marking
    # keeps it on the first occurrence (the clone) and renumbers the original.
    from intent_browser.observation_pipeline import ObservationChanged
    original = {'nodeId': '1', 'backendDOMNodeId': 3, 'role': {'value': 'button'}, 'name': {'value': 'Commit'},
                'browsergym_id': '9'}
    clone = {'nodeId': '2', 'backendDOMNodeId': 4, 'role': {'value': 'button'}, 'name': {'value': 'Decoy'},
             'browsergym_id': '9'}
    pending = {'nodes': [clone, original]}
    full = json.loads(json.dumps(pending)); full['nodes'][1]['browsergym_id'] = '10'
    published = [(n['backendDOMNodeId'], n['role']['value'], n['browsergym_id']) for n in pending['nodes']]
    with pytest.raises(ObservationChanged):
        _decision(pending, full, bids=published, monkeypatch=monkeypatch).validate()


def test_change_after_background_capture_is_read_at_completion(monkeypatch):
    # Review finding 2: decision and background agree (revision 1) but the live
    # page reached revision 2 with a changed price before the response arrived.
    from intent_browser.observation_pipeline import ObservationChanged
    tree = {'nodes': [{'nodeId': '1', 'backendDOMNodeId': 3, 'role': {'value': 'button'}, 'name': {'value': 'Buy'},
                       'browsergym_id': '9'},
                      {'nodeId': '2', 'backendDOMNodeId': 5, 'role': {'value': 'StaticText'}, 'name': {'value': '480 kr'}}]}
    late = json.loads(json.dumps(tree)); late['nodes'][1]['name']['value'] = '520 kr'
    with pytest.raises(ObservationChanged):
        _decision(tree, json.loads(json.dumps(tree)), live={'revision': 2}, current_tree=late,
                  bids=[(3, 'button', '9')], monkeypatch=monkeypatch).validate()
    # Tracker unavailable at completion: a fresh read must still match.
    unknown = _decision(tree, json.loads(json.dumps(tree)), current_tree=late, monkeypatch=monkeypatch)
    monkeypatch.setattr('intent_browser.budgeted_decision.settle_call', lambda *a, **k: None)
    with pytest.raises(ObservationChanged):
        unknown.validate()


def test_invalidated_decision_keeps_fact_mappings_unknown():
    # Review finding 3: decision outputs are re-bound only after validation proves
    # the same revision; an invalidated decision is never credited with new facts.
    from copy import deepcopy
    import threading
    from tests import test_fact_provenance as provenance_cases
    from intent_browser.observation_pipeline import ObservationPipeline
    case = provenance_cases.ProvenanceTests(); case.setUp()
    try:
        x, obs, recorder = case.fixture()
        recorder.pipeline_boundary = 'test-pipeline'
        obs['observation_capture'] = {'version': 'budgeted-decision-v1', 'coverage': 'full'}
        output = x.prepare_observation(obs)
        ledger, cid = case.policy(recorder, output)
        full = deepcopy(obs); full.pop('observation_capture')
        full['axtree_object']['nodes'][0]['name']['value'] = 'Different offer'
        case.state = 'state-2'
        decision = _decision(obs['axtree_object'], full['axtree_object'], revision=(1, 2))
        decision.full.update(full)
        def changed():
            from intent_browser.observation_pipeline import ObservationChanged
            raise ObservationChanged('Page changed during inference; decision context is stale')
        decision.validate = changed
        decision.capture = lambda: 'background-artifact'
        pipeline = ObservationPipeline.__new__(ObservationPipeline)
        pipeline.dynamic = decision; pipeline.pending = None; pipeline.pool = None
        pipeline.after_background = x.capture
        pipeline.after_validation = recorder.finish_decision
        class Backend:
            supports_background_completion = True
            def complete(self, messages):
                return 'retained-completion'
        event = {}
        assert pipeline.complete(Backend(), [], event) == 'retained-completion'
        pipeline.pool.shutdown()
        assert event['observation_pipeline']['invalidated'] is True
        case.receipt(ledger, cid)
        policy = json.loads((case.path / f'fact-policy-{cid}.json').read_text())
        assert policy['projections'] == []
        records = [json.loads(p.read_text()) for p in case.path.glob('fact-output-*.json')]
        assert any({'reason': 'decision_invalidated_no_rebinding'} in r['diagnostics'] for r in records)
    finally:
        case.doCleanups()


def test_proven_revision_rebinds_decision_facts():
    from copy import deepcopy
    from tests import test_fact_provenance as provenance_cases
    case = provenance_cases.ProvenanceTests(); case.setUp()
    try:
        x, obs, recorder = case.fixture()
        recorder.pipeline_boundary = 'test-pipeline'
        decision_obs = deepcopy(obs)
        decision_obs['observation_capture'] = {'version': 'budgeted-decision-v1', 'coverage': 'full'}
        output = x.prepare_observation(decision_obs)
        ledger, cid = case.policy(recorder, output)
        assert json.loads((case.path / f'fact-policy-{cid}.json').read_text())['projections'] == []
        x.capture(obs)  # background capture of the same page, with provenance
        recorder.finish_decision({'valid': True, 'revision_proven': True})
        case.receipt(ledger, cid)
        policy = json.loads((case.path / f'fact-policy-{cid}.json').read_text())
        assert policy['projections']
    finally:
        case.doCleanups()


def test_failed_completion_finalizes_its_decision_facts_and_later_decisions_cannot_rebind_them(monkeypatch):
    # Follow-up review finding 1: a failed completion must not leave its decision
    # outputs queued for a later, differently-revisioned decision to re-bind.
    from copy import deepcopy
    from intent_browser import budgeted_decision
    from intent_browser.observation_pipeline import ObservationPipeline
    from intent_browser.fact_provenance import encoded
    from intent_browser.native_tools import NativeConversation
    from tests import test_fact_provenance as provenance_cases
    case = provenance_cases.ProvenanceTests(); case.setUp()
    pipeline = ObservationPipeline.__new__(ObservationPipeline)
    pipeline.pending = None; pipeline.pool = None
    try:
        x, obs, recorder = case.fixture()
        recorder.pipeline_boundary = 'test-pipeline'
        pipeline.after_background = x.capture
        pipeline.after_validation = recorder.finish_decision
        def prepare(revision):
            decision_obs = deepcopy(obs)
            decision_obs['observation_capture'] = {'version': 'budgeted-decision-v1', 'coverage': 'full'}
            output = x.prepare_observation(decision_obs)
            decision = _decision(obs['axtree_object'], deepcopy(obs['axtree_object']), revision=(revision, revision))
            decision.full.update(obs)
            decision.capture = lambda: 'background-artifact'
            pipeline.dynamic = decision
            return output
        first = prepare(1)
        ledger, first_id = case.policy(recorder, first)
        conversation = NativeConversation()
        messages = conversation.request('system', 'goal', first if isinstance(first, str) else encoded(first),
                                        observation_source=first_id)
        class Failing:
            supports_background_completion = True
            def complete(self, messages): raise RuntimeError('synthetic transport failure')
        with pytest.raises(RuntimeError, match='synthetic transport failure'):
            pipeline.complete(Failing(), messages, {})
        assert recorder.deferred == []
        assert {'reason': 'decision_invalidated_no_rebinding'} in recorder.select(first)['record']['diagnostics']
        ledger.record({'step': 0, 'messages': messages, 'model_request': {'messages': messages}},
                      conversation.bindings(), acknowledged=False)
        conversation.recover(None, 'Retry after transport failure')
        case.state = 'state-2'; recorder.step = 1
        second = prepare(2)
        second_text = second if isinstance(second, str) else encoded(second)
        second_id = ledger.register('page_observation', second_text, step=1, fact_output=recorder.select(second))
        messages = conversation.request('system', 'goal', second_text, observation_source=second_id)
        class Success:
            supports_background_completion = True
            def complete(self, messages): return 'retained-completion'
        monkeypatch.setattr(budgeted_decision, 'settle_call', lambda *a, **k: {'revision': 2})
        assert pipeline.complete(Success(), messages, {}) == 'retained-completion'
        assert pipeline.dynamic.revision_proven
        ledger.record({'step': 1, 'messages': messages, 'model_request': {'messages': messages}},
                      conversation.bindings(), acknowledged=True)
        assert json.loads((case.path / f'fact-policy-{first_id}.json').read_text())['projections'] == []
        # The second decision (a proven revision) is itself re-bound; it only
        # references content already staged, so it carries no new projections.
        second_record = recorder.select(second)['record']
        assert {'reason': 'rebound_to_background_capture'} in second_record['diagnostics']
        assert second_record['capture'] != recorder.select(first)['record']['capture']
    finally:
        if pipeline.pool is not None: pipeline.pool.shutdown()
        case.doCleanups()


_STALL_CHILD = r"""
import sys, json
from copy import deepcopy
from types import SimpleNamespace as NS
from unittest.mock import patch
sys.path.insert(0, sys.argv[2])
from tests.test_generated_world_fast_capture import _decision
from intent_browser import budgeted_decision
from intent_browser.observation_pipeline import ObservationPipeline
TREE = {'nodes': [{'nodeId': '1', 'backendDOMNodeId': 3, 'role': {'value': 'button'},
                   'name': {'value': 'Commit'}, 'browsergym_id': '9'}]}
phase = sys.argv[1]
decision = _decision(TREE, deepcopy(TREE), bids=[(3, 'button', '9')])
decision.validation_seconds = 0.05
page = decision.human.env.page
decision.capture = lambda: 'background-artifact'
pipeline = ObservationPipeline.__new__(ObservationPipeline)
pipeline.dynamic = decision; pipeline.pending = None; pipeline.pool = None
class Backend:
    supports_background_completion = True
    def complete(self, messages): return 'retained-completion'
event = {}
if phase == 'live_state':
    state = patch.object(budgeted_decision, 'settle_call', side_effect=lambda *a, **k: page.stalled())
    ax = patch.object(budgeted_decision, 'extract_json', return_value=TREE)
else:
    state = patch.object(budgeted_decision, 'settle_call', return_value=None)
    ax = patch.object(budgeted_decision, 'extract_json', side_effect=lambda *a: page.stalled())
with state, ax:
    result = pipeline.complete(Backend(), [], event)
pipeline.pool.shutdown()
print(json.dumps({'result': result, 'invalidated': event['observation_pipeline'].get('invalidated'),
                  'error': event['observation_pipeline']['background_error']}))
"""


@pytest.mark.parametrize('phase', ['live_state', 'fresh_ax'])
def test_completion_validation_reads_are_bounded(tmp_path, phase):
    # Follow-up review finding 2: a stalled completion-time read returns the
    # completed response with an invalidated decision instead of hanging.
    import subprocess, sys
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    child = tmp_path / 'stall_child.py'; child.write_text(_STALL_CHILD)
    done = subprocess.run([sys.executable, str(child), phase, str(root)], capture_output=True, text=True, timeout=20)
    assert done.returncode == 0, done.stderr
    result = json.loads(done.stdout.strip().splitlines()[-1])
    assert result['result'] == 'retained-completion' and result['invalidated'] is True
    assert 'CaptureDeadlineExceeded' in result['error']


def test_page_settle_wait_is_bounded_and_xhr_settles_once(tmp_path):
    # Review finding 4 and the XHR counter: run the exact script in a Node VM.
    import shutil, subprocess
    from pathlib import Path
    import playwright
    node = Path(playwright.__file__).parent / 'driver' / 'node'
    if not node.exists():
        pytest.skip('bundled node unavailable')
    script = tmp_path / 'settle.cjs'
    script.write_text(r"""
const fs=require('node:fs'), vm=require('node:vm'); const {webcrypto}=require('node:crypto');
const source=fs.readFileSync(process.argv[2],'utf8');
function context(raf){
  class XHR extends EventTarget { send(){ if(this.active) throw new Error('InvalidStateError'); this.active=true; }
    finish(){ this.active=false; this.dispatchEvent(new Event('loadend')); } }
  const c=vm.createContext({performance,crypto:webcrypto,document:{},MutationObserver:class{observe(){}},
    addEventListener(){},HTMLInputElement:class{},HTMLTextAreaElement:class{},HTMLSelectElement:class{},
    HTMLOptionElement:class{},XMLHttpRequest:XHR,requestAnimationFrame:raf,setTimeout,clearTimeout});
  vm.runInContext(source,c); return c;
}
(async()=>{
  const stalled=context(()=>{});
  const first=await Promise.race([stalled.__intentPageSettle.wait(0,40),
    new Promise(r=>setTimeout(()=>r({status:'hung'}),400))]);
  const live=context(cb=>setTimeout(cb,1));
  const ready=await live.__intentPageSettle.wait(5,500);
  const x=new live.XMLHttpRequest(); x.send(); try{ x.send(); }catch{} x.finish();
  console.log(JSON.stringify({stalled:first.status, ready:ready.status, pending:live.__intentPageSettle.state().pending}));
})();
""")
    source = Path(__file__).resolve().parents[1] / 'intent_browser' / 'page_settle.js'
    result = json.loads(subprocess.run([str(node), str(script), str(source)], capture_output=True, text=True,
                                       timeout=30, check=True).stdout)
    assert result == {'stalled': 'frame_timeout', 'ready': 'ready', 'pending': 0}


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
