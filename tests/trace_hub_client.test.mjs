// Exercise the shipped loader with controlled responses, including request races.
import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';

const source=readFileSync(new URL('../scripts/trace_hub_client.js',import.meta.url),'utf8');
const trace=id=>({id,title:id,revision:'r1',messages:[],turns:{},max_isl_tokens:12345});
const reply=(data,{status=200,revision='r1'}={})=>({status,ok:status===200,
  headers:new Map([['ETag','"'+revision+'"'],['X-Trace-Bytes','1000']]),
  async json(){assert.notEqual(status,304,'304 response has no JSON body');return data;}});
function setup(){
  const calls=[],renders=[],scrolls=[],elements=new Map();
  const context=vm.createContext({AbortController,TextEncoder,Date,
    location:{hash:'#a'},renders,scrolls,
    el(id){if(!elements.has(id))elements.set(id,{value:id==='parser'?'auto':'',replaceChildren(){}});return elements.get(id);},
    list(){},render(anchor,follow){renders.push({anchor,follow,id:vm.runInContext('current.id',context)});},
    async refreshCollections(){},
    chooseSession(id){return vm.runInContext('sessions',context).find(session=>session.id===id);},
    prepareLedgerSession(data){return data;},
    traceAtBottom(){return context.atBottom;},
    captureTracePosition(){return {id:'message',offset:12,y:400};},
    scrollTraceToBottom(){scrolls.push('bottom');},restoreTracePosition(anchor){scrolls.push(anchor);},
    atBottom:true,
    async fetch(url,options){calls.push({url,...options});return context.respond(url,options);},
    respond(url){return reply(url==='/api/sessions'?[trace('a'),trace('b')]:trace(url.split('/').at(-1)));},
  });
  vm.runInContext("let sessions=[],current=null,loaded='',generation=0,pageStart=0; const detailState=new Map();",context);
  vm.runInContext(source,context);
  return {context,calls,renders,scrolls,elements,run:code=>vm.runInContext(code,context)};
}
async function waitFor(check){
  for(let i=0;i<20&&!check();i++)await Promise.resolve();
  assert.ok(check());
}

test('navigation fetches only selected trace; revisits reuse JSON after 304',async()=>{
  const h=setup();await h.run('refresh()');
  h.context.location.hash='#b';await h.run('refresh({navigate:true})');
  h.context.respond=(url,options)=>{
    assert.equal(url,'/api/sessions/a');
    assert.equal(options.headers['If-None-Match'],'"r1"');
    return reply(null,{status:304});
  };
  h.context.location.hash='#a';await h.run('refresh({navigate:true})');
  assert.deepEqual(h.calls.map(c=>c.url),['/api/sessions','/api/sessions/a','/api/sessions/b','/api/sessions/a']);
  assert.deepEqual(h.renders.map(r=>r.id),['a','b','a']);
  assert.equal(h.run('current.max_isl_tokens'),12345);
  assert.equal(h.run('sessions[0].summary_pending'),false);
});

test('background polling cannot supersede a pending initial load',async()=>{
  const h=setup();let complete;
  h.context.respond=url=>url==='/api/sessions'?reply([trace('a')]):new Promise(resolve=>{complete=resolve;});
  const loading=h.run('refresh()');await waitFor(()=>complete);
  await h.run('refresh({background:true})');
  assert.equal(h.calls.length,2);assert.equal(h.run('generation'),1);
  complete(reply(trace('a')));await loading;
  assert.deepEqual(h.renders.map(r=>r.id),['a']);
});

test('user navigation supersedes a pending response, even if abort is ignored',async()=>{
  const h=setup();let complete;
  h.context.respond=url=>url==='/api/sessions'?reply([trace('a'),trace('b')]):url.endsWith('/a')?
    new Promise(resolve=>{complete=resolve;}):reply(trace('b'));
  const loading=h.run('refresh()');await waitFor(()=>complete);
  h.context.location.hash='#b';await h.run('refresh({navigate:true})');
  assert.equal(h.calls[1].signal.aborted,true);
  complete(reply(trace('a')));await loading;
  assert.deepEqual(h.renders.map(r=>r.id),['b']);
  assert.equal(h.run('current.id'),'b');
});

test('unchanged background refresh retains DOM and skips trace download',async()=>{
  const h=setup();await h.run('refresh()');await h.run('refresh({background:true})');
  assert.deepEqual(h.calls.map(c=>c.url),['/api/sessions','/api/sessions/a','/api/sessions']);
  assert.equal(h.renders.length,1);
});

for(const atBottom of [true,false])test('live updates preserve '+(atBottom?'bottom following':'reading position'),async()=>{
  const h=setup();await h.run('refresh()');h.context.atBottom=atBottom;
  h.context.respond=url=>reply(url==='/api/sessions'?[{...trace('a'),revision:'r2'}]:trace('a'),{revision:'r2'});
  await h.run('refresh({background:true})');
  assert.equal(h.renders.at(-1).follow,atBottom);
  assert.equal(h.scrolls.at(-1)==='bottom',atBottom);
  if(!atBottom)assert.equal(h.scrolls.at(-1).id,'message');
});

test('parser changes cannot reuse a different parser cache',async()=>{
  const h=setup();await h.run('refresh()');h.elements.get('parser').value='generic';
  h.context.respond=url=>reply(url.startsWith('/api/sessions?')?[trace('a')]:trace('a'));
  await h.run('refresh()');
  assert.equal(h.calls.at(-1).url,'/api/sessions/a?parser=generic');
  assert.equal(h.calls.at(-1).headers['If-None-Match'],undefined);
});

test('failed navigation retains the current trace and allows a retry',async()=>{
  const h=setup();await h.run('refresh()');h.context.location.hash='#b';
  h.context.respond=()=>reply(null,{status:503});await h.run('refresh({navigate:true})');
  assert.equal(h.run('current.id'),'a');assert.equal(h.run('traceRequest'),null);
  assert.match(h.elements.get('connection').textContent,/retry shortly/);
  h.context.respond=()=>reply(trace('b'));await h.run('refresh({navigate:true})');
  assert.equal(h.run('current.id'),'b');
});

test('JSON cache evicts least recently used entries within its budget',()=>{
  const h=setup();
  h.run("for(let i=0;i<6;i++)cacheTrace('k'+i,{bytes:40*1024*1024})");
  assert.equal(h.run('traceCache.size'),3);
  assert.equal(h.run("traceCache.has('k2')"),false);
  assert.equal(h.run('traceCacheBytes'),120*1024*1024);
});
