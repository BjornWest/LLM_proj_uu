from urllib.request import Request,urlopen
from urllib.error import HTTPError
import pytest
from .http import Site


def post(origin,body=b'code=A',path='/action',headers=None):
    headers={'Content-Type':'application/x-www-form-urlencoded',**(headers or {})}
    return urlopen(Request(origin+path,data=body,headers=headers))


def test_actions_opt_in_and_read_requests_never_mutate():
    calls=[]
    with Site(lambda *a:(200,'<h1>Page</h1>')) as site:
        with pytest.raises(HTTPError) as e:post(site.origin)
        assert e.value.code==405
    def act(path,fields):calls.append((path,fields));return 200,'<h1>Applied</h1>'
    with Site(lambda *a:(200,'<h1>Page</h1>'),action=act) as site:
        assert urlopen(site.origin+'/action?code=A').status==200 and not calls
        assert post(site.origin).status==200
        assert calls==[('/action',{'code':'A'})]


@pytest.mark.parametrize('body,path,headers,status',[
    (b'code=A&code=B','/action',{},400),
    (b'code=A','/action?code=B',{},400),
    (b'code=A','/action',{'Origin':'https://foreign.test'},403),
    (b'code=A','/action',{'Sec-Fetch-Site':'cross-site'},403),
    (b'{}','/action',{'Content-Type':'application/json'},400),
    (b'x='+b'a'*8192,'/action',{},400),
])
def test_invalid_forms_never_reach_action(body,path,headers,status):
    calls=[]
    def act(*args):calls.append(args);return 200,'ok'
    with Site(lambda *a:(200,'page'),action=act) as site:
        with pytest.raises(HTTPError) as e:post(site.origin,body,path,headers)
        assert e.value.code==status and not calls
