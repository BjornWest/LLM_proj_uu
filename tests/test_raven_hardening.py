"""Demo provider stalls retry once with identical payload and visible progress."""
import json
import httpx
import pytest
from apps.raven.episode import DemoBackend


@pytest.mark.parametrize('recover',[True,False])
def test_provider_timeout_retries_same_request_once(recover):
    requests=[]
    progress=[]
    def transport(request):
        requests.append(json.loads(request.content))
        if len(requests)==1 or not recover:
            raise httpx.ReadTimeout('provider stalled',request=request)
        return httpx.Response(200,json={'choices':[{'message':{'content':'done'}}]})
    backend=DemoBackend('https://fixture.invalid/v1','mock',on_retry=lambda:progress.append('retry'))
    backend.client.close()
    backend.client=httpx.Client(transport=httpx.MockTransport(transport))
    backend.sampling={'temperature':0.6}
    try:
        if recover:
            assert backend.complete([{'role':'user','content':'question'}]).text=='done'
        else:
            with pytest.raises(httpx.ReadTimeout):
                backend.complete([{'role':'user','content':'question'}])
        assert len(requests)==2 and requests[0]==requests[1]
        assert progress==['retry']
    finally: backend.close()
