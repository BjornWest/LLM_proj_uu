// Loaded in the shared viewer's script scope by trace_hub.viewer_html().
let traceRequest=null;
const traceCache=new Map();
let traceCacheBytes=0;
function cacheTrace(key,entry){
  const old=traceCache.get(key);
  if(old){traceCacheBytes-=old.bytes;traceCache.delete(key)}
  if(entry.bytes>128*1024*1024)return;
  traceCache.set(key,entry);traceCacheBytes+=entry.bytes;
  while(traceCache.size>4||traceCacheBytes>128*1024*1024){
    const first=traceCache.keys().next().value;
    traceCacheBytes-=traceCache.get(first).bytes;traceCache.delete(first);
  }
}
async function refresh({background=false,navigate=false}={}){
  if(background&&traceRequest)return;
  traceRequest?.abort();
  const request=new AbortController();traceRequest=request;
  const own=++generation,parser=el('parser').value,query=parser==='auto'?'':'?parser='+encodeURIComponent(parser);
  const desired=location.hash.slice(1);
  try{
    if(!navigate||!sessions.some(s=>s.id===desired)){
      const response=await fetch('/api/sessions'+query,{signal:request.signal});
      if(!response.ok)throw Error('Session catalog unavailable');
      const items=await response.json();if(own!==generation)return;
      sessions=items;
    }
    const chosen=sessions.find(s=>s.id===desired)||(desired===''||desired==='latest'?sessions.find(s=>s.state==='active')||sessions[0]:null);
    list();
    if(!chosen){current=null;loaded='';pageStart=0;list();el('title').textContent=desired&&desired!=='latest'?'Session not found':'No traces recorded yet';el('chat').replaceChildren();el('count').textContent='';return}
    const cacheKey=parser+':'+chosen.id;
    if(current?.id!==chosen.id||loaded!==cacheKey+':'+chosen.revision){
      el('connection').textContent='Loading trace…';
      const cached=traceCache.get(cacheKey);
      const headers=cached?{'If-None-Match':'"'+cached.revision+'"'}:{};
      // Revalidate on navigation: a cached catalog may predate a live update.
      const r=await fetch('/api/sessions/'+chosen.id+query,{signal:request.signal,headers});
      if(r.status!==304&&!r.ok)throw Error('Trace is being updated; retry shortly');
      const data=r.status===304?cached.data:await r.json();
      if(own!==generation)return;
      const revision=r.headers.get('ETag')?.replaceAll('"','')||chosen.revision;
      // Compressed Content-Length understates the retained JSON size.
      const bytes=r.status===304?cached.bytes:Number(r.headers.get('X-Trace-Bytes'))||new TextEncoder().encode(JSON.stringify(data)).length;
      cacheTrace(cacheKey,{data,revision,bytes});
      const same=current?.id===data.id,follow=same&&traceAtBottom(),anchor=same&&!follow?captureTracePosition():null;
      if(!same){pageStart=0;detailState.clear();el('chat').replaceChildren()}
      current=data;loaded=cacheKey+':'+revision;
      const {messages,turns,...summary}=data;
      Object.assign(chosen,summary,{revision,summary_pending:false});
      render(anchor,follow);
      if(follow)scrollTraceToBottom();else restoreTracePosition(anchor);
    }
    el('connection').textContent='Connected · checked '+new Date().toLocaleTimeString()+' · timestamps shown in your local timezone';
  }catch(error){
    if(error.name!=='AbortError'&&own===generation)el('connection').textContent='Disconnected / unavailable: '+error.message+' · existing view retained';
  }finally{
    if(traceRequest===request)traceRequest=null;
  }
}
