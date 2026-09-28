"""Loopback human-control UI. Request threads only signal the pure controller."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import hmac,json,secrets,threading

PAGE='''<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Browser handover</title><style>
body{font:17px/1.6 system-ui;max-width:1000px;margin:30px auto;padding:20px;background:#f4f6f8;color:#203244}article{padding:20px;margin:16px 0;background:white;border:1px solid #bdcbd5;border-radius:8px}button{font:inherit;padding:8px 16px;margin:8px 8px 0 0;cursor:pointer}button:disabled{cursor:default}p{overflow-wrap:anywhere}.state{font-weight:bold}#error{color:#9f2525}code{font-size:14px}</style></head><body><h1>Browser handover</h1><p>Work in the yielded tab in the browser window. The agent may continue in other tabs. These buttons signal control; they do not click verification or prove it succeeded.</p><p>Choose <b>Start helping</b>, complete the page interaction yourself, then choose <b>Finished</b>. The agent must inspect the returned page before using it.</p><p id="connection" role="status">Connecting…</p><p id="error" role="alert"></p><main id="tabs"></main><script nonce="__NONCE__">
const token='__TOKEN__';let last=-1;const error=document.getElementById('error');
function text(tag,value,parent){const n=document.createElement(tag);n.textContent=value;parent.append(n);return n;}
async function signal(tab,event){error.textContent='';try{const r=await fetch('/signal',{method:'POST',headers:{'Content-Type':'application/json','X-Handover-Token':token},body:JSON.stringify({tab_id:tab.tab_id,event,handover_id:tab.handover_id})});const result=await r.json();if(!r.ok)throw Error(result.error);last=-1;await refresh();}catch(e){error.textContent=e.message;last=-1;}}
function draw(data){const root=document.getElementById('tabs');root.replaceChildren();if(!data.tabs.length)text('p','No browser tabs registered yet.',root);for(const tab of data.tabs){const card=document.createElement('article');root.append(card);text('h2',tab.title||'Untitled tab',card);text('code',tab.tab_id,card);text('p',tab.url,card);text('p',tab.state.replaceAll('_',' '),card).className='state';if(tab.reason)text('p',tab.reason,card);for(const [event,label,allowed] of [['start','Start helping',['awaiting_human']],['complete','Finished',['human_active']],['cancel','Cancel handover',['awaiting_human','human_active']]]){if(!allowed.includes(tab.state))continue;const button=text('button',label,card);button.onclick=async()=>{button.disabled=true;await signal(tab,event);};}if(tab.state==='returned')text('p','Waiting for the agent to inspect fresh page state.',card);}}
async function refresh(){try{const r=await fetch('/state',{cache:'no-store'});if(!r.ok)throw Error('Panel connection failed');const data=await r.json();document.getElementById('connection').textContent=data.available?'Connected — revision '+data.revision:'Controller unavailable';if(data.revision!==last){draw(data);last=data.revision;}if(!data.available)document.querySelectorAll('button').forEach(b=>b.disabled=true);}catch(e){document.getElementById('connection').textContent='Disconnected; ownership is unknown. Stop interacting until reconnected.';document.querySelectorAll('button').forEach(b=>b.disabled=true);last=-1;}}
refresh();setInterval(refresh,1000);
</script></body></html>'''


class HumanHandoverUI:
    def __init__(self,controller,*,port=0):
        self.controller=controller;self._token=secrets.token_urlsafe(32);self._nonce=secrets.token_urlsafe(24);self._embed_token=secrets.token_urlsafe(32);self._instance=secrets.token_hex(12);outer=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def valid_host(self):return self.headers.get('Host') in (f'127.0.0.1:{outer.server.server_port}',f'localhost:{outer.server.server_port}')
            def embedded_auth(self):
                return (self.path in ('/_embedded/state','/_embedded/signal') and
                        self.headers.get('Origin')=='null' and self.valid_host() and
                        hmac.compare_digest(self.headers.get('X-Handover-Token',''),outer._embed_token))
            def reply(self,status,data,mime='application/json'):
                data=(json.dumps(data) if mime=='application/json' else data).encode()
                self.send_response(status);self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(data)))
                self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff')
                if self.embedded_auth():
                    self.send_header('Access-Control-Allow-Origin','null');self.send_header('Vary','Origin')
                self.send_header('Content-Security-Policy',"default-src 'none'; script-src 'nonce-"+outer._nonce+"'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
                self.end_headers();self.wfile.write(data)
            def do_OPTIONS(self):
                # Preflight carries header names, not the secret. Actual requests
                # always authenticate; preflight grants no state or mutation access.
                expected='GET' if self.path=='/_embedded/state' else 'POST' if self.path=='/_embedded/signal' else None
                requested={x.strip().lower() for x in self.headers.get('Access-Control-Request-Headers','').split(',') if x.strip()}
                if (not self.valid_host() or self.headers.get('Origin')!='null' or not expected or
                    self.headers.get('Access-Control-Request-Method')!=expected or
                    not {'x-handover-token'}<=requested or not requested<={'x-handover-token','content-type'}):
                    return self.reply(403,{'error':'Invalid embedded preflight'})
                self.send_response(204);self.send_header('Access-Control-Allow-Origin','null')
                self.send_header('Access-Control-Allow-Methods',expected)
                self.send_header('Access-Control-Allow-Headers','X-Handover-Token, Content-Type')
                self.send_header('Vary','Origin');self.send_header('Cache-Control','no-store')
                if self.headers.get('Access-Control-Request-Private-Network')=='true':self.send_header('Access-Control-Allow-Private-Network','true')
                self.send_header('Content-Length','0');self.end_headers()
            def do_GET(self):
                if not self.valid_host():return self.reply(403,{'error':'Invalid local host'})
                if self.path=='/_embedded/state':
                    if not self.embedded_auth():return self.reply(403,{'error':'Invalid embedded capability'})
                    return self.reply(200,outer.controller.snapshot())
                if self.path=='/':return self.reply(200,PAGE.replace('__TOKEN__',outer._token).replace('__NONCE__',outer._nonce),'text/html; charset=utf-8')
                if self.path=='/state':return self.reply(200,outer.controller.snapshot())
                self.reply(404,{'error':'Not found'})
            def do_POST(self):
                from .human_handover import HandoverConflict
                allowed=(outer.origin,outer.origin.replace('127.0.0.1','localhost'))
                embedded=self.path=='/_embedded/signal'
                authorized=(self.embedded_auth() if embedded else self.valid_host() and self.headers.get('Origin') in allowed and
                            hmac.compare_digest(self.headers.get('X-Handover-Token',''),outer._token))
                if not authorized:
                    return self.reply(403,{'error':'Invalid local control request'})
                if self.path not in ('/signal','/_embedded/signal'):return self.reply(404,{'error':'Not found'})
                try:
                    n=int(self.headers.get('Content-Length','0'))
                    if not 0<n<=8192 or self.headers.get_content_type()!='application/json':raise ValueError('Invalid body')
                    body=json.loads(self.rfile.read(n))
                    if not isinstance(body,dict) or set(body)!={'tab_id','event','handover_id'} or not isinstance(body['handover_id'],str):raise ValueError('Expected tab, event and current handover ID')
                    event=outer.controller.signal(**body)
                except HandoverConflict as e:return self.reply(409,{'error':str(e)})
                except (ValueError,TypeError):return self.reply(400,{'error':'Invalid human transition request'})
                except Exception:return self.reply(503,{'error':'Controller unavailable; stop interacting'})
                self.reply(200,{'accepted':event})
        self.server=ThreadingHTTPServer(('127.0.0.1',port),Handler);self.origin=f'http://127.0.0.1:{self.server.server_port}'
        self.thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.05},daemon=True);self.thread.start()
    def attach_chat(self,chat_page):
        """Owner-thread-only bootstrap into BrowserGym's private chat document.

        Browser fetch runs independently while the owner thread awaits inference.
        The returned diagnostic never contains control capabilities.
        """
        if chat_page is None or chat_page.is_closed():raise ValueError('A live BrowserGym chat page is required')
        if chat_page.url!='about:blank':raise ValueError('Only the private BrowserGym chat document can host controls')
        return chat_page.evaluate(_CHAT_SCRIPT,{'origin':self.origin,'token':self._embed_token,'instance':self._instance})

    def close(self):self.server.shutdown();self.server.server_close();self.thread.join(timeout=2)
    def __enter__(self):return self
    def __exit__(self,*args):self.close()


_CHAT_SCRIPT=r'''({origin,token,instance})=>{
const version='human-chat-controls-v1';
if(!document.getElementById('chatForm')||!document.getElementById('chatBody')||!document.getElementById('inputBox'))throw Error('Unsupported BrowserGym chat document');
const old=document.getElementById('human-handover-controls');
if(old){if(old.dataset.instance!==instance)throw Error('Another controller is attached');return {version,attached:true,already_attached:true};}
const style=document.createElement('style');style.textContent=`
#human-handover-controls{flex:0 0 auto;max-height:36vh;overflow:auto;background:#102e3e;color:#eef7fa;border:1px solid #668899;border-radius:8px;padding:10px;font:14px/1.45 system-ui;margin-top:10px}
#human-handover-controls summary{cursor:pointer;font-weight:bold}#human-handover-controls p{margin:6px 0;overflow-wrap:anywhere}#human-handover-controls article{border-top:1px solid #496879;padding:8px 0}
#human-handover-controls button{font:inherit;padding:6px 10px;margin:5px 5px 0 0;background:#e1f1f6;color:#123040;border:1px solid #98b8c8;border-radius:4px;cursor:pointer}#human-handover-controls button:disabled{opacity:.55;cursor:default}
#human-handover-controls .handover-error{color:#ffb6ac}#human-handover-controls h3{font-size:14px;margin:4px 0}
`;document.head.append(style);
const root=document.createElement('section');root.id='human-handover-controls';root.dataset.instance=instance;root.setAttribute('aria-label','Agent controls');
const details=document.createElement('details');root.append(details);
const summary=document.createElement('summary');summary.textContent='Agent controls';details.append(summary);
const status=document.createElement('p');status.setAttribute('role','status');root.append(status);
const intro=document.createElement('p');intro.textContent='For verification: Start helping, use the yielded browser tab, then Finished. The agent may work elsewhere. Finished is not a verification result.';details.append(intro);
const error=document.createElement('p');error.className='handover-error';error.setAttribute('role','alert');details.append(error);
const list=document.createElement('div');details.append(list);
const input=document.querySelector('.chat-input-area');if(!input||!input.parentNode)throw Error('Chat input container missing');input.parentNode.insertBefore(root,input);
let revision=-1,busy=false,alive=true;const seen=new Set();
function text(tag,value,parent){const e=document.createElement(tag);e.textContent=value;parent.append(e);return e;}
function disable(){list.querySelectorAll('button').forEach(b=>b.disabled=true);}
async function request(path,body){const r=await fetch(origin+'/_embedded/'+path,{method:body?'POST':'GET',mode:'cors',credentials:'omit',cache:'no-store',headers:{'X-Handover-Token':token,...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{})});const result=await r.json();if(!r.ok)throw Error(result.error||'Control request failed');return result;}
function draw(data){list.replaceChildren();let pending=0;for(const tab of data.tabs){if(tab.state==='awaiting_human'||tab.state==='human_active')pending++;
if(tab.state==='awaiting_human'&&!seen.has(tab.handover_id)){details.open=true;seen.add(tab.handover_id);}
const card=document.createElement('article');list.append(card);text('h3',tab.title||'Untitled tab',card);text('p',tab.tab_id+' · '+tab.state.replaceAll('_',' '),card);text('p',tab.url,card);if(tab.reason)text('p',tab.reason,card);
for(const [event,label,allowed] of [['start','Start helping',['awaiting_human']],['complete','Finished',['human_active']],['cancel','Cancel handover',['awaiting_human','human_active']]]){
if(!allowed.includes(tab.state))continue;const button=text('button',label,card);button.type='button';button.disabled=busy||!data.available;
button.onclick=async()=>{if(busy)return;busy=true;disable();error.textContent='';try{await request('signal',{tab_id:tab.tab_id,event,handover_id:tab.handover_id});}catch(e){error.textContent=e.message;}finally{busy=false;revision=-1;}};
}if(tab.state==='returned')text('p','Waiting for fresh inspection by the agent.',card);
}summary.textContent=pending?'Agent controls — help requested ('+pending+')':'Agent controls';status.textContent=data.available?(pending?'Human help requested; open Agent controls.':'Connected. No pending human help request.'):'Controls unavailable. Stop interacting.';if(!data.available)disable();}
async function poll(){if(!alive)return;try{const data=await request('state');if(data.revision!==revision){draw(data);revision=data.revision;}if(!data.available)disable();}catch(e){status.textContent='Controls disconnected. Ownership is unknown; stop interacting until reconnected.';disable();revision=-1;}if(alive)setTimeout(poll,750);}
window.addEventListener('pagehide',()=>{alive=false;},{once:true});poll();
return {version,attached:true,already_attached:false};
}'''
