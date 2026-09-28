import asyncio
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from playwright.sync_api import Error as PlaywrightError
from intent_browser.native_capture import CaptureBudget, owner_lookup_invalidation
from intent_browser.batching import DocumentScanInvalidated

ADOPTION='Frame.frame_element: Unable to adopt element handle from a different document'

@pytest.mark.parametrize('text', [ADOPTION,'Frame has been detached.','Frame was detached'])
def test_narrow_owner_errors_are_observation_invalidations(text):
    result=owner_lookup_invalidation(PlaywrightError(text),2)
    assert isinstance(result,DocumentScanInvalidated)
    assert result.detail['phase']=='frame_owner_lookup' and result.detail['child_index']==2
    assert result.detail['native_error']==text

@pytest.mark.parametrize('error', [RuntimeError(ADOPTION),PlaywrightError('Target page, context or browser has been closed'),
                                   PlaywrightError('Protocol error: unrelated failure'),ValueError('Frame has been detached')])
def test_transport_and_other_failures_not_classified_as_races(error):
    assert owner_lookup_invalidation(error,0) is None


def test_gather_never_masks_transport_error_with_another_child_race():
    records=[]
    page=SimpleNamespace(_impl_obj=SimpleNamespace(_connection=SimpleNamespace(_callbacks={})),_sync=asyncio.run)
    trace=SimpleNamespace(event=lambda *a,**kw:records.append(kw))
    budget=CaptureBudget(page,trace,enforce=False);budget.quarantined={}
    transport=PlaywrightError('Connection closed during owner lookup')
    class Frame:
        def __init__(self,value):self.value=value
        async def frame_element(self):
            await asyncio.sleep(0)
            if self.value==0:raise PlaywrightError(ADOPTION)
            raise transport
    children=[type('Child',(),{'_impl_obj':i})() for i in range(2)]
    with patch('intent_browser.native_capture.AsyncFrame',Frame),pytest.raises(PlaywrightError) as caught:
        budget.owner_attributes(children)
    assert caught.value is transport
    assert len([r for r in records if r.get('phase')=='frame_owner_lookup' and 'seconds' in r])==2
