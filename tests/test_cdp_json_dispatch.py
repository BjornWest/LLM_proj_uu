"""Real pinned Connection dispatch with an in-memory transport, no browser/API."""
import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from playwright._impl._connection import Connection
from intent_browser.cdp_json import _raw_reply_scope, _STATE_ATTRIBUTE


def setup():
    sent = []
    transport = SimpleNamespace(send=sent.append)
    conn = Connection(None, None, transport, asyncio.get_running_loop())
    conn._api_zone.set({'apiName':'test', 'frames':[]})
    obj = SimpleNamespace(_connection=conn, _guid='cdp@1', _was_collected=False)
    known = SimpleNamespace(_channel=object())
    conn._objects['known'] = known
    return conn, obj, known, sent


def request(conn, obj, method='Accessibility.getFullAXTree'):
    cb = conn._send_message_to_server(obj, 'send', {'method':method})
    return conn._last_id, cb


def test_only_tagged_success_skips_conversion_events_and_other_replies_still_convert():
    async def run():
        c, obj, known, sent = setup(); events = []
        c._objects['events'] = SimpleNamespace(_channel=SimpleNamespace(emit=lambda *a:events.append(a)))
        with _raw_reply_scope(obj, 'Accessibility.getFullAXTree'):
            selected, a = request(c, obj)
            other, b = request(c, obj, 'Runtime.evaluate')
            literal = {'result':{'nested':{'guid':'known'}, 'nodes':[]}}
            with patch.object(c, '_replace_guids_with_channels', wraps=c._replace_guids_with_channels) as convert:
                c.dispatch({'id':selected,'result':literal})
                assert convert.call_count == 0
                assert a.future.result() is literal
                c.dispatch({'id':other,'result':{'result':{'guid':'known'}}})
                c.dispatch({'guid':'events','method':'sample','params':{'ref':{'guid':'known'}}})
            assert b.future.result()['result'] is known._channel
            assert events == [('sample', {'ref':known._channel})]
        assert not hasattr(c, _STATE_ATTRIBUTE)
        assert 'dispatch' not in vars(c) and '_send_message_to_server' not in vars(c)
        assert not c._callbacks and len(sent)==2
    asyncio.run(run())


@pytest.mark.parametrize('mode',['error','cancelled','unexpected_shape'])
def test_non_success_keeps_native_dispatch(mode):
    async def run():
        c,obj,known,sent = setup()
        with _raw_reply_scope(obj, 'Accessibility.getFullAXTree'):
            key,cb = request(c,obj)
            if mode=='error':
                c.dispatch({'id':key,'error':{'error':{'name':'Error','message':'Synthetic CDP failure','stack':''}}})
                with pytest.raises(Exception,match='Synthetic CDP failure'):await cb.future
            elif mode=='cancelled':
                cb.future.cancel();c.dispatch({'id':key,'result':{'result':{'nodes':[]}}})
                assert cb.future.cancelled()
            else:
                c.dispatch({'id':key,'result':{'different':{'guid':'known'}}})
                assert cb.future.result()['different'] is known._channel
        assert len(sent)==1 and not c._callbacks and not hasattr(c,_STATE_ATTRIBUTE)
    asyncio.run(run())


def test_cancel_scope_restores_dispatch_before_late_reply():
    async def run():
        c,obj,known,sent = setup(); pending = []
        async def task():
            with _raw_reply_scope(obj,'Accessibility.getFullAXTree'):
                pending.append(request(c,obj))
                await pending[0][1].future
        task = asyncio.create_task(task());await asyncio.sleep(0);task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert not hasattr(c,_STATE_ATTRIBUTE)
        key,cb = pending[0]
        c.dispatch({'id':key,'result':{'result':{'nodes':[]}}})
        assert cb.future.cancelled() and not c._callbacks and len(sent)==1
    asyncio.run(run())


def test_overlapping_calls_out_of_order_keep_per_request_identity():
    async def run():
        c,obj,known,sent=setup(); requests=[]
        async def operation(method):
            with _raw_reply_scope(obj,method):
                key,cb=request(c,obj,method);requests.append((key,cb))
                return await cb.future
        tasks=[asyncio.create_task(operation(m)) for m in ('Accessibility.getFullAXTree','DOMSnapshot.captureSnapshot')]
        await asyncio.sleep(0)
        a,b=requests
        c.dispatch({'id':b[0],'result':{'result':{'label':'second','guid':'known'}}})
        await asyncio.sleep(0)
        assert hasattr(c,_STATE_ATTRIBUTE)
        c.dispatch({'id':a[0],'result':{'result':{'label':'first','guid':'known'}}})
        results=await asyncio.gather(*tasks)
        assert [r['result']['label'] for r in results]==['first','second']
        assert all(r['result']['guid']=='known' for r in results)
        assert len(sent)==2 and not c._callbacks and not hasattr(c,_STATE_ATTRIBUTE)
    asyncio.run(run())


def test_instrumented_connection_is_left_alone():
    async def run():
        c,obj,known,sent=setup();original=c.dispatch
        with patch.object(c,'dispatch',wraps=original) as instrumented:
            with _raw_reply_scope(obj,'Accessibility.getFullAXTree'):
                assert not hasattr(c,_STATE_ATTRIBUTE)
                key,cb=request(c,obj)
                c.dispatch({'id':key,'result':{'result':{'guid':'known'}}})
                assert cb.future.result()['result'] is known._channel
            assert c.dispatch is instrumented and instrumented.call_count==1
    asyncio.run(run())


def test_connection_close_completes_pending_future_and_cleans_scope():
    async def run():
        c,obj,known,sent=setup()
        with _raw_reply_scope(obj,'Accessibility.getFullAXTree'):
            _,cb=request(c,obj);c.cleanup()
            with pytest.raises(Exception,match='closed'):await cb.future
        assert not hasattr(c,_STATE_ATTRIBUTE) and len(sent)==1
    asyncio.run(run())


def test_nested_tracing_message_does_not_steal_selected_request_id():
    async def run():
        c,obj,known,sent=setup()
        local=SimpleNamespace(_guid='localUtils',_was_collected=False)
        c._local_utils=SimpleNamespace(add_stack_to_tracing_no_reply=lambda *a:
            c._send_message_to_server(local,'trace',{},True))
        c._tracing_count=1
        c._api_zone.set({'apiName':'test','frames':[{'file':'test.py','line':1,'column':1}]})
        with _raw_reply_scope(obj,'Accessibility.getFullAXTree'):
            cb=c._send_message_to_server(obj,'send',{'method':'Accessibility.getFullAXTree'})
            assert set(c._callbacks)=={1,2}
            payload={'result':{'guid':'known'}}
            c.dispatch({'id':1,'result':payload});c.dispatch({'id':2,'result':{}})
            assert cb.future.result() is payload
        assert len(sent)==2 and not c._callbacks
    asyncio.run(run())


def test_independent_connections_with_same_request_id_do_not_share_replies():
    async def run():
        first,a,_,sent_a=setup();second,b,_,sent_b=setup()
        with _raw_reply_scope(a,'Accessibility.getFullAXTree'), _raw_reply_scope(b,'DOMSnapshot.captureSnapshot'):
            # Each tag belongs to its actual task/scope; re-enter A while B lives.
            with _raw_reply_scope(a,'Accessibility.getFullAXTree'):
                ka,ca=request(first,a)
            kb,cb=request(second,b,'DOMSnapshot.captureSnapshot')
            assert ka==kb==1
            pa={'result':{'nodes':[{'name':'A'}]}};pb={'result':{'documents':[{'name':'B'}]}}
            second.dispatch({'id':kb,'result':pb});first.dispatch({'id':ka,'result':pa})
            assert ca.future.result() is pa and cb.future.result() is pb
        assert not hasattr(first,_STATE_ATTRIBUTE) and not hasattr(second,_STATE_ATTRIBUTE)
        assert len(sent_a)==len(sent_b)==1
    asyncio.run(run())
