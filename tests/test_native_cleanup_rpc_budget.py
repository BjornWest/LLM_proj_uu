"""CPU-only cancellation/isolation proofs; no browser, model or recorded action."""
import asyncio
from types import SimpleNamespace
import pytest
from intent_browser.browser_shutdown import cleanup_rpc_budget
from intent_browser.native_capture import CaptureDeadlineExceeded


def connection():
    async def original(cb,*args,**kwargs):return await cb()
    return SimpleNamespace(wrap_api_call=original,_callbacks={},_loop=asyncio.get_running_loop())


def carrier(conn):return SimpleNamespace(_impl_obj=SimpleNamespace(_connection=conn))


@pytest.mark.parametrize('role',['task','chat'])
def test_distinct_pooled_connections_are_bounded_and_restored(role):
    async def run():
        task,chat,sibling=connection(),connection(),connection()
        before=[x.wrap_api_call for x in (task,chat,sibling)]
        env=SimpleNamespace(page=carrier(task),context=carrier(task),browser=carrier(task),
            chat=SimpleNamespace(context=carrier(chat),browser=carrier(chat)))
        trace=SimpleNamespace(event=lambda *a,**kw:None)
        with pytest.raises(CaptureDeadlineExceeded) as error:
            with cleanup_rpc_budget(env,trace,seconds=.02,phase=role+'_context_close') as count:
                assert count==2 and sibling.wrap_api_call is before[2]
                async def pending():await asyncio.Event().wait()
                await (task if role=='task' else chat).wrap_api_call(pending)
        assert error.value.document_scan_detail['scope']=='browser_cleanup'
        assert [x.wrap_api_call for x in (task,chat,sibling)]==before
        assert await sibling.wrap_api_call(lambda:asyncio.sleep(0,result='alive'))=='alive'
    asyncio.run(run())


def test_deduplicates_handles_and_works_without_page():
    async def run():
        conn=connection();original=conn.wrap_api_call
        base=SimpleNamespace(page=None,context=carrier(conn),browser=carrier(conn),chat=None)
        with cleanup_rpc_budget(SimpleNamespace(unwrapped=base),None,seconds=.1,phase='navigation') as count:
            assert count==1
            assert await conn.wrap_api_call(lambda:asyncio.sleep(0,result=3))==3
        assert conn.wrap_api_call is original
    asyncio.run(run())


def test_callback_error_restores_all_connections():
    async def run():
        task,chat=connection(),connection();originals=(task.wrap_api_call,chat.wrap_api_call)
        env=SimpleNamespace(page=carrier(task),chat=SimpleNamespace(context=carrier(chat)))
        with pytest.raises(RuntimeError,match='fixture'):
            with cleanup_rpc_budget(env,None,seconds=.1,phase='feedback'):
                raise RuntimeError('fixture')
        assert (task.wrap_api_call,chat.wrap_api_call)==originals
    asyncio.run(run())


def test_nonbrowser_callbacks_still_run_and_required_connection_fails_closed():
    env=SimpleNamespace()
    with cleanup_rpc_budget(env,None,seconds=.1,phase='task_teardown') as count:assert count==0
    with pytest.raises(ValueError,match='existing Playwright'):
        with cleanup_rpc_budget(env,None,seconds=.1,phase='navigation',required=True):raise AssertionError('must not run')


def test_invalid_existing_connection_is_not_silently_left_unbounded():
    env=SimpleNamespace(page=carrier(SimpleNamespace()))
    with pytest.raises(ValueError,match='Unsupported cleanup'):
        with cleanup_rpc_budget(env,None,seconds=.1,phase='navigation'):raise AssertionError('must not run')


def test_real_runner_uses_budget_without_human_support(tmp_path,monkeypatch):
    from tests import test_native_argument_feedback as fixture
    import intent_browser.browser_shutdown as shutdown
    import intent_browser.native_capture as capture
    original_bind=fixture.bind_grade;observed=[]
    def bind(env,trace,obs):
        result=original_bind(env,trace,obs)
        from pathlib import Path
        from intent_browser.automatic_grading import file_hash
        result['source_files'][str(Path(__file__).resolve())]=file_hash(Path(__file__).resolve())
        # No Page or browser is launched. The actual runner sees owned RPC handles.
        conn=SimpleNamespace(_callbacks={})
        async def original(cb,*a,**kw):return await cb()
        conn.wrap_api_call=original;env.page=carrier(conn)
        original_close=env.close
        def close():
            async def run():
                conn._loop=asyncio.get_running_loop()
                async def pending():await asyncio.Event().wait()
                await conn.wrap_api_call(pending)
            try:asyncio.run(run())
            finally:original_close()
        env.close=close
        conn._loop=None
        return result
    real_budget=capture.CaptureBudget
    def short_budget(*a,seconds,**kw):
        observed.append(seconds);return real_budget(*a,seconds=.02,**kw)
    monkeypatch.setattr(fixture,'bind_grade',bind)
    monkeypatch.setattr(capture,'CaptureBudget',short_budget)
    path,summary,rows,requests,responses,actions=fixture.exercise(tmp_path,[fixture.reply([('send_msg_to_user',{'text':'Done'})])])
    assert observed and len(requests)==1 and len(actions)==1
    assert summary['error'] is not None and 'Browser cleanup exceeded its time budget' in summary['error']
    assert summary['infrastructure_completed'] is False
    import json
    events=[json.loads(l) for l in (path/'events.jsonl').read_text().splitlines()]
    close=next(e for e in events if e.get('event')=='cleanup_phase_completed' and e.get('phase')=='browsergym_close')
    assert close['rpc_budget_seconds']==5 and close['rpc_budget_connection_count']==1
    assert 'CaptureDeadlineExceeded' in close['error']


def test_caller_cancellation_restores_owned_connections():
    async def run():
        task,chat=connection(),connection();originals=(task.wrap_api_call,chat.wrap_api_call)
        env=SimpleNamespace(page=carrier(task),chat=SimpleNamespace(context=carrier(chat)))
        with pytest.raises(asyncio.CancelledError):
            with cleanup_rpc_budget(env,None,seconds=.1,phase='context_close'):
                raise asyncio.CancelledError()
        assert (task.wrap_api_call,chat.wrap_api_call)==originals
    asyncio.run(run())


@pytest.mark.parametrize('fail_context',[False,True])
def test_pooled_resources_get_fresh_budgets_preserve_wrapper_and_attempt_connections(fail_context):
    from intent_browser.browser_shutdown import cleanup_phase_dispatch,phase_managed_close
    from intent_browser.shared_browsergym import SharedBrowserEnv,PoolEpisode,SharedChat,_BrowserLease
    import time
    events=[];released=[];originals=[]
    episode=PoolEpisode.__new__(PoolEpisode);episode.closed=False;episode.leases=[];episode.owner='owner'
    episode.client=SimpleNamespace(request=lambda op,payload:released.append(payload['lease_id']))
    def resource(role,kind,conn):
        def close():
            events.append(role+'_'+kind)
            async def run():
                conn._loop=asyncio.get_running_loop()
                async def rpc():
                    if fail_context and kind=='context':await asyncio.Event().wait()
                    else:await asyncio.sleep(.006)
                await conn.wrap_api_call(rpc)
            asyncio.run(run())
        return SimpleNamespace(_impl_obj=SimpleNamespace(_connection=conn),close=close)
    def lease(role):
        conn=SimpleNamespace(_callbacks={},_loop=None)
        async def original(cb,*a,**kw):return await cb()
        conn.wrap_api_call=original;originals.append((conn,original))
        result=_BrowserLease.__new__(_BrowserLease);result.episode=episode
        result.context=resource(role,'context',conn);result.browser=resource(role,'browser',conn)
        result.closed=False;result.record={'lease_id':role,'owner':'owner','release_token':'token'}
        return result
    task,chat=lease('task'),lease('chat')
    env=SharedBrowserEnv.__new__(SharedBrowserEnv);env.pool_episode=episode
    env.task=SimpleNamespace(teardown=lambda:events.append('task_teardown'))
    env.page=None;env.context=task.context;env.browser=task
    env.chat=SharedChat.__new__(SharedChat);env.chat.pool_episode=episode
    env.chat.context=chat.context;env.chat.browser=chat
    # Keep the capture/recording close wrapper in the path.
    native_close=env.close
    def wrapped_close():
        events.append('wrapper_enter')
        try:return native_close()
        finally:events.append('wrapper_exit')
    env.close=wrapped_close
    failures=[]
    def phase(name,callback,seconds=2):
        if phase_managed_close(callback):return callback()
        try:
            with cleanup_rpc_budget(env,None,seconds=.02,phase=name):return callback()
        except Exception as error:
            failures.append((name,type(error).__name__));raise
    started=time.monotonic()
    with cleanup_phase_dispatch(env,phase):
        if fail_context:
            with pytest.raises(Exception,match='Shared environment close failed'):env.close()
        else:env.close()
    assert events[0]=='wrapper_enter' and events[-1]=='wrapper_exit'
    assert 'task_browser' in events and 'chat_browser' in events
    assert set(released)=={'task','chat'}
    assert time.monotonic()-started>.02  # Total exceeds a composite deadline.
    assert bool(failures)==fail_context
    assert all(conn.wrap_api_call is original for conn,original in originals)
    assert '_cleanup_phase' not in vars(env) and '_cleanup_phase' not in vars(episode)
