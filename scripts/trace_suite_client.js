// Project-local read-only suite view. The shared trace renderer remains unchanged.
const suiteStyle=node('style');suiteStyle.textContent=`
main[data-suite-mode="true"]>:not(#suite-view){display:none!important}
#suite-view[hidden]{display:none!important}
#show-suites.selected{border-color:#86c1ff;background:#20344c}
.suite-badge{display:block;margin-top:5px;color:#b8d2ff;font-size:12px}.suite-toolbar{display:flex;gap:8px;margin:8px 0 14px}.suite-scroll{overflow-x:auto;max-width:100%}.suite-table{border-collapse:collapse;width:100%;font-size:13px}.suite-table th,.suite-table td{padding:10px;text-align:left;border-bottom:1px solid #334155;white-space:nowrap}.suite-table th{background:#172331}.suite-table td:nth-child(2){white-space:normal;min-width:170px}.suite-card{padding:14px;border:1px solid #334155;border-radius:8px;margin:10px 0}.suite-note{color:#b5bfce;font-size:13px}.suite-state{font-weight:600}.suite-pass{color:#8ce0ad}.suite-fail{color:#ff9e9e}`;document.head.append(suiteStyle);
const suitesButton=node('button','','Suites');suitesButton.id='show-suites';suitesButton.onclick=()=>{location.hash='suites'};
const suitesToolbar=node('div','suite-toolbar');suitesToolbar.append(suitesButton);el('sessions').before(suitesToolbar);
const suitePanel=node('section');suitePanel.id='suite-view';suitePanel.hidden=true;document.querySelector('main').append(suitePanel);
let suiteGeneration=0,suiteSignature=null;
const suiteFilters=new Map();
const originalList=list;
list=function(){
 originalList();const items=[...sessions];if(el('order').value==='oldest')items.reverse();
 [...el('sessions').children].forEach((button,index)=>{
  if(document.querySelector('main').dataset.suiteMode==='true')button.classList.remove('selected');
  const member=items[index]?.suite;if(!member)return;
  const badge=node('a','suite-badge',member.title+' · '+member.case_id);badge.href='#suite/'+encodeURIComponent(member.id);
  badge.title=(member.tags||[]).join(' · ');badge.onclick=event=>{event.stopPropagation()};button.append(badge);
 });
};
function suiteMode(enabled){
 document.querySelector('main').dataset.suiteMode=String(enabled);
 suitePanel.hidden=!enabled;suitesButton.setAttribute('aria-pressed',String(enabled));
 suitesButton.classList.toggle('selected',enabled);
 if(enabled)for(const button of el('sessions').children)button.classList.remove('selected');
}
function suiteNumber(value){return typeof value==='number'?value.toLocaleString():'—'}
function suiteVerdict(value){return value===true?'Passed':value===false?'Failed':'Unknown'}
function suiteCell(row,text,cls=''){row.append(node('td',cls,text));}
function renderSuiteIndex(rows){
 suitePanel.replaceChildren(node('h2','','Episode suites'),node('p','suite-note','Frozen task/model sets. Open a suite to compare its episodes; original traces remain individually accessible.'));
 if(!rows.length)suitePanel.append(node('p','','No suites registered. Use the suite launcher’s register-viewer command.'));
 for(const suite of rows){
  const card=node('article','suite-card'),link=node('a','',suite.title);link.href='#suite/'+encodeURIComponent(suite.id);
  card.append(link,node('p','',suite.description||''),node('p','suite-note',`${suite.case_count} cases · ${suite.counts.pass||0} passed · ${suite.counts.fail||0} failed · ${suite.counts.unknown||0} unknown`),node('p','suite-note',(suite.tags||[]).join(' · ')));suitePanel.append(card);
 }
}
function renderSuiteDetail(suite){
 const back=node('a','','← All suites');back.href='#suites';
 suitePanel.replaceChildren(back,node('h2','',suite.title),node('p','',suite.description||''),node('p','suite-note',(suite.tags||[]).join(' · ')),node('p','suite-note',suite.grade_scope_note));
 suitePanel.append(node('p','',`${suite.case_count} cases · ${suite.counts.pass||0} passed · ${suite.counts.fail||0} failed · ${suite.counts.unknown||0} unknown`));
 const filter=suiteFilters.get(suite.id)||{text:'',model:'',outcome:''};suiteFilters.set(suite.id,filter);
 const controls=node('div','suite-toolbar'),search=node('input'),models=node('select'),outcomes=node('select'),matching=node('p','suite-note');
 search.type='search';search.placeholder='Filter case or task';search.value=filter.text;search.setAttribute('aria-label','Filter suite cases');
 models.setAttribute('aria-label','Filter suite model');models.append(node('option','','All models'));models.firstChild.value='';
 for(const name of [...new Set(suite.cases.map(c=>c.model))]){const option=node('option','',name);option.value=name;models.append(option)}models.value=filter.model;
 outcomes.setAttribute('aria-label','Filter suite outcome');
 for(const [value,label] of [['','All outcomes'],['true','Passed'],['false','Failed'],['unknown','Unknown']]){const option=node('option','',label);option.value=value;outcomes.append(option)}outcomes.value=filter.outcome;
 controls.append(search,models,outcomes);suitePanel.append(controls,matching);
 const table=node('table','suite-table'),thead=node('thead'),header=node('tr');
 for(const text of ['Trace','Case / task','Model','Repeat','Execution','Outcome','Check scope','Grading','Requests','Tool calls','Max ISL','Input tokens¹','Output tokens¹','Cached input¹','Reported charge²'])header.append(node('th','',text));
 thead.append(header);table.append(thead);const tbody=node('tbody');
 for(const c of suite.cases){
  const row=node('tr'),trace=node('td');if(c.trace_url){const link=node('a','','Open trace');link.href=c.trace_url;trace.append(link)}else trace.textContent='Not started';row.append(trace);
  const first=node('td');first.append(node('b','',c.case_id),node('div','suite-note',c.task_title));row.append(first);
  suiteCell(row,c.model);suiteCell(row,String(c.repeat));suiteCell(row,c.state.replaceAll('_',' '));
  suiteCell(row,suiteVerdict(c.verdict),c.verdict===true?'suite-pass':c.verdict===false?'suite-fail':'');
  suiteCell(row,c.verdict_scope?.replaceAll('_',' ')||'Unestablished');suiteCell(row,c.grading_status.replaceAll('_',' '));
  const u=c.usage||{};suiteCell(row,suiteNumber(u.model_requests??c.model_turn_count));suiteCell(row,suiteNumber(u.tool_call_count??c.tool_call_count));
  suiteCell(row,suiteNumber(u.max_isl_tokens??c.max_isl_tokens));suiteCell(row,suiteNumber(u.prompt_tokens));suiteCell(row,suiteNumber(u.completion_tokens));suiteCell(row,suiteNumber(u.cached_prompt_tokens));
  suiteCell(row,u.billing==='subscription'?'Subscription; charge unreported':typeof u.reported_cost_usd==='number'?'$'+u.reported_cost_usd.toFixed(6)+(u.unknown_cost_requests?' + unknown charges':''):'—');
  tbody.append(row);
 }
 table.append(tbody);const scroll=node('div','suite-scroll');scroll.append(table);suitePanel.append(scroll,
 node('p','suite-note','¹ Provider-reported tokens summed over requests, using each model’s tokenizer. Max ISL is the largest reported request input; totals are not unique context.'),
 node('p','suite-note','² Episode model charges only; answer-extraction charges are separate. Unknown charges are not zero. A passed answer check does not establish whole-episode safe success.'));
 function applyFilters(){
  filter.text=search.value;filter.model=models.value;filter.outcome=outcomes.value;let visible=0;
  [...tbody.children].forEach((row,index)=>{const c=suite.cases[index],outcome=c.verdict===null?'unknown':String(c.verdict);
   row.hidden=!(c.case_id+' '+c.task_title).toLowerCase().includes(filter.text.toLowerCase())||(filter.model!==''&&c.model!==filter.model)||(filter.outcome!==''&&outcome!==filter.outcome);
   if(!row.hidden)visible++;
  });matching.textContent=`Showing ${visible} of ${suite.case_count} cases`;
 }
 search.oninput=applyFilters;models.onchange=applyFilters;outcomes.onchange=applyFilters;applyFilters();
}
const originalRefresh=refresh;
refresh=async function(options={}){
 const hash=decodeURIComponent(location.hash.slice(1)),enabled=hash==='suites'||hash.startsWith('suite/');
 const changed=document.querySelector('main').dataset.suiteMode!==String(enabled);
 suiteMode(enabled);
 if(!enabled){suiteGeneration++;suiteSignature=null;return originalRefresh(options)}
 // Invalidate in-flight trace refreshes before they can render into suite mode.
 traceRequest?.abort();generation++;
 const own=++suiteGeneration;
 try{
  const route=hash==='suites'?'/api/suites':'/api/suites/'+encodeURIComponent(hash.slice(6));
  const [response,catalog]=await Promise.all([fetch(route),changed||!sessions.length?fetch('/api/sessions'):Promise.resolve(null),refreshCollections(undefined,()=>own===suiteGeneration)]);
  if(!response.ok)throw Error('Suite unavailable ('+response.status+')');
  const data=await response.json();if(own!==suiteGeneration)return;
  if(catalog?.ok){const items=await catalog.json();if(own!==suiteGeneration)return;sessions=items;}
  list();
  const signature=hash+JSON.stringify(data);
  if(signature!==suiteSignature){suiteSignature=signature;hash==='suites'?renderSuiteIndex(data):renderSuiteDetail(data)}
  if(changed||options.navigate){document.querySelector('main').scrollTop=0;if(getComputedStyle(document.querySelector('main')).overflowY==='visible')window.scrollTo(0,0)}
  el('connection').textContent='Connected · suite status refreshed '+new Date().toLocaleTimeString();
 }catch(error){if(own===suiteGeneration)el('connection').textContent=error.message+' · existing view retained'}
};

refresh({navigate:true});
