"""Repository-owned modern chat presentation, using BrowserGym's chat backend.

Keep callbacks, message storage, recordings and browser ownership upstream.
The reset binding is instance-local so independent environments do not compete
for a global Chat factory. WindowsChrome supplies its existing isolated launcher.
"""
from contextlib import contextmanager
from importlib.metadata import version
from importlib.resources import files
from types import FunctionType, MethodType

from browsergym.core.env import BrowserEnv


def chat_template():
    return files('intent_browser').joinpath('assets/chat/chat.html').read_text(encoding='utf-8')


def create_chat(factory, *args, **kwargs):
    """Replace presentation immediately after creation, before any goal messages."""
    if kwargs.get('modern', True) is False:
        return factory(*args, **kwargs)
    template = chat_template()
    chat = factory(*args, **kwargs)
    # The Windows launcher may have already installed this template.
    if not getattr(chat, '_intent_chat_ui_installed', False):
        # set_content alone retains the previous document's global lexical
        # bindings. A fresh private document lets the template scripts initialize
        # while Playwright reinstalls the existing send_user_message binding.
        try:
            chat.page.goto('about:blank')
            chat.page.set_content(template)
        except BaseException:
            chat.close()
            raise
        chat._intent_chat_ui_installed = True
    return chat


@contextmanager
def repo_chat_ui(env):
    """Use the repo template during native reset without changing module globals.

    Custom environment reset implementations retain their own chat setup.
    Restore the instance's original reset even if setup fails.
    """
    base = getattr(env, 'unwrapped', env)
    reset = getattr(base, 'reset', None)
    if not isinstance(base, BrowserEnv) or getattr(reset, '__func__', None) is not BrowserEnv.reset:
        yield False
        return
    if version('browsergym-core') != '0.14.3':
        raise ValueError('Repository chat binding requires BrowserGym 0.14.3')
    original = reset.__func__
    scope = dict(original.__globals__)
    factory = scope['Chat']
    scope['Chat'] = lambda *args, **kwargs: create_chat(factory, *args, **kwargs)
    bound = FunctionType(original.__code__, scope, original.__name__,
                         original.__defaults__, original.__closure__)
    bound.__kwdefaults__ = original.__kwdefaults__
    previous = vars(base).get('reset')
    had_reset = 'reset' in vars(base)
    base.reset = MethodType(bound, base)
    try:
        yield True
    finally:
        if had_reset:
            base.reset = previous
        else:
            del base.reset
