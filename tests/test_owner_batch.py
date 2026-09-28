import asyncio
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from intent_browser.native_capture import CaptureBudget, CaptureDeadlineExceeded, _SKIPPED


def fixture(count):
    active=SimpleNamespace(now=0,peak=0,calls=[])
    class Element:
        def __init__(self,frame):self.frame=frame
        async def content_frame(self):
            return self.frame if self.frame.mode!='mismatch' else None
        async def evaluate(self,expression):
            active.now-=1
            return {'sandbox':None,'bid':str(self.frame.index)}
    class Frame:
        def __init__(self,index):self.index=index;self._impl_obj=self;self.mode='normal'
        async def frame_element(self):
            active.calls.append(self.index);active.now+=1;active.peak=max(active.peak,active.now)
            if self.mode=='blocked':await asyncio.Future()
            if self.mode=='error':raise ValueError('owner read failed')
            await asyncio.sleep(.001*(3-self.index%3))
            return Element(self)
    children=[Frame(i) for i in range(count)]
    page=SimpleNamespace(_impl_obj=SimpleNamespace(_connection=SimpleNamespace(_callbacks={})),_sync=asyncio.run)
    trace=SimpleNamespace(event=lambda *a,**kw:None)
    budget=CaptureBudget(page,trace);budget.quarantined={}
    return budget,children,active


def test_bounded_concurrent_reads_preserve_child_order():
    budget,children,active=fixture(20)
    with patch('intent_browser.native_capture.AsyncFrame',lambda impl:impl):
        results=budget.owner_attributes(children)
    assert [r['bid'] for r in results]==list(map(str,range(20)))
    assert active.peak==8 and active.now==0


def test_mismatch_and_existing_quarantine_not_markable():
    budget,children,active=fixture(3);children[0].mode='mismatch'
    budget.quarantined[children[1]]={'reason':'earlier timeout'}
    with patch('intent_browser.native_capture.AsyncFrame',lambda impl:impl):
        results=budget.owner_attributes(children)
    assert results[0] is None and results[1] is _SKIPPED and results[2]['bid']=='2'
    assert 1 not in active.calls


def test_one_blocked_owner_quarantines_without_losing_healthy_sibling():
    budget,children,active=fixture(2);children[0].mode='blocked'
    with patch('intent_browser.native_capture.AsyncFrame',lambda impl:impl), \
            patch('intent_browser.native_capture.CHILD_RPC_SECONDS',.02):
        results=budget.owner_attributes(children)
    assert results[0] is _SKIPPED and results[1]['bid']=='1'
    assert budget.quarantined[children[0]]['reason']=='owner_lookup_deadline'


def test_owner_errors_are_not_silenced():
    budget,children,_=fixture(2);children[0].mode='error'
    with patch('intent_browser.native_capture.AsyncFrame',lambda impl:impl),pytest.raises(ValueError,match='owner read failed'):
        budget.owner_attributes(children)


def test_aggregate_deadline_cancels_pending_owner_reads():
    budget,children,_=fixture(20)
    for child in children:child.mode='blocked'
    budget.deadline=budget.started+.02
    with patch('intent_browser.native_capture.AsyncFrame',lambda impl:impl),pytest.raises(CaptureDeadlineExceeded):
        budget.owner_attributes(children)
    assert not budget.quarantined  # Aggregate exhaustion must not become partial success.
