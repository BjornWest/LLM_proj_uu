"""Private browser state for explicitly adopted generated DOM-backed pages.

Not a Chromium-process snapshot: frames, shadow roots, service workers and JS-heap
applications require a future explicit adapter. Restoration never clicks or submits.
"""
from copy import deepcopy
import hashlib
import json
import re
import time
from urllib.parse import urlsplit
import httpx

VERSION = 'generated-browser-checkpoint-v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False, separators=(',', ':')).encode()).hexdigest()


CAPTURE = r'''async () => {
 if(document.readyState !== 'complete') throw Error('Document is not complete');
 if(document.querySelector('iframe,frame') || [...document.querySelectorAll('*')].some(e=>e.shadowRoot))
   throw Error('Frames and shadow DOM require explicit checkpoint support');
 if((await indexedDB.databases()).length)throw Error('IndexedDB requires explicit checkpoint support');
 if([...document.querySelectorAll('input[type=file]')].some(e=>e.files.length))throw Error('Selected files require explicit checkpoint support');
 if(document.activeElement?.isContentEditable)throw Error('Contenteditable selection requires explicit checkpoint support');
 const elements=[...document.querySelectorAll('*')];
 const positions=new Map(elements.map((e,i)=>[e,i]));
 const state=elements.map(e=>({tag:e.tagName,
   attrs:[...e.attributes].filter(a=>!a.name.startsWith('browsergym') && a.name!=='bid' &&
     !['aria-roledescription','aria-description'].includes(a.name)).map(a=>[a.name,a.value]).sort(),
   aria:['aria-roledescription','aria-description'].map(k=>[k,(e.getAttribute(k)||'').replace(/browsergym_id_\S+\s*/g,'')]),
   text:[...e.childNodes].filter(n=>n.nodeType===3).map(n=>n.nodeValue),
   parent:e.parentElement?positions.get(e.parentElement):null,
   element_scroll:[e.scrollLeft,e.scrollTop],
   value:'value' in e && ['INPUT','SELECT','TEXTAREA'].includes(e.tagName)?e.value:null,
   checked:e.tagName==='INPUT'?e.checked:null,
   selected:e.tagName==='SELECT'?[...e.options].map(o=>o.selected):null,
   modal:e.tagName==='DIALOG'?e.matches(':modal'):null, bid:e.getAttribute('bid')}));
 const focus=elements.indexOf(document.activeElement);
 const selection=focus>=0 && ['INPUT','TEXTAREA'].includes(elements[focus].tagName)?
   [elements[focus].selectionStart,elements[focus].selectionEnd,elements[focus].selectionDirection]:null;
 return {url:location.href, html:document.documentElement.outerHTML, nodes:state, scroll:[scrollX,scrollY],focus,selection,
   session_storage:Object.fromEntries(Object.entries(sessionStorage)),
   counter:window.browsergym_elem_counter??null,
   consent:window.__connectedConsentCheckpoint?.capture()??null,
   converter:window.__connectedConverterCheckpoint?.capture()??null};
}'''

# Attribute/property restoration is NOT generic JS-heap restoration. Callers
# explicitly adopt this contract and supply extra UI state if their scripts need it.
RESTORE = r'''async saved => {
 if(saved.consent!==null){if(!window.__connectedConsentCheckpoint)throw Error('Missing consent UI adapter');window.__connectedConsentCheckpoint.restore(saved.consent);}
 if(saved.converter!==null && saved.converter!==undefined){if(!window.__connectedConverterCheckpoint)throw Error('Missing converter UI adapter');window.__connectedConverterCheckpoint.restore(saved.converter);}
 const elements=[...document.querySelectorAll('*')];
 const positions=new Map(elements.map((e,i)=>[e,i]));
 if(elements.length!==saved.nodes.length) throw Error('Checkpoint DOM node count changed');
 for(let i=0;i<elements.length;i++) {
   const e=elements[i], n=saved.nodes[i];
   if(e.tagName!==n.tag || (e.parentElement?positions.get(e.parentElement):null)!==n.parent ||
      JSON.stringify([...e.childNodes].filter(x=>x.nodeType===3).map(x=>x.nodeValue))!==JSON.stringify(n.text))
      throw Error('Checkpoint DOM structure/text changed at '+i);
 }
 for(let i=0;i<elements.length;i++) {
   const e=elements[i],n=saved.nodes[i];
   // Require authored identity before applying saved UI attributes.
   for(const key of ['id','name','type','href','action','src','onclick','onchange']) {
     const old=n.attrs.find(a=>a[0]===key)?.[1]??null;
     if(e.getAttribute(key)!==old) throw Error('Checkpoint element identity changed: '+i+' '+key);
   }
   if(e.tagName==='DIALOG' && e.open)e.close();
   const authored=new Map(n.attrs);
   for(const a of [...e.attributes]) if(!a.name.startsWith('browsergym') && a.name!=='bid' &&
     !['aria-roledescription','aria-description'].includes(a.name) && !authored.has(a.name))e.removeAttribute(a.name);
   // Keep unchanged LINK/SCRIPT attributes intact: removing/readding href/src
   // can refetch resources and leave layout temporarily unstyled.
   for(const [k,v] of n.attrs)if(!(e.tagName==='DIALOG' && k==='open') && e.getAttribute(k)!==v)e.setAttribute(k,v);
   if(e.tagName==='DIALOG' && n.attrs.some(a=>a[0]==='open')){if(n.modal)e.showModal();else e.show();}
   for(const [k,v] of n.aria){if(v)e.setAttribute(k,v);else e.removeAttribute(k);}
   if(n.bid!==null)e.setAttribute('bid',n.bid);else e.removeAttribute('bid');
 }
 // OPTION selected attributes can reset SELECT.value: apply properties last.
 for(let i=0;i<elements.length;i++){const e=elements[i],n=saved.nodes[i];
   if(n.value!==null && e.value!==n.value)e.value=n.value;
   if(n.checked!==null)e.checked=n.checked;
   if(n.selected!==null)[...e.options].forEach((o,j)=>o.selected=n.selected[j]);
 }
 if(saved.consent!==null){
   if(!window.__connectedConsentCheckpoint)throw Error('Missing consent checkpoint adapter');
   window.__connectedConsentCheckpoint.restore(saved.consent);
 }
 sessionStorage.clear();for(const [k,v] of Object.entries(saved.session_storage))sessionStorage.setItem(k,v);
 if(saved.counter!==null)window.browsergym_elem_counter=saved.counter;
 if(saved.focus>=0)elements[saved.focus].focus({preventScroll:true});
 if(saved.selection && saved.selection[0]!==null)elements[saved.focus].setSelectionRange(...saved.selection);
 // Replacing hidden/open attributes can schedule Chromium scroll anchoring.
 // Let that layout settle, then restore native scroll state without clicking.
 await new Promise(resolve=>requestAnimationFrame(resolve));
 scrollTo(...saved.scroll);
 for(let i=elements.length-1;i>=0;i--){const e=elements[i],n=saved.nodes[i];if(e.scrollLeft!==n.element_scroll[0])e.scrollLeft=n.element_scroll[0];if(e.scrollTop!==n.element_scroll[1])e.scrollTop=n.element_scroll[1];}
 await new Promise(resolve=>requestAnimationFrame(resolve));
}'''


def difference_path(expected,actual,path='pages'):
    if type(expected) is not type(actual):return path+' (type)'
    if isinstance(expected,dict):
        if set(expected)!=set(actual):return path+' (keys)'
        for key in expected:
            if expected[key]!=actual[key]:return difference_path(expected[key],actual[key],path+'.'+key)
    if isinstance(expected,list):
        if len(expected)!=len(actual):return path+' (length)'
        for i,(left,right) in enumerate(zip(expected,actual)):
            if left!=right:return difference_path(left,right,path+'['+str(i)+']')
    return path


def semantic_browser(value):
    """Keep every authored field/control state; omit only transport counter/BIDs."""
    result=deepcopy(value)
    result.pop('counter',None)
    result.pop('html',None)
    result.pop('history',None)
    for n in result['nodes']:n.pop('bid',None)
    return result


def capture_browser(env):
    base=env.unwrapped;context=base.page.context
    if context.service_workers:raise ValueError('Service workers are unsupported by checkpoint v1')
    pages=list(context.pages)
    # BrowserGym chat is out-of-world and is not part of agent page tabs.
    chat=getattr(getattr(base,'chat',None),'page',None)
    pages=[p for p in pages if p is not chat]
    if any(urlsplit(p.url).scheme not in ('http','https') for p in pages):
        raise ValueError('Checkpoint requires adopted HTTP(S) world tabs')
    from .checkpoint_history import capture as history_capture
    captured=[{**p.evaluate(CAPTURE),'history':history_capture(p),'viewport':p.viewport_size} for p in pages]
    if base.page not in pages:raise ValueError('Active agent tab absent')
    result={'schema_version':VERSION,'pages':captured,'active':pages.index(base.page),
            'storage':context.storage_state(),
            'environment':{'last_action':base.last_action,'last_action_error':base.last_action_error,
                           'elapsed_seconds':time.time()-base.start_time}}
    result['semantic_sha256']=digest([semantic_browser(p) for p in captured])
    return result


def restore_browser(env,state):
    if state.get('schema_version')!=VERSION:raise ValueError('Unsupported browser checkpoint')
    base=env.unwrapped;context=base.page.context
    chat=getattr(getattr(base,'chat',None),'page',None)
    pages=[p for p in context.pages if p is not chat]
    if len(pages)!=1:raise ValueError('Restore requires a fresh one-tab environment')
    # Local/session storage must be installed BEFORE scripts run.
    storage=state['storage'];context.clear_cookies();context.add_cookies(storage['cookies'])
    origin_storage={o['origin']:o['localStorage'] for o in storage['origins']}
    script='({local,session}) => {\n      if(local[location.origin]){localStorage.clear();for(const item of local[location.origin])localStorage.setItem(item.name,item.value);}\n      if(session[location.href]){sessionStorage.clear();for(const [k,v] of Object.entries(session[location.href]))sessionStorage.setItem(k,v);}\n    }'
    restored=[]
    for i,p in enumerate(state['pages']):
        page=pages[0] if i==0 else context.new_page()
        if p['viewport'] is not None:page.set_viewport_size(p['viewport'])
        # Chromium's removable, target-local preload avoids replaying stale
        # localStorage on later ordinary navigations/reloads.
        cdp=context.new_cdp_session(page)
        cdp.send('Page.enable')
        identifier=cdp.send('Page.addScriptToEvaluateOnNewDocument', {'source':
            '('+script+')('+json.dumps({'local':origin_storage,'session':{p['url']:p['session_storage']}})+')'})['identifier']
        try:
            from .checkpoint_history import hydrate
            hydrate(page,p['history'],p['html'])
        finally:
            cdp.send('Page.removeScriptToEvaluateOnNewDocument', {'identifier':identifier})
            cdp.detach()
        page.evaluate(RESTORE,p);restored.append(page)
    base.page=restored[state['active']]
    got=[{**p.evaluate(CAPTURE),'viewport':p.viewport_size} for p in restored]
    if digest([semantic_browser(p) for p in got])!=state['semantic_sha256']:
        path=difference_path([semantic_browser(p) for p in state['pages']],[semantic_browser(p) for p in got])
        if 'element_scroll' in path:
            index=int(path.split('.nodes[')[1].split(']')[0])
            detail=restored[0].evaluate('(index)=>{const e=document.querySelectorAll("*")[index];return {top:e.scrollTop,height:e.scrollHeight,client:e.clientHeight}}',index)
            path+=' geometry='+json.dumps(detail)
        raise ValueError('Restored browser state differs from checkpoint: '+path)
    if context.storage_state()!=storage:raise ValueError('Restored browser storage differs')
    inherited=state['environment']
    base.last_action=inherited['last_action'];base.last_action_error=inherited['last_action_error']
    base.start_time=time.time()-inherited['elapsed_seconds']
    return got


class LogicalOrigins:
    """Context-local bridge: private physical ports, unchanged policy/browser URLs.

    Only exact declared origins are forwarded, including redirects. No global
    listener or shared browser proxy is created. Unknown destinations fail closed.
    """
    def __init__(self,logical,physical):
        if set(logical)!=set(physical):raise ValueError('World site topology changed')
        self.mapping={}
        for key in logical:
            source,target=logical[key],physical[key]
            for value in (source,target):
                parsed=urlsplit(value)
                if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
                    raise ValueError('Invalid declared origin')
            if source in self.mapping and self.mapping[source]!=target:raise ValueError('Inconsistent origin alias')
            self.mapping[source]=target
        self.client=httpx.Client(follow_redirects=False,trust_env=False,timeout=10)
    def attach(self,context):
        context.route('**/*',self.route)
    def replace(self,text):
        inverse={physical:logical for logical,physical in self.mapping.items()}
        pattern='(?:'+'|'.join(re.escape(v) for v in sorted(inverse,key=len,reverse=True))+')(?=$|[/#?\\s\"\'<>])'
        return re.sub(pattern,lambda match:inverse[match.group()],text)
    def route(self,route,request):
        url=urlsplit(request.url);origin=f'{url.scheme}://{url.netloc}'
        if origin not in self.mapping:
            route.abort('blockedbyclient');return
        physical=self.mapping[origin]
        headers={k:v for k,v in request.all_headers().items() if k.lower() not in
                 ('host','content-length','accept-encoding','connection')}
        for key in ('origin','referer'):
            if key in headers:
                parsed=urlsplit(headers[key]);declared=f'{parsed.scheme}://{parsed.netloc}'
                if declared in self.mapping:headers[key]=self.mapping[declared]+headers[key][len(declared):]
        response=self.client.request(request.method,physical+request.url[len(origin):],
                                     headers=headers,content=request.post_data_buffer)
        result_headers={k:v for k,v in response.headers.items() if k.lower() not in
                        ('content-length','content-encoding','transfer-encoding','connection')}
        if 'location' in result_headers:
            from urllib.parse import urljoin
            raw=result_headers['location']
            absolute=urlsplit(raw)
            if absolute.scheme and (absolute.scheme not in ('http','https') or not absolute.hostname or absolute.username or absolute.password):
                route.fulfill(status=502,body='Malformed absolute redirect rejected');return
            if '\\' in raw or any(ord(c)<33 for c in raw) or raw.startswith('//') or (':' in raw.split('/')[0] and not raw.startswith(('http://','https://'))):
                route.fulfill(status=502,body='Ambiguous redirect rejected');return
            location=urljoin(physical+request.url[len(origin):],raw)
            parsed=urlsplit(location)
            if f'{parsed.scheme}://{parsed.netloc}' not in self.mapping.values():
                route.fulfill(status=502,body='Off-world redirect rejected');return
            result_headers['location']=self.replace(location)
        cookies=response.headers.get_list('set-cookie')
        if cookies:result_headers['set-cookie']='\n'.join(cookies)
        body=response.content
        if any(t in response.headers.get('content-type','') for t in ('text/','json','javascript')):
            body=self.replace(body.decode('utf-8')).encode('utf-8')
        route.fulfill(status=response.status_code,headers=result_headers,body=body)
    def close(self):self.client.close()
