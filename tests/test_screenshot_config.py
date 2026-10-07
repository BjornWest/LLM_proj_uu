from unittest.mock import Mock, patch
import pytest
from tests.runner_diagnostics import run_episode
from intent_browser.standard_profile import standard_profile


@pytest.mark.parametrize('value', [0,1,'false',[],{}])
def test_invalid_option_rejected_before_environment_or_backend(value):
    factory=Mock();backend=Mock()
    with pytest.raises(ValueError,match='trace_screenshots must be boolean'):
        run_episode(factory,backend,{},trace_screenshots=value)
    factory.assert_not_called();backend.assert_not_called()


def test_screenshot_setting_inherited_by_root_and_helpers():
    runtime=Mock()
    runtime.run.side_effect=lambda launch:launch({'backend':None})
    # Enter the real initial call; capture only its delegated recursive call.
    with patch('intent_browser.delegation.AgentRuntime',return_value=runtime) as cls, \
         patch('intent_browser.runner.run_episode',return_value='child-result') as recursive:
        result=run_episode(None,None,{},harness_profile=standard_profile(helpers=True,data_tools=False),trace_screenshots=False)
    assert result=='child-result'
    assert cls.call_args.args[5]['trace_screenshots'] is False
    assert recursive.call_args.kwargs['trace_screenshots'] is False
