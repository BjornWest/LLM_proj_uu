import {createToolActivity,keepChatPosition,showChatWorking,bindChatEnter,createFullScreenMode,InterruptibleTurn,TurnInterrupted,interruptionNotice,transcriptBubble,transcriptDetail,renderTraceConversation,groupTraceSessions,renderJobToolReview} from './tool-activity.js';
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
let activeTurn=null,interrupting=false,conversationID=null;
let remotePollTimer=null,remoteSending=false,remoteRendered='',remotePollFailed=false;
let manualConfig=null,manualSessions=[],manualBusy=false,manualUncertain=false,manualError='',manualFrameKey='',manualFrameLoaded=false,manualImageError='',manualCheckedAt=null;
const manualChoices=new Map(),manualLive=session=>session&&['starting','ready','busy'].includes(session.status);
const manualSite=()=>manualConfig?.sites?.find(site=>site.site_id===siteID);
const manualCurrent=()=>manualSessions.find(session=>session.site_id===siteID&&manualLive(session))||manualSessions.find(session=>session.site_id===siteID);
const manualOwnerLive=()=>manualSessions.find(manualLive);
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
let refreshTracesPending=false,refreshRequested=false;
let historyLoading=null,historyLoaded=false,historyMore=false,historyCursor=null,historyError='',historyStale=false;
const historyCursors=new Set();
let libraryRows=[],libraryLoading=false,libraryLoaded=false,libraryAttempted=false,libraryMore=false,libraryCursor=null,libraryError='',libraryEnabled=true;
const libraryCursors=new Set();
const historyWanted=()=>globalPage||view==='research'||view==='review';
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
  if(record.source==='manual')return 'ungraded';
  const evaluation=record.evaluation;
  if(evaluation?.safe_success===true)return 'success';
  if(evaluation?.safe_success===false)return 'failed';
  // Partial credit requires an explicit graded value and rubric, never a count of flags.
  if(record.grade==='partial'&&record.rubric)return 'partial';
  if(activeStatuses.has(record.status))return 'pending';
  if(record.source==='demo'&&evaluation==null)return 'ungraded';
  return 'unknown';
}
function gradeBadge(record){const grade=gradeOf(record),span=node('span',gradeNames[grade],'grade '+grade);span.title=record.source==='manual'?'Shared or human-controlled browser; reference checks are diagnostic, not an Ask grade.':grade==='success'||grade==='failed'?'Recorded verifier safe_success: '+String(record.evaluation.safe_success):grade==='partial'?'Explicit recorded grade with rubric':grade==='ungraded'?'No independent verifier result is attached':'No supported final safe-success result recorded';return span;}
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
  const browserRecords=groupTraceSessions(demoRows).map(turns=>{
    const first=turns[0],last=turns.at(-1),same=key=>turns.every(turn=>(turn[key]??null)===(first[key]??null))?first[key]??null:null;
    return {key:'d:'+first.id,id:first.id,source:'demo',turns,kind:['task','ask'].includes(same('interaction_kind'))?same('interaction_kind'):null,
      site:same('site_id')||'unknown',collection:same('collection')||'unknown',title:first.task_name||first.goal||'Browser conversation',goal:first.goal,task:same('task_id'),condition:same('condition'),
      status:last.status,at:last.created_at,runtime:same('runtime')||'Browser-side demo',executionMode:same('execution_mode'),evaluation:turns.length===1?first.evaluation??null:null,raw:first};
  });
  const manualRecords=manualSessions.map(session=>({key:'m:'+session.id,id:session.id,source:'manual',kind:'manual',site:session.site_id||'unknown',collection:session.collection||'unknown',title:session.task_name||session.task||'Manual session',condition:session.condition||null,goal:session.reference_goal,task:session.task,status:session.status,at:session.created_at,runtime:session.runtime||'BrowserGym',executionMode:'Human controlled',evaluation:null,raw:session}));
  const savedRecords=libraryRows.map(row=>({key:'l:'+row.id,id:row.id,source:'library',kind:['task','ask'].includes(row.interaction_kind)?row.interaction_kind:null,site:row.site_id||'unknown',collection:row.collection||'unknown',title:row.task_name||row.title||'Saved run',goal:row.goal||null,task:row.task_id||null,condition:row.condition||null,status:row.execution_status||row.state,at:row.started_at||row.created_at,runtime:row.environment||'Saved trace',executionMode:row.execution_mode||null,evaluation:row.evaluation??null,grade:row.grade??null,rubric:row.rubric??null,raw:row}));
  return [...jobRecords,...browserRecords,...manualRecords,...savedRecords].sort((a,b)=>(Date.parse(b.at)||0)-(Date.parse(a.at)||0));
}
function renderSites(){
  const query=$('site-search').value.trim().toLowerCase();$('site-folders').replaceChildren();
  for(const collection of [...new Set(sites.map(s=>s.collection))]){
    const matching=sites.filter(s=>s.collection===collection&&[s.name,s.description,collection].join(' ').toLowerCase().includes(query));if(!matching.length)continue;
    const details=node('details',undefined,'site-folder');details.open=folderState.get(collection)??true;details.ontoggle=()=>{if(details.isConnected)folderState.set(collection,details.open);};const summary=node('summary',collectionNames[collection]||collection);summary.append(node('span',String(matching.length)));details.append(summary);
    for(const site of matching){const button=node('button',undefined,'site-choice');button.type='button';button.dataset.site=site.id;button.disabled=askBusy;button.setAttribute('aria-current',String(!globalPage&&site.id===siteID));const text=node('span');text.append(node('strong',site.name),node('small',site.interactive?'Explore · tasks · replays':manualConfig?.enabled&&manualConfig.sites?.some(row=>row.site_id===site.id)?'Manual explore · tasks · replays':'Remote tasks · replays'));button.append(node('span',site.icon,'site-icon'),text);button.onclick=()=>selectSite(site.id);details.append(button);}
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
  if($('question').value!==draft)$('question').value=draft;
  showChatWorking(log,workingText);log.scrollTop=follow?log.scrollHeight:top;
  $('suggestions').replaceChildren(...['Find a room for three people','What can I do on this page?'].map(text=>{const button=node('button',text);button.type='button';button.disabled=askBusy||authExpired;button.onclick=()=>{draft=text;$('question').value=text;$('question').focus();};return button;}));
}
function syncControls(){
  const canAsk=!!modelConfig?.live_available&&!authExpired&&!!fixture;
  $('question').disabled=!canAsk;$('send-question').disabled=!canAsk||interrupting;$('reset-page').disabled=askBusy||!fixture;
  $('send-question').dataset.running=String(askBusy);$('send-question').setAttribute('aria-label',askBusy?'Interrupt and send message':'Send message');
  $('question').placeholder=askBusy?'Draft your next message while Daylight works…':'Ask about this site, or give a request…';
  $('send-question').title=askBusy?'Interrupt the current run and send this message':'Send message';
  document.querySelector('.composer-footer span').textContent=askBusy?'Enter to interrupt · Shift+Enter for a new line':'Enter to send · Shift+Enter for a new line';
  if(frame){frame.inert=askBusy;frame.style.pointerEvents=askBusy?'none':'';}
  $('explore-status').textContent=askBusy?'The agent is using this page…':'You can click, type and navigate freely.';
  const canLaunch=!!config?.enabled&&config?.worker?.mode==='live'&&pendingTask?.available!==false;
  $('try-task').disabled=launching||authExpired||!pendingTask||!canLaunch;
  $('try-task').textContent=launching?'Queuing…':config?.worker?.mode!=='live'?'Live worker required':config?.worker?.online?'Try this task →':'Queue task →';
  document.querySelectorAll('.site-choice,#suggestions button').forEach(button=>button.disabled=askBusy||manualBusy||authExpired);
}
function recordRow(record,all){
  const row=node('tr');row.dataset.run=record.key;row.dataset.site=record.site;row.dataset.kind=record.kind||'unknown';
  const cell=node('td'),button=node('button',undefined,'run-title');button.type='button';button.append(node('span',record.kind==='task'?'Task':record.kind==='ask'?'Ask':record.kind==='manual'?'Manual':'Activity unknown','run-kind '+(record.kind||'unknown')),document.createTextNode(' '+(record.kind==='ask'?record.goal||record.title:record.title)));button.onclick=()=>openRecord(record,all);
  cell.append(button,node('span',[record.runtime,record.turns?record.turns.length+' turn'+(record.turns.length===1?'':'s'):null,record.executionMode,record.condition,record.status].filter(Boolean).join(' · '),'run-meta'));row.append(cell);
  if(all){const siteCell=node('td',undefined,'site-cell');siteCell.textContent=siteFor(record.site)?.name||(record.site==='unknown'?'Not recorded':record.site);siteCell.append(node('small',record.collection==='unknown'?'Collection not recorded':collectionNames[record.collection]||record.collection));row.append(siteCell);}
  const grade=node('td');grade.append(gradeBadge(record));row.append(grade,node('td',dateLabel(record.at),'when'));
  const action=node('td'),open=node('button',activeStatuses.has(record.status)&&record.source==='harness'?'Watch →':['harness','library'].includes(record.source)?'Replay ↗':record.source==='demo'?'Conversation ↗':'Inspect ↗','replay-action');open.type='button';open.setAttribute('aria-label','Open '+record.title);open.onclick=()=>openRecord(record,all);action.append(open);row.append(action);return row;
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
  const matches=all.filter(r=>(site==='all'||r.site===site)&&(kind==='all'||(r.kind||'unknown')===kind)&&(grade==='all'||gradeOf(r)===grade)&&(collection==='all'||r.collection===collection)&&(!query||[r.title,r.goal,r.id,siteFor(r.site)?.name,...(r.turns||[]).flatMap(turn=>[turn.goal,turn.id])].join(' ').toLowerCase().includes(query)));
  $('global-rows').replaceChildren(...matches.map(r=>recordRow(r,true)));$('global-count').textContent=matches.length+' of '+all.length+' loaded conversations & runs';$('global-empty').hidden=!!matches.length;
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
function selectSite(id){if(askBusy||manualBusy)return;draft=$('question').value;if(!manualUncertain)manualError='';siteID=id;globalPage=false;view='explore';currentRun=null;render();syncURL();}
function setView(next){draft=$('question').value;globalPage=false;view=next;currentRun=null;render();syncURL();if(next==='research'){refresh();loadHistory();loadManual();}}
function openGlobal(event){event?.preventDefault();draft=$('question').value;globalPage=true;view='global';currentRun=null;render();syncURL();refresh();loadHistory();loadManual();}
async function openRecord(record,fromGlobal=globalPage){
  $('run-viewer').dataset.run='';
  currentRun=record;globalPage=fromGlobal;view='review';if(!fromGlobal&&siteFor(record.site))siteID=record.site;render();syncURL();
  if(record.source==='demo')await loadBrowserTrace(record);
}
function renderReview(){
  const record=currentRun;if(!record)return;
  $('back-to-research').textContent=globalPage?'← All traces & replays':'← Tasks & replays';$('recording-status').textContent=activeStatuses.has(record.status)?'In progress · recorded evidence':'Recorded evidence · view only';
  $('review-kind').textContent=[record.kind==='task'?'Task attempt':record.kind==='ask'?'Ask the agent':record.kind==='manual'?(record.raw?.asks?.length?'Shared browser session':'Manual exploration'):'Activity not recorded',siteFor(record.site)?.name||record.site,record.runtime].join(' · ');
  $('review-title').textContent=record.kind==='ask'?record.goal||record.title:record.title;$('review-grade').replaceChildren(gradeBadge(record));
  const isLibrary=record.source==='library',shared=$('shared-trace-viewer');shared.hidden=!isLibrary;
  if(isLibrary){$('run-viewer').hidden=true;$('browser-trace-review').hidden=true;$('manual-review').hidden=true;if(shared.dataset.session!==record.id){shared.dataset.session=record.id;shared.src='/trace-viewer?embed=1#'+encodeURIComponent(record.id);}return;}
  if(shared.hasAttribute('src')){shared.removeAttribute('src');delete shared.dataset.session;}
  const isJob=record.source==='harness',isManual=record.source==='manual';$('run-viewer').hidden=!isJob;$('browser-trace-review').hidden=isManual;$('browser-trace-download').hidden=isJob;$('trace-raw-details').hidden=isJob;$('manual-review').hidden=!isManual;
  if(isManual){const session=record.raw;$('manual-review-summary').textContent=[session.status,(session.action_count??0)+' recorded browser actions',session.condition,session.site_revision?'Site version '+session.site_revision.slice(0,12):null].filter(Boolean).join(' · ');$('manual-review-goal').textContent='Reference objective: '+(session.reference_goal||'Not recorded');$('manual-reference-evaluation').textContent=session.reference_evaluation==null?'No reference evaluation recorded.':JSON.stringify(session.reference_evaluation,null,2);$('manual-trace-download').hidden=!session.trace_ready;if(session.trace_ready)$('manual-trace-download').href='/api/manual/sessions/'+encodeURIComponent(session.id)+'/trace';else $('manual-trace-download').removeAttribute('href');}
  if(isJob){renderJobConversation(record);const mode=activeStatuses.has(record.status)?'watch':'replay',src='/harness?embed=1&activity='+mode+'#'+encodeURIComponent(record.id);const viewer=$('run-viewer');if(viewer.dataset.run!==record.id){viewer.dataset.run=record.id;viewer.src=src;}}
}
function recordForKey(key){return records().find(record=>record.key===key||record.turns?.some(turn=>'d:'+turn.id===key))||null;}
function renderJobConversation(record){
  const log=$('trace-conversation'),job=record.raw,key=JSON.stringify([record.key,job.goal,job.steps]);if(log.dataset.job===key)return;log.dataset.job=key;log.replaceChildren();
  $('browser-record-summary').textContent='Recorded goal and browser actions. Full model messages are not published for this run. Screenshots and exact step observations are below.';
  log.append(transcriptBubble('user',record.kind==='task'?'Task objective':'Recorded goal',job.goal||'Goal not recorded yet.'));
  for(const step of job.steps||[]){
    const action=typeof step.action==='string'?step.action:JSON.stringify(step.action??'No action recorded');
    log.append(transcriptBubble('assistant',job.mode==='live'?'Model · recorded decision '+step.step:job.mode==='rehearsal'?'Scripted decision '+step.step:'Recorded decision '+step.step,action));
    const receipt=transcriptBubble('tool','Browser tool · Step '+step.step,step.error?'Failed: '+String(step.error):step.browser_stepped?'Browser action recorded.':'Browser execution is not confirmed.');
    transcriptDetail(receipt,'Exact action',action);log.append(receipt);
  }
  renderJobToolReview(log,job);
}
async function loadBrowserTrace(record){
  const version=++reviewVersion,log=$('trace-conversation');log.parentElement.querySelector('.trace-tools-panel')?.remove();log.hidden=false;delete log.dataset.job;log.replaceChildren(node('p','Loading the recorded conversation…','muted'));
  $('browser-trace-json').textContent='Loading original evidence…';$('browser-record-summary').textContent='Loading recorded turns…';$('browser-trace-download').href='/api/traces/'+encodeURIComponent(record.id);
  const turns=record.turns||[record.raw];
  try{
    const values=[];
    // Bounded parallel reads; never download every conversation to list history.
    for(let offset=0;offset<turns.length;offset+=4){if(currentRun?.key!==record.key||version!==reviewVersion)return;values.push(...await Promise.all(turns.slice(offset,offset+4).map(turn=>api('/api/traces/'+encodeURIComponent(turn.id)))));}
    if(currentRun?.key!==record.key||version!==reviewVersion)return;
    $('browser-record-summary').textContent=values.length+' loaded turn'+(values.length===1?'':'s')+' · '+values.reduce((sum,value)=>sum+(value.steps?.length||0),0)+' recorded steps · read-only';
    renderTraceConversation(log,values);$('browser-trace-json').textContent=JSON.stringify(values.length===1?values[0]:values,null,2);
    $('browser-trace-download').textContent=values.length===1?'Download original JSON ↓':'Download first turn JSON ↓';
  }catch(error){if(currentRun?.key===record.key&&version===reviewVersion){log.replaceChildren(node('p','The conversation could not be loaded: '+error.message,'muted'));$('browser-trace-json').textContent=error.message;}}
}

function render(){
  if(view!=='review'&&$('shared-trace-viewer').hasAttribute('src')){$('shared-trace-viewer').removeAttribute('src');delete $('shared-trace-viewer').dataset.session;}
  const site=siteFor(siteID);if(!site)return;
  if(globalPage||view!=='explore'||!site.interactive)fullScreen.setActive(false,{focus:false});
  document.querySelector('.site-heading').hidden=globalPage;document.querySelector('.site-tabs').hidden=globalPage;
  $('site-breadcrumb').textContent=(collectionNames[site.collection]||site.collection)+' / '+site.name;$('site-name').textContent=site.name;$('site-description').textContent=!site.interactive&&manualConfig?.enabled&&manualSite()?'Browse yourself or ask the agent to use this same remote session.':site.description;$('site-label').textContent=site.interactive?'Interactive website':'Remote worker environment';
  $('explore-view').hidden=globalPage||view!=='explore';$('research-view').hidden=globalPage||view!=='research';$('global-view').hidden=!globalPage||view==='review';$('review-view').hidden=view!=='review';
  $('explore-tab').setAttribute('aria-pressed',String(view==='explore'));$('research-tab').setAttribute('aria-pressed',String(view!=='explore'));$('replay-count').textContent=historyLoaded?String(records().filter(r=>r.site===siteID).length)+(historyMore?'+':''):'…';
  $('tab-note').textContent=view==='explore'?'Browse the site or open a reviewed task.':'Tasks and recorded attempts for this site.';
  renderSites();
  $('remote-explore').hidden=site.interactive;$('interactive-explore').hidden=!site.interactive;
  if(!site.interactive)renderManual();
  if(!globalPage&&view==='explore'&&site.interactive){ensureFrame();updateAddress();$('agent-site').textContent='Campus · current page';renderConversation();}
  if(view==='research')renderTasks();if(globalPage&&view!=='review')renderGlobal();if(view==='review')renderReview();syncControls();
}
function updateManualViews(){
  renderManual();renderSites();syncControls();
  if(currentRun?.source==='manual')currentRun=records().find(record=>record.key===currentRun.key)||currentRun;
  if(view==='research')renderTasks();if(globalPage&&view!=='review')renderGlobal();if(view==='review')renderReview();
  $('replay-count').textContent=historyLoaded?String(records().filter(record=>record.site===siteID).length)+(historyMore?'+':''):'…';
}
function rememberManual(session){
  if(!session?.id)throw Error('The manual browser returned no session. Check sessions before continuing.');
  manualSessions=[session,...manualSessions.filter(row=>row.id!==session.id)];
}
function renderManual(){
  $('local-shop-launch').hidden=!['tricky-shop','authorized-warranty'].includes(siteID);
  $('local-shop-clean').hidden=siteID==='authorized-warranty';
  $('local-music-launch').hidden=siteID!=='tricky-music';
  $('local-health-launch').hidden=siteID!=='tricky-health';
  const site=manualSite(),session=manualCurrent(),live=manualOwnerLive(),ready=session?.status==='ready';
  renderRemoteAsk(session);
  const pending=manualBusy||!!manualLoading;
  const elsewhere=live&&live.site_id!==siteID,otherName=elsewhere?(siteFor(live.site_id)?.name||live.site_id):'';
  const ended=!!session&&!manualLive(session);
  const selected=(manualLive(session)?session.task:null)||manualChoices.get(siteID)||site?.default_task||site?.tasks?.[0]?.id||'';
  $('manual-task').replaceChildren(...(site?.tasks||[]).map(task=>{const option=node('option',(task.title||task.id)+(task.condition?' · '+task.condition:''));option.value=task.id;return option;}));$('manual-task').value=selected;
  $('manual-task').disabled=pending||!!live||authExpired;
  $('manual-open').disabled=pending||manualUncertain||!!live||authExpired||!manualConfig?.enabled||!selected;
  $('manual-open').textContent=manualBusy&&!session?'Opening…':session?'Open new session':'Open website';
  $('manual-check').disabled=pending||authExpired;
  $('manual-close').disabled=pending||manualUncertain||authExpired||!manualLive(session)||!ready;
  $('manual-other').hidden=!elsewhere;$('manual-other').disabled=pending;$('manual-other').textContent='Go to active '+otherName+' session →';
  $('manual-close-other').hidden=!elsewhere;$('manual-close-other').disabled=pending||manualUncertain||authExpired||live?.status!=='ready';$('manual-close-other').textContent='Close '+otherName+' session';
  const error=manualError||session?.last_error||session?.error||'';
  const unsupported=siteID==='tricky-health'&&String(error).includes('Browser left supported health routes');
  $('manual-error').hidden=!error;$('manual-error').textContent=unsupported?'That older session hit a route restriction. Medical records and profiles were not included in that fixture. Its saved image and trace remain available. Open a new session to use the restored site.':String(error);
  $('manual-error-details').hidden=!unsupported;$('manual-error-raw').textContent=unsupported?String(error):'';
  $('manual-scope').hidden=siteID!=='tricky-health';$('manual-scope').textContent='The current site includes Home, privacy settings, Appointments, scheduling, medical records, doctor profiles, messages and lab results. Three PDF downloads are missing upstream. Older traces retain their original site version.';
  $('manual-status').textContent=manualBusy?'Waiting for the remote browser…':manualLoading?'Checking session status…':manualUncertain?'Command outcome needs checking. Refresh session status before another action.':elsewhere?'Your '+otherName+' session is '+live.status+' and occupies your one remote-browser slot. Close it or return to it before opening this site.':session?'Session '+session.status+' · '+(session.action_count??0)+' browser actions'+(ended?' · '+(session.stop_reason==='manual_session_timeout'?'Expired after inactivity. ':'')+'This browser is closed; open a new session to continue.':''):manualConfig?.enabled&&site?'Open a private browser session. It may take up to 25 seconds.':manualConfig===null?'Checking manual browser availability…':'Manual exploration is unavailable for this site right now. Agent tasks remain separate.';
  $('manual-check').textContent=manualLoading?'Checking…':'Refresh session status';
  $('manual-checked').textContent=manualCheckedAt?'Status checked at '+new Date(manualCheckedAt).toLocaleTimeString()+'. This checks for completed, failed or expired sessions; it does not refresh the screenshot or repeat actions.':'Session status and screenshot refresh are separate.';
  $('manual-browser').hidden=!session?.frame;
  const f=session?.frame,key=f?session.id+'/'+f.id:'';
  if(key!==manualFrameKey){manualFrameKey=key;manualFrameLoaded=false;manualImageError='';if(f&&Number.isFinite(f.width)&&f.width>0&&Number.isFinite(f.height)&&f.height>0){$('manual-frame').width=f.width;$('manual-frame').height=f.height;$('manual-frame').src='/api/manual/sessions/'+encodeURIComponent(session.id)+'/frame/'+encodeURIComponent(f.id);}else $('manual-frame').removeAttribute('src');}
  const controls=pending||manualUncertain||authExpired||!ready||!manualFrameLoaded;
  $('manual-surface').setAttribute('aria-disabled',String(controls));$('manual-surface').tabIndex=controls?-1:0;
  $('manual-surface').dataset.state=ended?'closed':manualBusy||['starting','busy'].includes(session?.status)?'busy':manualImageError?'unavailable':!manualFrameLoaded?'loading':controls?'unavailable':'ready';
  $('manual-frame-status').textContent=ended?'Saved screenshot — session '+session.status+'. This image is not a live browser.':manualImageError|| (manualBusy||session?.status==='busy'?'Browser command in progress. Actions are locked until its outcome is known.':!manualFrameLoaded?'Loading screenshot…':elsewhere?'Saved screenshot from this site; another site has your active session.':'Remote browser ready. Click the image to interact.');
  for(const id of ['manual-scroll-up','manual-scroll-down','manual-press','manual-key','manual-send-text'])$(id).disabled=controls;
  $('manual-text').disabled=authExpired||!ready;
  $('manual-refresh').disabled=pending||manualUncertain||authExpired||!ready;
  $('manual-page-url').textContent=f?.page_url||'Remote browser';
  $('manual-session-facts').textContent=session?[session.task_name||session.task,session.condition,session.controller==='agent'?'Agent controlled · BrowserGym':'Human controlled · BrowserGym'].filter(Boolean).join(' · '):'';
  if(session?.site_revision&&!manualBusy&&!manualLoading)$('manual-status').textContent+=' · Site version '+session.site_revision.slice(0,12);
  $('manual-reference-goal').textContent=session?.reference_goal||'Resolved when the session starts.';
}
function renderRemoteAsk(session){
  const active=session?.controller==='agent',ask=session?.asks?.at(-1);
  const canAsk=manualConfig?.ask_enabled&&session?.status==='ready'&&!session?.environment_finished;
  $('remote-question').disabled=authExpired||remoteSending||!(canAsk||active);
  $('remote-send').disabled=$('remote-question').disabled;
  $('remote-send').textContent=active?'Interrupt and send':'Send';
  $('remote-stop').disabled=authExpired||remoteSending||!active;
  $('remote-agent-status').textContent=active?'Agent is using this browser. You can interrupt with a new message or Stop.':!session?'Open a remote session to ask the agent.':!manualConfig?.ask_enabled?'Remote inference is not configured.':session.environment_finished?'This environment ended. Open a new session to continue.':session.status==='ready'?'You control this browser. Ask requests are recorded and are not automatically graded.':'This session is not ready for Ask.';
  const content=JSON.stringify([session?.id,session?.asks]);
  if(content!==remoteRendered){remoteRendered=content;const log=$('remote-conversation');log.replaceChildren();
    for(const turn of session?.asks||[]){
      const user=node('div',undefined,'message user');user.append(node('strong','You'),document.createTextNode(turn.goal));log.append(user);
      for(const step of turn.steps||[]){if(!step.action||/^\s*send_msg_to_user\s*\(/.test(step.action))continue;const entry=node('details',undefined,'tool-activity');entry.append(node('summary',step.action+(step.executed===true?' · Applied':step.error?' · Failed':' · Recorded')));entry.append(node('pre',JSON.stringify(step,null,2)));log.append(entry);}
      if(turn.answer||turn.error||!['running','stopping'].includes(turn.status)){const response=node('div',undefined,'message assistant');response.append(node('strong','Daylight'),document.createTextNode(turn.answer||turn.error||'Request '+turn.status+'. Review the current page.'));log.append(response);}
      for(const alert of turn.alerts||[])log.append(node('p',alert,'notice'));
      log.append(node('small',turn.status+' · '+(typeof turn.reported_cost_usd==='number'?'Reported $'+turn.reported_cost_usd.toFixed(5):'Cost not reported')+(turn.unknown_cost_attempts?' · '+turn.unknown_cost_attempts+' unknown-cost attempts':'')));
    }log.scrollTop=log.scrollHeight;
  }
  clearTimeout(remotePollTimer);
  if(active&&!document.hidden&&!remotePollFailed)remotePollTimer=setTimeout(()=>pollRemoteSession(session.id),1500);
}
async function pollRemoteSession(id){
  try{const result=await api('/api/manual/sessions/'+id);rememberManual(result);manualUncertain=['starting','busy'].includes(result.status);}
  catch(error){remotePollFailed=true;manualError=error.message+' Use Refresh session status to reconnect.';}
  updateManualViews();
}
async function remoteInterrupt(session){
  const ask=session?.asks?.at(-1);if(!ask||session.controller!=='agent')return session;
  await api('/api/manual/sessions/'+session.id+'/interrupt',{ask_id:ask.id});
  for(let i=0;i<70;i++){
    const current=await api('/api/manual/sessions/'+session.id);rememberManual(current);updateManualViews();
    if(current.controller!=='agent')return current;
    await wait(500);
  }
  throw Error('Control handover is still pending. Check sessions before another request.');
}
$('remote-ask-form').onsubmit=async event=>{
  event.preventDefault();const goal=$('remote-question').value.trim(),session=manualCurrent();
  if(!goal||!session||remoteSending||authExpired)return;
  remoteSending=true;renderRemoteAsk(session);
  try{
    const current=await remoteInterrupt(session);
    if(current.status!=='ready')throw Error('Browser is not ready for a new request');
    const result=await api('/api/manual/sessions/'+session.id+'/ask',{request_id:crypto.randomUUID(),goal});
    $('remote-question').value='';rememberManual(result);manualUncertain=false;
  }catch(error){manualError=error.message+' No request was automatically retried.';}
  finally{remoteSending=false;updateManualViews();}
};
$('remote-stop').onclick=async()=>{
  if(remoteSending)return;remoteSending=true;
  try{await remoteInterrupt(manualCurrent());}catch(error){manualError=error.message;}
  finally{remoteSending=false;updateManualViews();}
};
bindChatEnter($('remote-question'),$('remote-send'));
let manualLoading=null;
async function loadManual(){
  if(manualBusy||authExpired)return;if(manualLoading)return manualLoading;
  manualLoading=(async()=>{
    try{const [settings,result]=await Promise.all([api('/api/manual/config'),api('/api/manual/sessions')]);manualConfig=settings;manualSessions=(result.sessions||[]).sort((a,b)=>(Date.parse(b.created_at)||0)-(Date.parse(a.created_at)||0));manualUncertain=manualSessions.some(session=>['starting','busy'].includes(session.status));manualError='';remotePollFailed=false;manualCheckedAt=Date.now();}
    catch(error){if(error.status===404){manualConfig={enabled:false,sites:[]};manualError='';}else{manualError=error.message;manualUncertain=true;}}
    finally{manualLoading=null;updateManualViews();}
  })();renderManual();return manualLoading;
}
async function manualCommand(operation,action,targetSession=null){
  if(manualBusy||manualLoading||manualUncertain||authExpired)return;
  if(targetSession&&(operation!=='close'||manualOwnerLive()?.id!==targetSession.id))return;
  const session=targetSession||manualCurrent();
  if(operation==='open'){if(manualOwnerLive()||!manualConfig?.enabled||!$('manual-task').value)return;}
  else if(session?.status!=='ready'||operation==='action'&&!manualFrameLoaded)return;
  const task=$('manual-task').value,request_id=crypto.randomUUID();manualBusy=true;manualError='';updateManualViews();
  try{
    const result=await api(operation==='open'?'/api/manual/sessions':'/api/manual/sessions/'+encodeURIComponent(session.id)+'/'+operation,
      operation==='open'?{task}:{request_id,...(operation==='action'?{frame_id:session.frame.id,action}:{})});
    rememberManual(result);if(result.last_error||result.error)manualError=String(result.last_error||result.error);
  }catch(error){manualError=error.message+' No command will be retried. Use Check sessions to recover its recorded state.';manualUncertain=true;}
  finally{manualBusy=false;updateManualViews();}
}
$('manual-task').onchange=()=>manualChoices.set(siteID,$('manual-task').value);
$('manual-open').onclick=()=>manualCommand('open');$('manual-close').onclick=()=>manualCommand('close');$('manual-refresh').onclick=()=>manualCommand('observe');$('manual-check').onclick=()=>loadManual();
$('manual-other').onclick=()=>{const session=manualOwnerLive();if(session)selectSite(session.site_id);};
$('manual-close-other').onclick=()=>manualCommand('close',undefined,manualOwnerLive());
$('manual-frame').onload=()=>{manualFrameLoaded=true;manualImageError='';renderManual();};
$('manual-frame').onerror=()=>{manualFrameLoaded=false;manualImageError='The remote image could not be loaded. Use Refresh screenshot while the session is ready.';manualError=manualImageError;renderManual();};
$('manual-surface').onclick=event=>{
  if($('manual-surface').getAttribute('aria-disabled')==='true')return;
  const bounds=$('manual-frame').getBoundingClientRect(),f=manualCurrent()?.frame;if(!f||!bounds.width||!bounds.height)return;
  const x=Math.floor((event.clientX-bounds.left)*f.width/bounds.width),y=Math.floor((event.clientY-bounds.top)*f.height/bounds.height);
  if(x<0||y<0||x>=f.width||y>=f.height)return;$('manual-surface').focus({preventScroll:true});manualCommand('action',{type:'click',x,y});
};
const manualKeys=new Set(['Tab','Enter','Escape','Backspace','ArrowUp','ArrowDown','ArrowLeft','ArrowRight']);
$('manual-surface').onkeydown=event=>{
  if(event.shiftKey||event.ctrlKey||event.altKey||event.metaKey||!manualKeys.has(event.key))return;
  event.preventDefault();if(event.repeat||event.isComposing||$('manual-surface').getAttribute('aria-disabled')==='true')return;
  manualCommand('action',{type:'press',key:event.key});
};
$('manual-leave').onclick=()=>$('manual-text').focus();
$('manual-scroll-up').onclick=()=>manualCommand('action',{type:'scroll',dx:0,dy:-500});$('manual-scroll-down').onclick=()=>manualCommand('action',{type:'scroll',dx:0,dy:500});
$('manual-press').onclick=()=>manualCommand('action',{type:'press',key:$('manual-key').value});
$('manual-text-form').onsubmit=async event=>{event.preventDefault();const field=$('manual-text'),text=field.value;if(!text||$('manual-send-text').disabled)return;field.value='';await manualCommand('action',{type:'type',text});};
function renderHistoryState(){
  const partial=historyMore||!historyLoaded;
  for(const prefix of ['global','site']){
    const status=$(prefix+'-history-status'),button=$(prefix+'-history-more');
    status.textContent=historyError?'History could not be loaded: '+historyError:historyLoading?'Loading history…':partial?'Showing loaded history only. Filters and conversations cover loaded turns; load more for additional activity.':'All browser-side history loaded.';
    button.hidden=historyLoaded&&!historyMore&&!historyError;button.disabled=!!historyLoading||authExpired;
    button.textContent=historyError?'Retry history':historyLoaded?'Load more history':'Load history';
    if(libraryEnabled)status.textContent+=' Saved library: '+(libraryError?'unavailable — '+libraryError:libraryLoading?'loading…':libraryMore?'more saved runs available.':libraryLoaded?'all published runs loaded.':'not loaded.');
    const savedButton=$(prefix+'-library-more');savedButton.hidden=!libraryEnabled;savedButton.disabled=libraryLoading||authExpired;savedButton.textContent=libraryError?'Retry saved library':libraryMore?'Load more saved runs':libraryLoaded?'Refresh saved library':'Load saved library';
  }
}
function renderHistory(){
  if(view==='research')renderTasks();if(globalPage&&view!=='review')renderGlobal();renderHistoryState();
}
async function loadHistory({more=false,reset=false}={}){
  if(authExpired)return;if(historyLoading)return historyLoading;
  reset ||= historyStale;
  if(historyLoaded&&!reset&&!more)return;
  if(more&&!historyMore&&!reset)return;
  const cursor=reset?null:historyCursor;
  historyError='';
  historyLoading=(async()=>{
    try{
      const page=await api('/api/traces?limit=25'+(cursor?'&cursor='+encodeURIComponent(cursor):''));
      if(!Array.isArray(page.traces)||typeof page.has_more!=='boolean')throw Error('Invalid history response.');
      if(page.has_more&&(!page.cursor||page.cursor===cursor||(!reset&&historyCursors.has(page.cursor))))throw Error('Trace history pagination did not advance.');
      const merged=new Map((reset?[]:demoRows).map(row=>[row.id,row]));for(const row of page.traces)merged.set(row.id,row);
      demoRows=[...merged.values()];if(reset)historyCursors.clear();if(page.cursor)historyCursors.add(page.cursor);
      historyCursor=page.cursor;historyMore=page.has_more;historyLoaded=true;historyStale=false;lastDemoRefresh=Date.now();
    }catch(error){historyError=error.message;}
    finally{historyLoading=null;renderHistory();renderSites();}
  })();renderHistoryState();return historyLoading;
}
for(const prefix of ['global','site'])$(prefix+'-history-more').onclick=()=>loadHistory({more:historyLoaded});
async function loadLibrary({more=false,reset=false}={}){
  if(authExpired||libraryLoading||!libraryEnabled||(libraryAttempted&&!more&&!reset))return;
  libraryLoading=true;libraryAttempted=true;libraryError='';if(reset){libraryCursor=null;libraryCursors.clear();}renderHistoryState();
  try{
    const page=await api('/api/library/sessions'+(libraryCursor?'?cursor='+encodeURIComponent(libraryCursor):''));
    if(!Array.isArray(page.sessions)||typeof page.has_more!=='boolean')throw Error('Invalid saved library response');
    if(page.has_more&&(!page.cursor||libraryCursors.has(page.cursor)))throw Error('Saved library pagination did not advance');
    const merged=new Map((reset?[]:libraryRows).map(row=>[row.id,row]));for(const row of page.sessions)merged.set(row.id,row);libraryRows=[...merged.values()];
    libraryLoaded=true;libraryMore=page.has_more;libraryCursor=page.cursor;if(page.cursor)libraryCursors.add(page.cursor);
  }catch(error){if(error.status===404)libraryEnabled=false;else libraryError=error.message;}
  finally{libraryLoading=false;renderHistory();renderSites();}
}
for(const prefix of ['global','site'])$(prefix+'-library-more').onclick=()=>loadLibrary({more:libraryMore,reset:!libraryMore});

async function refresh(forceTraces=false){
  if(forceTraces)historyStale=true;
  if(authExpired||document.hidden)return;if(refreshing){refreshRequested=true;refreshTracesPending ||= forceTraces;return;}refreshing=true;
  // The registry can display sites independently of slow jobs/history reads.
  const work=[(async()=>{try{
    const first=!config,oldSite=siteID;config=await api('/api/harness/config');buildSites();
    $('worker-status').textContent=config.worker?.online?'● Worker online · '+(config.worker.mode==='live'?'live agent':'rehearsal'):'○ Worker offline';
    if(first||oldSite!==siteID)render();else{renderSites();if(view==='research')renderTasks();syncControls();}
  }catch(error){notice(error.message);}})()];
  if(historyWanted()||jobRows.some(j=>activeStatuses.has(j.status)))work.push((async()=>{try{
    jobRows=(await api('/api/harness/jobs')).jobs||[];
    if(currentRun?.source==='harness')currentRun=recordForKey(currentRun.key)||currentRun;
    renderHistory();if(view==='review'&&currentRun?.source==='harness')renderReview();
  }catch(error){notice(error.message);}})());
  if(historyWanted()){loadHistory();loadLibrary();}
  try{await Promise.allSettled(work);
    if(pendingTask){const latest=tasks.find(t=>t.id===pendingTask.id);if(latest&&latest.revision===pendingTask.revision)pendingTask=latest;}
    syncControls();
  }finally{refreshing=false;clearTimeout(pollTimer);if(!authExpired){if(refreshRequested){const force=refreshTracesPending;refreshRequested=false;refreshTracesPending=false;pollTimer=setTimeout(()=>refresh(force),0);}else pollTimer=setTimeout(()=>refresh(),jobRows.some(j=>activeStatuses.has(j.status))?4000:60000);}}
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
async function askAgent(question,continuationOf=null){
  const turn=new InterruptibleTurn(api);activeTurn=turn;
  askBusy=true;syncControls();renderConversation();$('chat-status').textContent='';setWorking('Looking at the page…');
  let id,cost=0,unknown=0,pendingTool=null,actionError=null;const before=structuredClone(window.demoWorld.state),priorActivity=JSON.stringify({last_trace:lastTrace,interrupted:!!continuationOf,steps:activity});activity=[];
  const spend=()=> 'Reported model cost $'+cost.toFixed(4)+(unknown?' · '+unknown+' request(s) with unknown cost':'');
  try{
    await turn.wait(currentPage());({id,conversation_id:conversationID}=await turn.start({mode:'assist',goal:question,interaction_kind:'ask',site_id:'campus',...(conversationID?{conversation_id:conversationID}:{}),...(continuationOf?{continuation_of:continuationOf}:{})}));lastTrace=id;turn.check();
    for(let i=0;i<12;i++){
      setWorking(i?'Choosing the next action…':'Looking at the page…');if(i)await turn.wait(wait(750));const captured=snapshot(await turn.wait(currentPage()));turn.check();unknown++;
      const result=await turn.wait(api('/api/step',{id,observation:captured.observation,conversation,activity:priorActivity}));turn.check();
      if(result.status==='interrupted')throw new TurnInterrupted('This run was interrupted');
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
      turn.check();if(saved.status==='interrupted')throw new TurnInterrupted('This run was interrupted');
      if(saved.status!=='ready'){
        if(!['complete','step_limit'].includes(saved.status))throw Error('The server stopped this turn ('+saved.status+').');
        const answer=saved.status==='step_limit'?'The request reached its step limit. Review the current page and original record.':boundary?'The demo recorded a reservation and stopped at its one-reservation limit. Review it under My reservations.':result.answer||action.message||'The request finished. Review the recorded evidence.';
        messages.push({role:'assistant',text:answer,trace:id});conversation.push({role:'user',content:question},{role:'assistant',content:answer});conversation=conversation.slice(-8);$('chat-status').textContent=spend();return;
      }
    }
    throw Error('The client step limit was reached without a terminal receipt.');
  }catch(error){
    if(error instanceof TurnInterrupted){conversation.push({role:'user',content:question});conversation=conversation.slice(-8);}
    else{turn.failure=error;updateTool(pendingTool,actionError?'failed':'unrecorded',(actionError? actionError+' ':'')+'Receipt not saved: '+error.message);messages.push({role:'assistant',text:'The request stopped: '+error.message+' Earlier page changes may already have happened.',trace:id});$('chat-status').textContent=spend();notice(error.message);}
  }
  finally{setWorking('');activeTurn=null;askBusy=interrupting;renderConversation();syncControls();turn.finish();refresh(true);}
}
$('ask-form').onsubmit=async event=>{
  event.preventDefault();const question=$('question').value.trim();if(!question||interrupting||authExpired||!modelConfig?.live_available||siteID!=='campus')return;
  const previous=activeTurn;draft='';$('question').value='';
  const note=previous?interruptionNotice('Interrupting the current run…'):null;
  if(note)messages.push({role:'tool',element:note});messages.push({role:'user',text:question});renderConversation();
  let continuationOf=null;
  if(previous){
    interrupting=true;syncControls();
    try{continuationOf=await previous.interrupt();note.textContent=(previous.interruptStatus==='interrupted'?'Previous run interrupted. ':'')+'Your new message starts from the current page.';}
    catch(error){note.textContent='Stopped locally, but the new message was not started: '+error.message;notice(note.textContent);return;}
    finally{interrupting=false;askBusy=false;syncControls();}
  }
  await askAgent(question,continuationOf);
};
bindChatEnter($('question'),$('send-question'));
$('question').oninput=()=>{draft=$('question').value;};$('site-search').oninput=renderSites;$('replay-kind').onchange=renderTasks;
$('explore-tab').onclick=()=>setView('explore');$('research-tab').onclick=()=>setView('research');$('sidebar-tasks').onclick=()=>setView('research');$('remote-tasks').onclick=()=>setView('research');
for(const id of ['all-replays-link','global-library-link'])$(id).onclick=openGlobal;
for(const id of ['global-search','global-collection','global-site','global-kind','global-grade'])$(id).addEventListener(id==='global-search'?'input':'change',renderGlobal);
$('clear-filters').onclick=()=>{for(const id of ['global-collection','global-site','global-kind','global-grade'])$(id).value='all';$('global-search').value='';renderGlobal();};
$('toggle-agent').onclick=()=>setAgentVisible(!agentVisible);
$('reset-page').onclick=()=>{if(askBusy||!frame)return;window.demoWorld=new World(fixture);pendingDocument=frame.contentDocument;frame.src='/world/'+crypto.randomUUID()+'/booking';messages=[];conversation=[];conversationID=null;draft='';activity=[];lastTrace=null;setWorking('');$('chat-status').textContent='';renderConversation();};
$('back-to-research').onclick=()=>{view=globalPage?'global':'research';currentRun=null;reviewVersion++;render();syncURL();};
async function readRoute(){
  const route=location.href,params=new URLSearchParams(location.search);globalPage=location.pathname==='/workspace/replays';
  if(siteFor(params.get('site')))siteID=params.get('site');
  const key=params.get('run');currentRun=recordForKey(key);view=currentRun?'review':globalPage?'global':params.get('view')==='research'?'research':'explore';render();
  if(key&&!currentRun&&/^l:[A-Za-z0-9_-]{1,160}$/.test(key)){
    try{const value=await api('/api/library/sessions/'+encodeURIComponent(key.slice(2)));if(location.href!==route)return;const {messages,...summary}=value;libraryRows=[...libraryRows.filter(row=>row.id!==value.id),{...summary,...summary.library_metadata}];currentRun=recordForKey(key);if(currentRun)view='review';render();}catch(error){if(location.href===route)notice('The saved trace could not be loaded: '+error.message);}
  }
  if(key&&!currentRun&&/^[dhm]:[a-f0-9-]{36}$/.test(key)){
    try{
      const kind=key[0],id=key.slice(2),row=await api(kind==='d'?'/api/traces/'+id:kind==='h'?'/api/harness/jobs/'+id:'/api/manual/sessions/'+id);
      if(location.href!==route)return;
      if(kind==='d')demoRows=[...demoRows.filter(item=>item.id!==id),{...row,steps:row.steps?.length??0}];
      else if(kind==='h')jobRows=[...jobRows.filter(item=>item.id!==id),row];else rememberManual(row);
      currentRun=recordForKey(key);if(currentRun)view='review';render();
    }catch(error){if(location.href===route)notice('The requested trace could not be loaded: '+error.message);}
  }
  if(historyWanted()){loadHistory();loadLibrary();refresh();loadManual();}
  if(currentRun?.source==='demo')loadBrowserTrace(currentRun);
}
document.addEventListener('visibilitychange',()=>{clearTimeout(pollTimer);if(!document.hidden){refresh();loadManual();}else clearTimeout(remotePollTimer);});
window.addEventListener('popstate',readRoute);window.addEventListener('pagehide',()=>{clearTimeout(pollTimer);clearTimeout(remotePollTimer);});
window.addEventListener('message',event=>{if(event.origin!==location.origin||event.source!==$('run-viewer').contentWindow||event.data?.type!=='harness:size')return;const height=Number(event.data.height);if(Number.isFinite(height))$('run-viewer').style.height=Math.min(8000,Math.max(650,height))+'px';});
window.addEventListener('message',event=>{const frame=$('shared-trace-viewer');if(event.origin!==location.origin||event.source!==frame.contentWindow||event.data?.type!=='trace-viewer:size')return;const height=Number(event.data.height);if(Number.isFinite(height))frame.style.height=Math.min(14000,Math.max(800,height))+'px';});
// Render the workspace immediately; network dependencies settle independently.
buildSites();readRoute();
api('/assets/fixture.json').then(value=>{fixture=value;window.demoWorld=new World(fixture);render();}).catch(error=>notice(error.message));
api('/api/config').then(value=>{modelConfig=value;syncControls();if(!value.live_available)$('chat-status').textContent='OpenRouter is not configured for this deployment.';}).catch(error=>notice(error.message));
refresh();loadManual();
