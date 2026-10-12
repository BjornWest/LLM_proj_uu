"""Version-pinned resource close, preserving task teardown exactly once.

Close independent owned resources even after an earlier close fails. Context
close still finalizes recordings normally; failures never certify those files.
Caller supplies timed/bounded phase execution. No model or action retries.
"""
import inspect
import hashlib
from importlib.metadata import version
from browsergym.core.env import BrowserEnv
from browsergym.core.chat import Chat


def supported(env):
    from .shared_browsergym import supported_shared
    if supported_shared(env):return True
    return (version('browsergym-core')=='0.14.3' and type(env) is BrowserEnv
        and getattr(env.close,'__func__',None) is BrowserEnv.close
        and hashlib.sha256(inspect.getsource(BrowserEnv.close).encode()).hexdigest()==
            'f8ecb729634b9b0c56876d3bee8a3205620ec517c66c5f39173f6860bbc55a45')


def close_resources(env,phase,*,shared_close=None):
    # Only the qualified pooled method supplies its bound original. External
    # shutdown callers still inspect env.close and cannot skip instrumentation.
    if shared_close is None:
        qualified = supported(env)
    else:
        from .shared_browsergym import _supported_shared_close
        qualified = _supported_shared_close(env, shared_close)
    if not qualified:raise ValueError('Resource shutdown requires native BrowserGym close')
    failures=[]
    def attempt(name,fn,seconds=2):
        try:phase(name,fn,seconds=seconds);return True
        except Exception as exc:
            failures.append({'phase':name,'error':f'{type(exc).__name__}: {exc}'})
            return False
    if env.task and attempt('task_teardown',env.task.teardown):env.task=None
    if env.chat:
        chat=env.chat
        if (type(chat) is Chat and getattr(chat.close,'__func__',None) is Chat.close
                and hashlib.sha256(inspect.getsource(Chat.close).encode()).hexdigest()==
                    'c49a92cf0b91c845e2daa7217435c9b09137142ce9b62d93fa3905bc53930f7b'):
            context_ok=attempt('chat_context_close',chat.context.close,seconds=5)
            browser_ok=attempt('chat_browser_close',chat.browser.close)
            if browser_ok:env.chat=None
        else:
            if attempt('custom_chat_close',chat.close,seconds=5):env.chat=None
            elif getattr(chat,'browser',None):attempt('chat_browser_fallback',chat.browser.close)
    if env.context and attempt('task_context_close',env.context.close,seconds=5):env.context=None
    if env.browser and attempt('task_browser_close',env.browser.close):env.browser=None;env.context=None
    return failures
