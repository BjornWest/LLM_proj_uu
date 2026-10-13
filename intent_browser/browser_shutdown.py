"""Version-pinned resource close, preserving task teardown exactly once.

Close independent owned resources even after an earlier close fails. Context
close still finalizes recordings normally; failures never certify those files.
Caller supplies timed/bounded phase execution. No model or action retries.
"""
from contextlib import contextmanager, ExitStack
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


def close_resources(env,phase):
    if not supported(env):raise ValueError('Resource shutdown requires native BrowserGym close')
    return _close_qualified_resources(env,phase)


def _close_qualified_resources(env,phase):
    """Private cleanup body; entrypoints must qualify their actual close first."""
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


@contextmanager
def cleanup_rpc_budget(env, trace, *, seconds, phase, required=False):
    """Bound RPC awaits on owned task/chat connections, not Python callbacks.

    Inspect existing local handles only. A pooled chat can use a different
    connection from the task page; both must be covered. No browser/group is
    closed by this budget and timed-out operations must never be replayed.
    An independent parent watchdog is still needed for blocked sync callbacks.
    """
    from .native_capture import CaptureBudget
    base = getattr(env, 'unwrapped', env)
    chat = getattr(base, 'chat', None)
    handles = [getattr(base, name, None) for name in ('page', 'context', 'browser')]
    handles += [getattr(chat, name, None) for name in ('page', 'context', 'browser')]
    carriers, seen = [], set()
    for handle in handles:
        connection = getattr(getattr(handle, '_impl_obj', None), '_connection', None)
        if connection is None or id(connection) in seen:
            continue
        if (not callable(getattr(connection, 'wrap_api_call', None))
                or not hasattr(connection, '_callbacks') or not hasattr(connection, '_loop')):
            raise ValueError('Unsupported cleanup Playwright connection')
        seen.add(id(connection)); carriers.append(handle)
    if required and not carriers:
        raise ValueError('Cleanup requires an existing Playwright connection')
    with ExitStack() as stack:
        for carrier in carriers:
            budget = CaptureBudget(carrier, trace, seconds=seconds, scope='browser_cleanup')
            budget.phase = 'teardown_' + phase
            stack.enter_context(budget.rpc_deadline())
        yield len(carriers)
