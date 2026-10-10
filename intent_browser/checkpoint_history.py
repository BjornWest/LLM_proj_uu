"""Chromium navigation-history hydration, with NO inherited POST replay.

Generated pages opt into disabling BFCache via an unload listener, so Back loads
an actual document instead of retaining an uncheckpointable old JS heap. Native
history request methods/bodies are recorded privately and bootstrapped through
intercepted responses; future ordinary reloads/actions go to the isolated world.
"""
from base64 import b64encode,b64decode
from html import escape
from urllib.parse import parse_qsl

INIT = """(() => {
 window.addEventListener('unload',()=>{});
 // DOM-backed version cannot restore arbitrary History API state/JS heaps.
 for(const name of ['pushState','replaceState']) {
   const original=history[name].bind(history);
   history[name]=(...args)=>{const result=original(...args);window.__rollout_unsupported_history=true;return result;};
 }
 window.addEventListener('hashchange',()=>{window.__rollout_unsupported_history=true;});
})();"""


def track(context):
    context.add_init_script(INIT)
    def attach(page):
        page._rollout_history={};page._rollout_navigation=None
        cdp=context.new_cdp_session(page)
        def request(req):
            if req.is_navigation_request() and req.frame==page.main_frame:
                page._rollout_navigation={'url':req.url,'method':req.method,
                    'body':b64encode(req.post_data_buffer or b'').decode(),
                    'content_type':req.headers.get('content-type','')}
        def navigated(frame):
            if frame!=page.main_frame or page._rollout_navigation is None:return
            history=cdp.send('Page.getNavigationHistory')
            entry=history['entries'][history['currentIndex']]
            if entry['url']==page._rollout_navigation['url']:
                page._rollout_history[entry['id']]=dict(page._rollout_navigation)
        page.on('request',request);page.on('framenavigated',navigated)
    context.on('page',attach)
    for page in context.pages:attach(page)


def capture(page):
    if page.evaluate('Boolean(window.__rollout_unsupported_history)'):
        raise ValueError('History API/same-document navigation requires explicit checkpoint support')
    cdp=page.context.new_cdp_session(page)
    try:history=cdp.send('Page.getNavigationHistory')
    finally:cdp.detach()
    entries=[]
    for entry in history['entries']:
        if entry['url']=='about:blank':
            request={'url':entry['url'],'method':'GET','body':'','content_type':''}
        else:
            request=getattr(page,'_rollout_history',{}).get(entry['id'])
            if request is None:raise ValueError('Navigation entry was not tracked; checkpoint history is incomplete')
        if request['method'] not in ('GET','POST'):raise ValueError('Unsupported history request method')
        if request['method']=='POST' and not request['content_type'].startswith('application/x-www-form-urlencoded'):
            raise ValueError('Checkpoint history supports ordinary form POSTs only')
        entries.append({**request,'title':entry['title']})
    return {'current':history['currentIndex'],'entries':entries}


def hydrate(page,state,html):
    entries=state['entries'];current=state['current']
    if type(current) is not int or not 0<=current<len(entries):raise ValueError('Invalid history position')
    # Backward hydration across a POST may present Chromium's resubmit prompt.
    # Never guess/re-submit a mutation or dismiss that boundary silently.
    if current!=len(entries)-1 and any(e['method']=='POST' for e in entries):
        raise ValueError('Forward history containing POST requires an explicit future adapter')
    target=None
    def respond(route,request):
        if request.is_navigation_request() and request.frame==page.main_frame and target is not None:
            if request.url!=target['url'] or request.method!=target['method']:
                route.abort('blockedbyclient');raise ValueError('History hydration request changed')
            content=html if target['actual'] else '<!doctype html><title>'+escape(target['title'])+'</title>'
            route.fulfill(status=200,headers={'content-type':'text/html; charset=utf-8','cache-control':'no-store'},body=content)
        else:route.fallback()
    page.route('**/*',respond)
    try:
        for i,entry in enumerate(entries):
            if entry['url']=='about:blank':
                if i!=0:raise ValueError('Unexpected blank history entry')
                continue
            target={**entry,'actual':i==current}
            if entry['method']=='GET':page.goto(entry['url'],wait_until='load')
            else:
                fields=parse_qsl(b64decode(entry['body']).decode('utf-8'),keep_blank_values=True,strict_parsing=True)
                with page.expect_navigation(wait_until='load'):
                    page.evaluate('''({url,fields}) => {
                      const form=document.createElement('form');form.method='POST';form.action=url;
                      for(const [name,value] of fields){const input=document.createElement('input');input.type='hidden';input.name=name;input.value=value;form.append(input);}
                      document.body.append(form);HTMLFormElement.prototype.submit.call(form);
                    }''',{'url':entry['url'],'fields':fields})
        if current!=len(entries)-1:
            target={**entries[current],'actual':True}
            # With the explicit no-BFCache recipe this reloads the recorded URL.
            with page.expect_navigation(wait_until='load'):
                page.evaluate('(distance)=>history.go(distance)',current-(len(entries)-1))
        got=capture(page)
        if got!=state:raise ValueError('Restored navigation history differs')
    finally:page.unroute('**/*',respond)
