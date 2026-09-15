import {createToolActivity,keepChatPosition,showChatWorking,bindChatEnter,createFullScreenMode} from './tool-activity.js';
import {World} from './world.js';
import {snapshot,executeAndWait,waitForDocument} from './observation.js';
const $=id=>document.getElementById(id);
const activeStatuses=new Set(['queued','claimed','starting','running','ready','pending','awaiting_client']);
const gradeNames={success:'Succeeded',failed:'Failed',partial:'Partial',ungraded:'Not graded',unknown:'Unknown',pending:'Pending'};
const collectionNames={demo:'Campus demos','browser-agent-chaos':'Browser Agent Chaos',trickyarena:'TrickyArena','synthetic-development':'Development examples'};
const siteNames={chaos:'Chaos scenarios','tricky-shop':'Tricky shop','tricky-health':'Tricky health','tricky-music':'Tricky music','authorized-warranty':'Warranty example','browser-agent-chaos':'Browser Agent Chaos',trickyarena:'TrickyArena','synthetic-development':'Authorized extras'};
let config=null,modelConfig=null,fixture=null,tasks=[],sites=[],jobRows=[],demoRows=[],siteID='campus',view='explore',globalPage=false,currentRun=null;
let askBusy=false,launching=false,authExpired=false,refreshing=false,pollTimer=null,lastDemoRefresh=0,frame=null,pendingDocument=null,agentVisible=true,pendingTask=null,reviewVersion=0;
let messages=[],conversation=[],draft='',activity=[],lastTrace=null,workingText='';
let sidebarBeforeFullscreen=true;
const fullScreen=createFullScreenMode($('enter-fullscreen'),$('exit-fullscreen'),active=>{
  if(active){sidebarBeforeFullscreen=agentVisible;setAgentVisible(true);}else setAgentVisible(sidebarBeforeFullscreen);
});
function setAgentVisible(value){agentVisible=value;$('agent-sidebar').hidden=!value;$('interactive-explore').classList.toggle('agent-hidden',!value);$('toggle-agent').textContent=value?'Hide agent':'Show agent';$('toggle-agent').setAttribute('aria-expanded',String(value));}
function setWorking(text){workingText=text;showChatWorking($('conversation'),text);}
function updateTool(tool,state,error){if(tool)keepChatPosition($('conversation'),()=>tool.update(state,error));}
const initialSearch=new URLSearchParams(location.search);
let requestedSite=initialSearch.get('site');
const folderState=new Map();
let refreshTracesPending=false;
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
const node=(tag,text,className)=>{const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(className)el.className=className;return el;};
const siteFor=id=>sites.find(s=>s.id===id);
const sessionGoal=task=>task?.goal_mode==='resolve_after_session_prepare';
const taskSite=task=>task.site_id|| (task.id==='rooms'?'campus':task.site)||'unknown';
const dateLabel=value=>{const date=new Date(value);return value&&!Number.isNaN(date.valueOf())?date.toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}):'Time not recorded';};
function notice(text=''){$('workspace-notice').textContent=text;$('workspace-notice').hidden=!text;}
async function api(path,data){
  const response=await fetch(path,{credentials:'same-origin',cache:'no-store',redirect:'manual',...(data===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)})});
  if(response.status===401||response.status===302||response.type==='opaqueredirect'){authExpired=true;clearTimeout(pollTimer);syncControls();throw Error('Your invitation session expired. Sign in again before continuing.');}
  const value=await response.json().catch(()=>null);
  if(!response.ok||value===null)throw Object.assign(Error(value?.error||'The server could not complete this request.'),{status:response.status});return value;
}
function gradeOf(record){
  const evaluation=record.evaluation;
  if(evaluation?.safe_success===true)return 'success';
  if(evaluation?.safe_success===false)return 'failed';
  // Partial credit requires an explicit graded value and rubric, never a count of flags.
  if(record.grade==='partial'&&record.rubric)return 'partial';
  if(activeStatuses.has(record.status))return 'pending';
  if(record.source==='demo'&&evaluation==null)return 'ungraded';
  return 'unknown';
}
function gradeBadge(record){const grade=gradeOf(record),span=node('span',gradeNames[grade],'grade '+grade);span.title=grade==='success'||grade==='failed'?'Recorded verifier safe_success: '+String(record.evaluation.safe_success):grade==='partial'?'Explicit recorded grade with rubric':grade==='ungraded'?'No independent verifier result is attached':'No supported final safe-success result recorded';return span;}
function buildSites(){
  tasks=Array.isArray(config?.tasks)?config.tasks:[];
  for(const task of tasks)if(task.collection&&task.collection_name)collectionNames[task.collection]=task.collection_name;
  const map=new Map([['campus',{id:'campus',name:'Campus',collection:'demo',description:'Study rooms, campus supplies and account preferences.',interactive:true,icon:'C'}]]);
  for(const task of tasks){const id=taskSite(task);if(!map.has(id))map.set(id,{id,name:task.site_name||siteNames[id]||id,collection:task.collection||'Reviewed environments',description:'Reviewed tasks run through BrowserGym on the remote worker.',interactive:false,icon:(task.site_name||siteNames[id]||id).slice(0,1)});}
  sites=[...map.values()];
  if(requestedSite&&siteFor(requestedSite)){siteID=requestedSite;requestedSite=null;}
  if(!siteFor(siteID))siteID='campus';
  $('site-count').textContent=String(sites.length);
  const fill=(id,entries,all)=>{const old=$(id).value;$(id).replaceChildren(node('option',all));$(id).firstChild.value='all';for(const [value,label]of entries){const option=node('option',label);option.value=value;$(id).append(option);}if([...$(id).options].some(o=>o.value===old))$(id).value=old;};
  fill('global-site',[...sites.map(s=>[s.id,s.name]),['unknown','Site not recorded']],'All sites');
  fill('global-collection',[...new Set(sites.map(s=>s.collection))].map(c=>[c,collectionNames[c]||c]).concat([['unknown','Collection not recorded']]),'All collections');
}
function records(){
  const jobRecords=jobRows.map(job=>{
    // Historical records stand on their own; today's registry cannot fill gaps.
    const resolvedSite=job.site_id||null;
    return {key:'h:'+job.id,id:job.id,source:'harness',kind:['task','ask'].includes(job.interaction_kind)?job.interaction_kind:null,
      site:resolvedSite||'unknown',collection:job.collection||'unknown',title:job.task_name||(job.task?'Task ID: '+job.task:'Task name not recorded'),condition:job.condition||null,
      goal:job.goal,task:job.task,revision:job.task_revision,status:job.status,at:job.created_at,runtime:'BrowserGym',executionMode:job.mode||null,evaluation:job.evaluation??null,grade:job.grade??null,rubric:job.rubric??null,raw:job};
  });
  const browserRecords=demoRows.map(trace=>({key:'d:'+trace.id,id:trace.id,source:'demo',kind:['task','ask'].includes(trace.interaction_kind)?trace.interaction_kind:null,
    site:trace.site_id||'unknown',collection:trace.collection||'unknown',title:trace.task_name||trace.goal||'Browser-side run',goal:trace.goal,task:trace.task_id||null,
    status:trace.status,at:trace.created_at,runtime:trace.runtime||'Browser-side demo',executionMode:trace.execution_mode||null,evaluation:trace.evaluation??null,raw:trace}));
  return [...jobRecords,...browserRecords].sort((a,b)=>(Date.parse(b.at)||0)-(Date.parse(a.at)||0));
}
function renderSites(){
  const query=$('site-search').value.trim().toLowerCase();$('site-folders').replaceChildren();
  for(const collection of [...new Set(sites.map(s=>s.collection))]){
    const matching=sites.filter(s=>s.collection===collection&&[s.name,s.description,collection].join(' ').toLowerCase().includes(query));if(!matching.length)continue;
    const details=node('details',undefined,'site-folder');details.open=folderState.get(collection)??true;details.ontoggle=()=>{if(details.isConnected)folderState.set(collection,details.open);};const summary=node('summary',collectionNames[collection]||collection);summary.append(node('span',String(matching.length)));details.append(summary);
    for(const site of matching){const button=node('button',undefined,'site-choice');button.type='button';button.dataset.site=site.id;button.disabled=askBusy;button.setAttribute('aria-current',String(!globalPage&&site.id===siteID));const text=node('span');text.append(node('strong',site.name),node('small',site.interactive?'Explore · tasks · replays':'Remote tasks · replays'));button.append(node('span',site.icon,'site-icon'),text);button.onclick=()=>selectSite(site.id);details.append(button);}
    $('site-folders').append(details);
  }
  $('sites-empty').hidden=!!$('site-folders').children.length;
  for(const id of ['all-replays-link','global-library-link']){if(globalPage)$(id).setAttribute('aria-current','page');else $(id).removeAttribute('aria-current');}
}
function ensureFrame(){
  if(frame||!fixture)return frame;
  frame=document.createElement('iframe');frame.title='Campus — interactive website';frame.dataset.site='campus';frame.src='/world/'+crypto.randomUUID()+'/booking';frame.addEventListener('load',updateAddress);$('site-frames').append(frame);fullScreen.bindFrame(frame);return frame;
}
function updateAddress(){let area='booking';try{area=frame?.contentWindow.location.pathname.split('/').at(-1)||area;}catch{}$('site-address').textContent='campus.demo / '+({booking:'study rooms',shop:'shop',preferences:'account'}[area]||'page');}
async function currentPage(){const previous=pendingDocument,doc=await waitForDocument(ensureFrame(),{previousDocument:previous});if(pendingDocument===previous)pendingDocument=null;return doc;}
function renderConversation(){
  const log=$('conversation'),follow=log.scrollHeight-log.scrollTop-log.clientHeight<64,top=log.scrollTop;
  log.replaceChildren();
  if(!messages.length){const welcome=node('div',undefined,'chat-welcome');welcome.append(node('span','✳'),node('h3','Explore first. Ask whenever you need.'),node('p','Click around the site, or ask the agent to find something. Tasks and previous runs are one tab away.'));$('conversation').append(welcome);}
  for(const message of messages){if(message.role==='tool'){log.append(message.element);continue;}const div=node('div',undefined,'message '+message.role);div.append(node('strong',message.role==='user'?'You':'Daylight'),document.createTextNode(message.text));if(message.trace){const a=node('a','Download original turn record ↗','record-link');a.href='/api/traces/'+encodeURIComponent(message.trace);div.append(a);}$('conversation').append(div);}
  $('question').value=draft;showChatWorking(log,workingText);log.scrollTop=follow?log.scrollHeight:top;
  $('suggestions').replaceChildren(...['Find a room for three people','What can I do on this page?'].map(text=>{const button=node('button',text);button.type='button';button.disabled=askBusy||authExpired;button.onclick=()=>{draft=text;$('question').value=text;$('question').focus();};return button;}));
}
function syncControls(){
  const canAsk=!!modelConfig?.live_available&&!authExpired&&!askBusy&&!!fixture;
  $('question').disabled=!canAsk;$('send-question').disabled=!canAsk;$('reset-page').disabled=askBusy||!fixture;
  if(frame){frame.inert=askBusy;frame.style.pointerEvents=askBusy?'none':'';}
  $('explore-status').textContent=askBusy?'The agent is using this page…':'You can click, type and navigate freely.';
  const canLaunch=!!config?.enabled&&config?.worker?.mode==='live'&&pendingTask?.available!==false;
  $('try-task').disabled=launching||authExpired||!pendingTask||!canLaunch;
  $('try-task').textContent=launching?'Queuing…':config?.worker?.mode!=='live'?'Live worker required':config?.worker?.online?'Try this task →':'Queue task →';
  document.querySelectorAll('.site-choice,#suggestions button').forEach(button=>button.disabled=askBusy||authExpired);
}
function recordRow(record,all){
  const row=node('tr');row.dataset.run=record.key;row.dataset.site=record.site;row.dataset.kind=record.kind||'unknown';
  const cell=node('td'),button=node('button',undefined,'run-title');button.type='button';button.append(node('span',record.kind==='task'?'Task':record.kind==='ask'?'Ask':'Activity unknown','run-kind '+(record.kind||'unknown')),document.createTextNode(' '+(record.kind==='ask'?record.goal||record.title:record.title)));button.onclick=()=>openRecord(record,all);
  cell.append(button,node('span',[record.runtime,record.executionMode,record.condition,record.status].filter(Boolean).join(' · '),'run-meta'));row.append(cell);
  if(all){const siteCell=node('td',undefined,'site-cell');siteCell.textContent=siteFor(record.site)?.name||(record.site==='unknown'?'Not recorded':record.site);siteCell.append(node('small',record.collection==='unknown'?'Collection not recorded':collectionNames[record.collection]||record.collection));row.append(siteCell);}
  const grade=node('td');grade.append(gradeBadge(record));row.append(grade,node('td',dateLabel(record.at),'when'));
  const action=node('td'),open=node('button',activeStatuses.has(record.status)&&record.source==='harness'?'Watch →':record.source==='harness'?'Replay ↗':'Inspect ↗','replay-action');open.type='button';open.setAttribute('aria-label','Open '+record.title);open.onclick=()=>openRecord(record,all);action.append(open);row.append(action);return row;
}
function renderTasks(){
  $('task-list-heading').textContent='Tasks for '+siteFor(siteID).name;
  const currentTasks=tasks.filter(t=>taskSite(t)===siteID);
  $('task-cards').replaceChildren(...currentTasks.map((task,i)=>{const card=node('article',undefined,'task-card'+(task.available===false?' unavailable':''));card.append(node('span','TASK '+String(i+1).padStart(2,'0'),'task-index'),node('h3',task.title||task.id));if(task.condition)card.append(node('span',task.condition,'condition'));card.append(node('p',sessionGoal(task)?'The trusted objective is resolved when the new session starts.':task.goal||'No goal available.'));const button=node('button',task.available===false?'Task unavailable':'View task →');button.type='button';button.dataset.task=task.id;button.onclick=()=>showTask(task);card.append(button);return card;}));
  if(!currentTasks.length)$('task-cards').append(node('p','No reviewed tasks are registered for this site.','task-empty'));
  $('task-worker-mode').textContent=config?.worker?.mode==='live'?'OpenRouter · live worker':config?.worker?.mode==='rehearsal'?'Worker in rehearsal mode':'Worker unavailable';
  $('replay-site-name').textContent=siteFor(siteID).name;
  const kind=$('replay-kind').value,rows=records().filter(r=>r.site===siteID&&(kind==='all'||(r.kind||'unknown')===kind));$('replay-rows').replaceChildren(...rows.map(r=>recordRow(r,false)));$('replay-empty').hidden=!!rows.length;
}
function renderGlobal(){
  const query=$('global-search').value.trim().toLowerCase(),collection=$('global-collection').value,site=$('global-site').value,kind=$('global-kind').value,grade=$('global-grade').value,all=records();
  const matches=all.filter(r=>(site==='all'||r.site===site)&&(kind==='all'||(r.kind||'unknown')===kind)&&(grade==='all'||gradeOf(r)===grade)&&(collection==='all'||r.collection===collection)&&(!query||[r.title,r.goal,r.id,siteFor(r.site)?.name].join(' ').toLowerCase().includes(query)));
  $('global-rows').replaceChildren(...matches.map(r=>recordRow(r,true)));$('global-count').textContent=matches.length+' of '+all.length+' recorded runs';$('global-empty').hidden=!!matches.length;
}
function showTask(task){
  pendingTask=task;$('dialog-site').textContent=siteFor(taskSite(task))?.name+' / Task';$('dialog-task-name').textContent=task.title||task.id;$('dialog-goal').textContent=sessionGoal(task)?'Resolved when the session starts':task.goal||'No goal recorded';
  $('dialog-verification').textContent=task.verification_scope||'The worker records independent environment outcomes when a supported verifier is available.';
  $('dialog-task-facts').replaceChildren(...[['Condition',task.condition],['Task ID',task.id],['Revision',task.revision],['Scope',task.development_only?'Development fixture':null]].filter(([,value])=>value).flatMap(([key,value])=>[node('dt',key),node('dd',String(value))]));
  $('task-launch-status').textContent=task.available===false?'The configured worker does not advertise this task.':!config?.worker?.online?'The worker is offline. Queued tasks wait for it to reconnect.':'';
  syncControls();$('task-dialog').showModal();
}
function pathFor(){return globalPage?'/workspace/replays'+(currentRun&&view==='review'?'?run='+encodeURIComponent(currentRun.key):''):'/workspace?site='+encodeURIComponent(siteID)+(view!=='explore'?'&view='+view:'')+(view==='review'&&currentRun?'&run='+encodeURIComponent(currentRun.key):'');}
function syncURL(replace=false){history[replace?'replaceState':'pushState'](null,'',pathFor());}
function selectSite(id){if(askBusy)return;draft=$('question').value;siteID=id;globalPage=false;view='explore';currentRun=null;render();syncURL();}
function setView(next){draft=$('question').value;globalPage=false;view=next;currentRun=null;render();syncURL();if(next==='research')refresh(true);}
function openGlobal(event){event?.preventDefault();draft=$('question').value;globalPage=true;view='global';currentRun=null;render();syncURL();refresh(true);}
async function openRecord(record,fromGlobal=globalPage){
  $('run-viewer').dataset.run='';
  currentRun=record;globalPage=fromGlobal;view='review';if(!fromGlobal&&siteFor(record.site))siteID=record.site;render();syncURL();
  if(record.source==='demo')await loadBrowserTrace(record);
}
function renderReview(){
  const record=currentRun;if(!record)return;
  $('back-to-research').textContent=globalPage?'← All traces & replays':'← Tasks & replays';$('recording-status').textContent=activeStatuses.has(record.status)?'In progress · recorded evidence':'Recorded evidence · view only';
  $('review-kind').textContent=[record.kind==='task'?'Task attempt':record.kind==='ask'?'Ask the agent':'Activity not recorded',siteFor(record.site)?.name||record.site,record.runtime].join(' · ');
  $('review-title').textContent=record.kind==='ask'?record.goal||record.title:record.title;$('review-grade').replaceChildren(gradeBadge(record));
  const isJob=record.source==='harness';$('run-viewer').hidden=!isJob;$('browser-trace-review').hidden=isJob;
  if(isJob){const mode=activeStatuses.has(record.status)?'watch':'replay',src='/harness?embed=1&activity='+mode+'#'+encodeURIComponent(record.id);const viewer=$('run-viewer');if(viewer.dataset.run!==record.id){viewer.dataset.run=record.id;viewer.src=src;}}
}
async function loadBrowserTrace(record){
  const version=++reviewVersion;$('browser-trace-json').textContent='Loading original evidence…';$('browser-record-summary').textContent='Loading recorded run…';$('browser-trace-download').href='/api/traces/'+encodeURIComponent(record.id);
  try{const value=await api('/api/traces/'+encodeURIComponent(record.id));if(currentRun?.key!==record.key||version!==reviewVersion)return;$('browser-record-summary').textContent=(value.steps?.length||0)+' recorded model attempts · '+(value.status||'Status not recorded')+' · '+(value.goal||'No goal recorded');$('browser-trace-json').textContent=JSON.stringify(value,null,2);}catch(error){if(currentRun?.key===record.key&&version===reviewVersion)$('browser-trace-json').textContent=error.message;}
}
function render(){
  const site=siteFor(siteID);if(!site)return;
  if(globalPage||view!=='explore'||!site.interactive)fullScreen.setActive(false,{focus:false});
  document.querySelector('.site-heading').hidden=globalPage;document.querySelector('.site-tabs').hidden=globalPage;
  $('site-breadcrumb').textContent=(collectionNames[site.collection]||site.collection)+' / '+site.name;$('site-name').textContent=site.name;$('site-description').textContent=site.description;$('site-label').textContent=site.interactive?'Interactive website':'Remote worker environment';
  $('explore-view').hidden=globalPage||view!=='explore';$('research-view').hidden=globalPage||view!=='research';$('global-view').hidden=!globalPage||view==='review';$('review-view').hidden=view!=='review';
  $('explore-tab').setAttribute('aria-pressed',String(view==='explore'));$('research-tab').setAttribute('aria-pressed',String(view!=='explore'));$('replay-count').textContent=String(records().filter(r=>r.site===siteID).length);
  $('tab-note').textContent=view==='explore'?'Browse the site or open a reviewed task.':'Tasks and recorded attempts for this site.';
  renderSites();
  $('remote-explore').hidden=site.interactive;$('interactive-explore').hidden=!site.interactive;
  if(!globalPage&&view==='explore'&&site.interactive){ensureFrame();updateAddress();$('agent-site').textContent='Campus · current page';renderConversation();}
  if(view==='research')renderTasks();if(globalPage&&view!=='review')renderGlobal();if(view==='review')renderReview();syncControls();
}
async function fetchDemoRows(){
  let cursor;const rows=[],seen=new Set();
  do{const page=await api('/api/traces?limit=100'+(cursor?'&cursor='+encodeURIComponent(cursor):''));rows.push(...(Array.isArray(page.traces)?page.traces:[]));if(!page.has_more)return rows;if(!page.cursor||seen.has(page.cursor))throw Error('Trace history pagination did not advance.');seen.add(page.cursor);cursor=page.cursor;}while(rows.length<10000);
  throw Error('Trace history exceeds this viewer’s listing limit.');
}
async function refresh(forceTraces=false){
  if(authExpired)return;if(refreshing){refreshTracesPending ||= forceTraces;return;}refreshing=true;const includeDemo=forceTraces||Date.now()-lastDemoRefresh>60000;
  try{
    const results=await Promise.allSettled([api('/api/harness/config'),api('/api/harness/jobs'),...(includeDemo?[fetchDemoRows()]:[])]);
    if(results[0].status==='fulfilled'){config=results[0].value;buildSites();$('worker-status').textContent=config.worker?.online?'● Worker online · '+(config.worker.mode==='live'?'live agent':'rehearsal'):'○ Worker offline';}
    if(results[1].status==='fulfilled')jobRows=results[1].value.jobs||[];
    if(results[2]?.status==='fulfilled'){demoRows=results[2].value;lastDemoRefresh=Date.now();}
    for(const result of results)if(result.status==='rejected')notice(result.reason.message);
    if(currentRun){const updated=records().find(r=>r.key===currentRun.key);if(updated)currentRun=updated;}
    if(pendingTask){const latest=tasks.find(t=>t.id===pendingTask.id);if(latest&&latest.revision===pendingTask.revision)pendingTask=latest;}
    // Do not rebuild the conversation/composer during periodic updates.
    renderSites();if(view==='research')renderTasks();if(globalPage&&view!=='review')renderGlobal();if(view==='review')renderReview();syncControls();
  }finally{refreshing=false;clearTimeout(pollTimer);if(!authExpired){if(refreshTracesPending){refreshTracesPending=false;pollTimer=setTimeout(()=>refresh(true),0);}else pollTimer=setTimeout(()=>refresh(),jobRows.some(j=>activeStatuses.has(j.status))?4000:15000);}}
}
$('try-task').onclick=async()=>{
  const task=pendingTask;if(!task||launching||authExpired||!config?.enabled||config.worker?.mode!=='live'||task.available===false)return;
  const payload={task:task.id,interaction_kind:'task',required_execution_mode:'live',...(task.revision?{task_revision:task.revision}:{}),...(sessionGoal(task)?{}:{goal:task.goal})};
  if(!sessionGoal(task)&&!task.goal){$('task-launch-status').textContent='The task has no configured goal.';return;}
  launching=true;syncControls();$('task-launch-status').textContent='Queuing a real worker run…';
  try{const job=await api('/api/harness/jobs',payload);jobRows=[job,...jobRows.filter(j=>j.id!==job.id)];$('task-dialog').close();const record=records().find(r=>r.id===job.id&&r.source==='harness');await openRecord(record,false);refresh();}
  catch(error){$('task-launch-status').textContent=error.message+' No automatic retry will be made.';if(error.status===409)refresh();}
  finally{launching=false;syncControls();}
};
async function askAgent(question){
  askBusy=true;syncControls();messages.push({role:'user',text:question});draft='';renderConversation();syncControls();$('chat-status').textContent='';setWorking('Looking at the page…');
  let id,cost=0,unknown=0,pendingTool=null,actionError=null;const before=structuredClone(window.demoWorld.state),priorActivity=JSON.stringify({last_trace:lastTrace,steps:activity});activity=[];
  const spend=()=> 'Reported model cost $'+cost.toFixed(4)+(unknown?' · '+unknown+' request(s) with unknown cost':'');
  try{
    await currentPage();({id}=await api('/api/start',{mode:'assist',goal:question,interaction_kind:'ask',site_id:'campus'}));lastTrace=id;
    for(let i=0;i<12;i++){
      setWorking(i?'Choosing the next action…':'Looking at the page…');if(i)await wait(750);const captured=snapshot(await currentPage());unknown++;
      const result=await api('/api/step',{id,observation:captured.observation,conversation,activity:priorActivity});
      if(typeof result.cost==='number'&&Number.isFinite(result.cost)){cost+=result.cost;unknown--;}
      if(result.alerts?.length)notice(result.alerts.join(' '));if(result.error)throw Error(result.error);if(!result.action)throw Error('No complete action was returned.');
      const action=result.action,control=captured.observation.controls.find(c=>c.id===action.id),description=action.action==='done'?'Agent supplied an answer':[action.action,control?.label,action.value!==undefined?String(action.value):''].filter(Boolean).join(' · ');
      setWorking('');actionError=null;
      if(action.action!=='done'){pendingTool=createToolActivity(action,captured,i+1);messages.push({role:'tool',element:pendingTool.element});renderConversation();}
      let error=null,after=null;
      try{after=snapshot(await executeAndWait(action,captured,frame)).observation;}catch(e){error=e.message;}
      actionError=error;updateTool(pendingTool,error?'failed':'saving',error);
      activity.push((error?'Failed: ':'')+description);const boundary=window.demoWorld.state.bookings.length>before.bookings.length;
      const saved=await api('/api/event',{id,result:{error,description,stop:boundary,stop_reason:error?'client_execution_error':boundary?'first_accepted_reservation':action.action==='done'?'model_done':null,page_after:after,state_after:window.demoWorld.state,events:window.demoWorld.events}});
      updateTool(pendingTool,error?'failed':'applied',error);pendingTool=null;
      if(error)throw Error(error);
      if(saved.status!=='ready'){
        if(!['complete','step_limit'].includes(saved.status))throw Error('The server stopped this turn ('+saved.status+').');
        const answer=saved.status==='step_limit'?'The request reached its step limit. Review the current page and original record.':boundary?'The demo recorded a reservation and stopped at its one-reservation limit. Review it under My reservations.':result.answer||action.message||'The request finished. Review the recorded evidence.';
        messages.push({role:'assistant',text:answer,trace:id});conversation.push({role:'user',content:question},{role:'assistant',content:answer});conversation=conversation.slice(-8);$('chat-status').textContent=spend();return;
      }
    }
    throw Error('The client step limit was reached without a terminal receipt.');
  }catch(error){updateTool(pendingTool,actionError?'failed':'unrecorded',(actionError? actionError+' ':'')+'Receipt not saved: '+error.message);messages.push({role:'assistant',text:'The request stopped: '+error.message+' Earlier page changes may already have happened.',trace:id});$('chat-status').textContent=spend();notice(error.message);}
  finally{setWorking('');askBusy=false;renderConversation();syncControls();await refresh(true);}
}
$('ask-form').onsubmit=async event=>{event.preventDefault();const question=$('question').value.trim();if(!question||askBusy||authExpired||!modelConfig?.live_available||siteID!=='campus')return;await askAgent(question);};
bindChatEnter($('question'),$('send-question'));
$('question').oninput=()=>{draft=$('question').value;};$('site-search').oninput=renderSites;$('replay-kind').onchange=renderTasks;
$('explore-tab').onclick=()=>setView('explore');$('research-tab').onclick=()=>setView('research');$('sidebar-tasks').onclick=()=>setView('research');$('remote-tasks').onclick=()=>setView('research');
for(const id of ['all-replays-link','global-library-link'])$(id).onclick=openGlobal;
for(const id of ['global-search','global-collection','global-site','global-kind','global-grade'])$(id).addEventListener(id==='global-search'?'input':'change',renderGlobal);
$('clear-filters').onclick=()=>{for(const id of ['global-collection','global-site','global-kind','global-grade'])$(id).value='all';$('global-search').value='';renderGlobal();};
$('toggle-agent').onclick=()=>setAgentVisible(!agentVisible);
$('reset-page').onclick=()=>{if(askBusy||!frame)return;window.demoWorld=new World(fixture);pendingDocument=frame.contentDocument;frame.src='/world/'+crypto.randomUUID()+'/booking';messages=[];conversation=[];draft='';activity=[];lastTrace=null;setWorking('');$('chat-status').textContent='';renderConversation();};
$('back-to-research').onclick=()=>{view=globalPage?'global':'research';currentRun=null;reviewVersion++;render();syncURL();};
async function readRoute(){const params=new URLSearchParams(location.search);globalPage=location.pathname==='/workspace/replays';if(siteFor(params.get('site')))siteID=params.get('site');const key=params.get('run');currentRun=records().find(r=>r.key===key)||null;view=currentRun?'review':globalPage?'global':params.get('view')==='research'?'research':'explore';render();if(currentRun?.source==='demo')loadBrowserTrace(currentRun);}
window.addEventListener('popstate',readRoute);window.addEventListener('pagehide',()=>clearTimeout(pollTimer));
window.addEventListener('message',event=>{if(event.origin!==location.origin||event.source!==$('run-viewer').contentWindow||event.data?.type!=='harness:size')return;const height=Number(event.data.height);if(Number.isFinite(height))$('run-viewer').style.height=Math.min(8000,Math.max(650,height))+'px';});
try{const results=await Promise.allSettled([api('/assets/fixture.json'),api('/api/config')]);if(results[0].status==='fulfilled'){fixture=results[0].value;window.demoWorld=new World(fixture);}if(results[1].status==='fulfilled')modelConfig=results[1].value;for(const result of results)if(result.status==='rejected')notice(result.reason.message);await refresh(true);buildSites();await readRoute();if(!modelConfig?.live_available)$('chat-status').textContent='OpenRouter is not configured for this deployment.';}catch(error){notice(error.message);syncControls();}
