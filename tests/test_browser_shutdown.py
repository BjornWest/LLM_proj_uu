from types import SimpleNamespace
import pytest
from browsergym.core.env import BrowserEnv
from browsergym.core.chat import Chat
from intent_browser.browser_shutdown import close_resources,supported


@pytest.mark.parametrize('failed',[None,'task_teardown','chat_context_close','task_context_close'])
def test_independent_resources_closed_after_one_failure(failed):
    called=[]
    def operation(name):
        def execute():
            called.append(name)
            if name==failed:raise RuntimeError('Injected resource failure')
        return execute
    env=BrowserEnv.__new__(BrowserEnv)
    env.task=SimpleNamespace(teardown=operation('task_teardown'))
    env.chat=Chat.__new__(Chat)
    env.chat.context=SimpleNamespace(close=operation('chat_context_close'))
    env.chat.browser=SimpleNamespace(close=operation('chat_browser_close'))
    env.context=SimpleNamespace(close=operation('task_context_close'))
    env.browser=SimpleNamespace(close=operation('task_browser_close'))
    failures=close_resources(env,lambda name,fn,seconds:fn())
    assert called==['task_teardown','chat_context_close','chat_browser_close','task_context_close','task_browser_close']
    assert [r['phase'] for r in failures]==([failed] if failed else [])
    assert env.browser is None and env.context is None and env.chat is None


def test_custom_close_not_bypassed():
    env=BrowserEnv.__new__(BrowserEnv);env.close=lambda:None
    assert not supported(env)
    with pytest.raises(ValueError):close_resources(env,None)
