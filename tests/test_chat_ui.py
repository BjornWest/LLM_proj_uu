from types import FunctionType, SimpleNamespace
from unittest.mock import Mock, call

import pytest
from browsergym.core.env import BrowserEnv

from intent_browser.chat_ui import chat_template, create_chat, repo_chat_ui


def fixture_reset(self, seed=None):
    self.chat = Chat(headless=True)
    self.chat.add_message('user', 'Original goal')
    return seed, {}


@pytest.fixture
def native_reset(monkeypatch):
    chat = Mock()
    chat._intent_chat_ui_installed = False
    factory = Mock(return_value=chat)
    scope = {**fixture_reset.__globals__, 'Chat': factory}
    reset = FunctionType(fixture_reset.__code__, scope, argdefs=fixture_reset.__defaults__)
    monkeypatch.setattr(BrowserEnv, 'reset', reset)
    return reset, factory, chat


def test_template_loaded_before_goal_and_upstream_factory_preserved(native_reset):
    reset, factory, chat = native_reset
    env = object.__new__(BrowserEnv)
    with repo_chat_ui(env) as configured:
        assert configured
        assert env.reset(seed=42) == (42, {})
        assert reset.__globals__['Chat'] is factory
    assert env.reset.__func__ is reset
    assert 'reset' not in vars(env)
    factory.assert_called_once_with(headless=True)
    assert chat.mock_calls == [call.page.goto('about:blank'), call.page.set_content(chat_template()),
                               call.add_message('user', 'Original goal')]


def test_independent_environments_have_separate_reset_scopes(native_reset):
    reset, factory, _ = native_reset
    first, second = object.__new__(BrowserEnv), object.__new__(BrowserEnv)
    with repo_chat_ui(first):
        with repo_chat_ui(second):
            assert first.reset.__func__.__globals__ is not second.reset.__func__.__globals__
            assert reset.__globals__['Chat'] is factory
        assert second.reset.__func__ is reset
        assert first.reset.__func__ is not reset
    assert first.reset.__func__ is reset


def test_reset_restored_after_setup_failure(native_reset):
    reset, factory, _ = native_reset
    factory.side_effect = RuntimeError('launch failed')
    env = object.__new__(BrowserEnv)
    # Preserve even an explicitly bound native reset on the instance.
    env.reset = reset.__get__(env)
    previous = env.reset
    with pytest.raises(RuntimeError, match='launch failed'), repo_chat_ui(env):
        env.reset()
    assert env.reset is previous


def test_windows_template_is_not_loaded_twice():
    chat = Mock(_intent_chat_ui_installed=True)
    factory = Mock(return_value=chat)
    assert create_chat(factory, headless=False) is chat
    chat.page.goto.assert_not_called()
    chat.page.set_content.assert_not_called()


def test_failed_template_install_closes_the_new_chat():
    chat = Mock(_intent_chat_ui_installed=False)
    chat.page.set_content.side_effect = RuntimeError('document closed')
    with pytest.raises(RuntimeError, match='document closed'):
        create_chat(Mock(return_value=chat), headless=True)
    chat.close.assert_called_once()


def test_custom_reset_is_unchanged():
    env = SimpleNamespace(reset=Mock())
    previous = env.reset
    with repo_chat_ui(env) as configured:
        assert not configured
        assert env.reset is previous


def test_classic_chat_keeps_its_explicit_factory():
    factory = Mock()
    assert create_chat(factory, headless=True, modern=False) is factory.return_value
    factory.return_value.page.set_content.assert_not_called()
