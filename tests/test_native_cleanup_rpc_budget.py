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
