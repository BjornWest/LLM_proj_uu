import asyncio
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch
import pytest

from intent_browser.native_capture import CaptureBudget, CaptureDeadlineExceeded
from intent_browser.harness import native_tools_profile
from intent_browser.open_internet import open_profile, with_human_handover


def test_diagnostic_reports_overrun_while_rpc_still_pending_without_cancellation():
    async def run():
        events=[]
        trace=SimpleNamespace(event=lambda name,**kw:events.append((name,kw)))
        connection=SimpleNamespace(_loop=asyncio.get_running_loop())
        page=SimpleNamespace(_impl_obj=SimpleNamespace(_connection=connection))
        budget=CaptureBudget(page,trace,seconds=.01,enforce=False)
        budget.phase='deliberately_slow_read'
        with budget.rpc_deadline():
            await asyncio.sleep(.03)
            assert len(events)==1  # Written before the operation/context exits.
            assert events[0][1]['phase']=='deliberately_slow_read'
            budget.check()
        assert len(events)==1 and events[0][1]['enforced'] is False
    asyncio.run(run())


def test_bounded_budget_still_raises():
    budget=CaptureBudget(None,None,seconds=0)
    with pytest.raises(CaptureDeadlineExceeded):budget.check()


def test_human_test_defaults_diagnostic_with_explicit_bounded_option():
    base=native_tools_profile()
    ordinary=open_profile(replace(base,tools=replace(base.tools,batch_size=4)))
    diagnostic=with_human_handover(ordinary)
    bounded=with_human_handover(ordinary,capture_timeout_mode='bounded')
    assert diagnostic.capture_timeout_mode=='diagnostic'
    assert bounded.capture_timeout_mode=='bounded'
    assert diagnostic.describe()['capture_timeout_mode']=='diagnostic'
    assert '+capture-diagnostic-v1' in diagnostic.name
    assert diagnostic.instructions==bounded.instructions
    assert diagnostic.tools.definitions()==bounded.tools.definitions()
    assert 'capture_timeout_mode' not in ordinary.describe()
    assert ordinary.capture_timeout_mode=='bounded'
    with pytest.raises(ValueError):with_human_handover(ordinary,capture_timeout_mode='typo')


@pytest.mark.parametrize('mode',['diagnostic','bounded'])
def test_cli_passes_explicit_mode_to_episode_profile(mode):
    from intent_browser.cli import main
    argv=['intent-browser','run','--open-internet','--human-handover','--headful','--no-subagents',
          '--url','https://example.test/','--goal','Inspect the page','--no-preview','--capture-timeout-mode',mode,
          '--model','offline','--base-url','http://localhost:9990/v1']
    with patch('sys.argv',argv),patch.dict('os.environ',{},clear=True), \
            patch('intent_browser.cli.ChatCompletionsBackend'), \
            patch('intent_browser.human_handover_ui.HumanHandoverUI'), \
            patch('intent_browser.cli.run_episode',return_value=('unused',{'error':None})) as run:
        main()
    assert run.call_args.kwargs['harness_profile'].capture_timeout_mode==mode
