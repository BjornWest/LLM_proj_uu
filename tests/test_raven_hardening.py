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
    assert backend.client.timeout.read==120
    backend._request_client=lambda:httpx.Client(transport=httpx.MockTransport(transport))
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


def test_keepalive_whitespace_cannot_extend_request_deadline():
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_POST(self):
            self.rfile.read(int(self.headers['Content-Length']))
            calls.append(1)
            self.send_response(200)
            self.send_header('Content-Type','application/json')
            self.end_headers()
            try:
                for _ in range(20):
                    self.wfile.write(b' ');self.wfile.flush();time.sleep(0.03)
                self.wfile.write(b'{"choices":[{"message":{"content":"too late"}}]}')
            except (BrokenPipeError,ConnectionResetError): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    progress=[]
    backend=DemoBackend('http://127.0.0.1:'+str(server.server_port),'mock',
                        on_retry=lambda:progress.append('retry'),request_timeout=0.12)
    started=time.monotonic()
    try:
        with pytest.raises(httpx.TimeoutException): backend.complete([{'role':'user','content':'question'}])
        assert time.monotonic()-started < 0.5
        assert len(calls)==2 and progress==['retry']
    finally:
        backend.close();server.shutdown();server.server_close()


def test_price_excerpt_matches_localized_currency_and_spacing():
    from apps.raven.episode import evidence_excerpt
    captured='\n'.join(['RAM Minne','8 GB']+['Other product text']*200+['Pris','2 149 SEK','Inkl. 25% moms'])
    excerpt=evidence_excerpt(captured,'Raspberry Pi med 8 GB kostar **2 149 kr**.')
    assert '2 149 SEK' in excerpt and 'Pris' in excerpt and 'Inkl. 25% moms' in excerpt
    assert excerpt.index('2 149 SEK') < excerpt.index('8 GB')
