from dataclasses import replace
from types import SimpleNamespace as NS
from unittest.mock import patch
import pytest
from intent_browser.runtime_defaults import select_observation_pipeline
from intent_browser.observation_pipeline import ObservationPipelineConfig


class Background:
    supports_background_completion=True


class Unreviewed(Background):pass


def profile():
    return NS(tools=NS(human_handover_tools=True,open_internet=True,stable_frame_capture=True),
              agent_limits=None,ax_config=NS(incremental=True))


def task():
    return NS(supports_observation_pipeline='native_full_only',supports_dynamic_preview=True,
              supports_targeted_observations=True)


def choose(value='auto',**changes):
    args=dict(profile=profile(),backend=Background(),task=task(),trace_screenshots=None)
    args.update(changes);return select_observation_pipeline(value,**args)


def test_reviewed_auto_matches_live_configuration_without_changing_tools():
    p=profile();before=vars(p.tools).copy();c,r=choose(profile=p)
    assert c==ObservationPipelineConfig((),full_capture_only=True,dynamic_preview=True,shallow_depth=2,
                 preview_node_limit=64,preview_bids=True,trace_screenshots=False,targeted_actions=True)
    assert r['selected']=='preview_targeted' and vars(p.tools)==before


def test_explicit_config_and_none_are_not_upgraded():
    c=ObservationPipelineConfig((),full_capture_only=True)
    for value in (c,None):
        selected,r=choose(value)
        assert selected is value and r['reason']=='caller_configuration'
    selected,r=choose('native')
    assert not selected.dynamic_preview and selected.trace_screenshots
    assert r['reason']=='explicit_native'


def test_screenshots_preserve_full_post_action_capture():
    c,r=choose(trace_screenshots=True)
    assert c.trace_screenshots and c.dynamic_preview and not c.targeted_actions
    assert r['selected']=='preview_full_post_action'
    assert choose(trace_screenshots=False)[0].targeted_actions


@pytest.mark.parametrize('missing',('supports_observation_pipeline','supports_dynamic_preview','supports_targeted_observations'))
def test_grader_capability_is_required(missing):
    t=task();setattr(t,missing,False)
    c,r=choose(task=t)
    assert not c.dynamic_preview and r['reason']=='adapter_not_fast_capture_certified'


def test_background_capability_cannot_be_inherited_by_accident():
    c,r=choose(backend=Unreviewed())
    assert not c.dynamic_preview and r['reason']=='backend_not_background_certified'
    backend=Background();backend.requires_browser_thread=True
    assert not choose(backend=backend)[0].dynamic_preview


def test_benchmark_helpers_legacy_and_missing_tracking_remain_native():
    p=profile();p.tools.human_handover_tools=False
    assert choose(profile=p)[0] is None
    assert choose(profile=None)[0] is None
    for change in ('stable_frames','helpers','incremental'):
        p=profile()
        if change=='stable_frames':p.tools.stable_frame_capture=False
        elif change=='helpers':p.agent_limits=object()
        else:p.ax_config.incremental=False
        assert not choose(profile=p)[0].dynamic_preview


@pytest.mark.parametrize('value',('typo','fast'))
def test_invalid_mode_rejected(value):
    with pytest.raises(ValueError):choose(value)


@pytest.mark.parametrize('mode,images',(('auto',None),('native',None),('auto',True),('auto',False)))
def test_cli_current_path_uses_auto_with_stable_frames_and_image_capability(mode,images):
    from intent_browser.cli import main
    argv=['intent-browser','run','--open-internet','--human-handover','--headful','--no-subagents',
          '--url','https://example.test/','--goal','Inspect','--no-preview',
          '--model','offline','--base-url','http://localhost:9990/v1','--observation-mode',mode]
    if images is not None:argv.append('--screenshots' if images else '--no-screenshots')
    with patch('sys.argv',argv),patch.dict('os.environ',{},clear=True), \
            patch('intent_browser.cli.ChatCompletionsBackend') as backend, \
            patch('intent_browser.human_handover_ui.HumanHandoverUI'), \
            patch('intent_browser.cli.run_episode',return_value=('unused',{'error':None})) as run:
        main()
    opts=run.call_args.kwargs
    assert opts['observation_pipeline']==mode
    assert opts['trace_screenshots'] is images
    assert opts['harness_profile'].tools.stable_frame_capture
    assert opts['harness_profile'].tools.compact_tab_context
    assert backend.call_args.kwargs['supports_images'] is True


def test_explicit_older_cli_profile_keeps_its_capture_capabilities():
    from intent_browser.cli import main
    argv=['intent-browser','run','--open-internet','--human-handover','--headful','--no-subagents',
          '--harness-profile','core-tools-v10-agents','--url','https://example.test/',
          '--goal','Inspect','--no-preview','--model','offline','--base-url','http://localhost:9990/v1']
    with patch('sys.argv',argv),patch.dict('os.environ',{},clear=True), \
            patch('intent_browser.cli.ChatCompletionsBackend'), \
            patch('intent_browser.human_handover_ui.HumanHandoverUI'), \
            patch('intent_browser.cli.run_episode',return_value=('unused',{'error':None})) as run:
        main()
    assert not run.call_args.kwargs['harness_profile'].tools.stable_frame_capture
    assert not run.call_args.kwargs['harness_profile'].tools.compact_tab_context
