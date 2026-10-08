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
    if(typeof sidebarSessions==='undefined'||sidebarSessions!==sessions)list();
    if(!chosen){current=null;loaded='';pageStart=0;list();el('title').textContent=desired&&desired!=='latest'?'Session not found':'No traces recorded yet';el('chat').replaceChildren();el('count').textContent='';return}
    const cacheKey=parser+':'+chosen.id;
    if(current?.id!==chosen.id||loaded!==cacheKey+':'+chosen.revision){
      el('connection').textContent='Loading trace…';
      const cached=traceCache.get(cacheKey);
      const headers=cached?{'If-None-Match':'"'+cached.revision+'"'}:{};
      // Revalidate on navigation: a cached catalog may predate a live update.
      const r=await fetch('/api/sessions/'+chosen.id+query,{signal:request.signal,headers});
      if(r.status!==304&&!r.ok)throw Error('Trace is being updated; retry shortly');
      const data=r.status===304?cached.data:prepareLedgerSession(await r.json());
      if(own!==generation)return;
      const revision=r.headers.get('ETag')?.replaceAll('"','')||chosen.revision;
      // Compressed Content-Length understates the retained JSON size.
      const bytes=r.status===304?cached.bytes:Number(r.headers.get('X-Trace-Bytes'))||new TextEncoder().encode(JSON.stringify(data)).length;
      cacheTrace(cacheKey,{data,revision,bytes});
      const same=current?.id===data.id,follow=same&&traceAtBottom(),anchor=same&&!follow?captureTracePosition():null;
      if(!same){pageStart=0;detailState.clear();el('chat').replaceChildren()}
      current=data;loaded=cacheKey+':'+revision;
      const {messages,turns,value_ledger,...summary}=data;
      Object.assign(chosen,summary,{revision,summary_pending:false,summary_stale:false});
      render(anchor,follow);
      if(follow)scrollTraceToBottom();else restoreTracePosition(anchor);
    }else list();
    el('connection').textContent='Connected · checked '+new Date().toLocaleTimeString()+' · timestamps shown in your local timezone';
  }catch(error){
    if(error.name!=='AbortError'&&own===generation)list();
    if(error.name!=='AbortError'&&own===generation)el('connection').textContent='Disconnected / unavailable: '+error.message+' · existing view retained';
  }finally{
    if(traceRequest===request)traceRequest=null;
  }
}

function renderDerivedGrade(){
  const grade=current?.derived_evaluation;
  if(!grade)return;
  const box=node('section','notice derived-grade');box.id='derived-answer-grade';
  box.style.cssText='background:#18212e;border-color:#36475d';
  const verdict=grade.binding_status!=='verified'?'Unavailable — evidence binding failed':
    grade.structured_claims_correct===true?'Passed':grade.structured_claims_correct===false?'Failed':'Inconclusive';
  box.append(node('h3','','Post-run answer checks: '+verdict));
  box.append(node('p','','These checks grade the final answer and covered state changes after browsing finishes. They are not model input.'));
  const original=node('details');original.append(node('summary','','Browser-phase outcome (before answer grading)'));
  original.append(node('p','',(current.recorded_evaluation_label||'unknown')+'. This earlier record is preserved separately; it does not mean the answer checks above are missing or failed.'));
  box.append(original);
  if(grade.binding_status!=='verified'){
    box.append(node('p','',grade.error||'Invalid derived grade'));el('notices').prepend(box);return;
  }
  box.append(node('p','',`Extractor: ${grade.extractor.model} · ${grade.extractor.provider} · ${grade.extractor.version}`));
  const table=node('table');table.style.cssText='border-collapse:collapse;width:100%;margin:12px 0';
  const head=node('tr');head.append(node('th','','Requirement'),node('th','','Result'));table.append(head);
  const names={no_unauthorized_effects:'No unauthorized changes',base_claim:'Task answer',reported_total:'Reported total',
    public_selection_identity:'Selected product and retailer',follow_up_sku_link:'Exact-variant product link',
    follow_up_coupon_code:'Required coupon code',reported_currency:'Reported currency'};
  for(const [key,value] of Object.entries({...grade.requirements,...grade.additional_checks})){
    const row=node('tr'),cell=node('td'),check=node('details');check.dataset.check=key;
    row.style.backgroundColor=value===true?'rgba(115,206,150,.10)':value===false?'rgba(255,141,141,.10)':'transparent';
    const stateKey=current.id+':check:'+key;check.open=detailState.get(stateKey)??false;
    check.addEventListener('toggle',()=>detailState.set(stateKey,check.open));
    check.append(node('summary','',names[key]||key.replaceAll('_',' ')));
    const explanation=grade.check_details?.[key];
    if(explanation){
      check.append(node('p','',explanation.explanation));
      const facts=node('dl');
      for(const [name,val] of [['Expected',explanation.expected],['Supplied / observed',explanation.supplied]]){
        const term=node('dt','',name);term.style.fontWeight='bold';
        const definition=node('dd','',val!==null&&typeof val==='object'?JSON.stringify(val,null,2):val);
        definition.style.whiteSpace='pre-wrap';
        definition.style.cssText='margin:4px 0 12px;white-space:pre-wrap;overflow-wrap:anywhere';facts.append(term,definition);
      }
      check.append(facts);
      if(explanation.answer_quote){check.append(node('b','','Quoted answer evidence'),node('blockquote','',explanation.answer_quote))}
    }else{
      check.append(node('p','',grade.check_details_error?'Check details unavailable: '+grade.check_details_error:'Detailed expected/supplied values have not been exported for this grade.'));
    }
    cell.append(check);row.append(cell,node('td','',value===true?'Pass':value===false?'Fail':'Unknown'));
    row.firstChild.title=key;
    for(const cell of row.children)cell.style.cssText='text-align:left;padding:5px 10px;border-bottom:1px solid #42516a';
    table.append(row);
  }
  box.append(table);
  for(const text of grade.limitations)box.append(node('p','muted',text));
  const detail=node('details');detail.dataset.key=current.id+':derived-grade';detail.open=detailState.get(detail.dataset.key)??false;
  detail.append(node('summary','','Extracted claims, URL derivations and evidence hashes'),
    contentView(JSON.stringify({claims:grade.claims,oracle_answer:grade.oracle_answer,derivations:grade.derivations,
      selected_candidate_assessment:grade.selected_candidate_assessment,
      extractor:grade.extractor,source_directory:grade.source_directory,source_artifact_sha256:grade.source_artifact_sha256,
      episode_artifact_sha256:grade.episode_artifact_sha256},null,2),current.id+':derived-facts'));
  box.append(detail);el('notices').prepend(box);
}
