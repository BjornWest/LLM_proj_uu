// Site-first design prototype. All records, grades and assistant replies are local samples.
import {World} from '/assets/world.js';
import {waitForDocument} from '/assets/observation.js';
const $ = id => document.getElementById(id);
const fixture = await (await fetch('/assets/fixture.json')).json();
window.demoWorld = new World(fixture);
const sites = [
  {id:'campus',name:'Campus',collection:'Campus demos',icon:'C',description:'Study rooms, campus supplies and account preferences.',address:'campus.demo / study rooms',tag:'Interactive campus demo',src:'/world/preview-campus/booking',image:'campus',suggestions:['Find a room for three people','What can I do on this page?']},
  {id:'fieldnotes',name:'Fieldnotes',collection:'Sample sites',icon:'F',description:'A small bookshop for trying browsing, search and comparison.',address:'fieldnotes.demo / books',tag:'Fictional sample website',src:'/preview/site?site=sample-bookshop&workspace=1',image:'sample-bookshop',suggestions:['Find a paperback under 200 SEK','Show me the second book']},
];
const tasks = [
  {id:'campus-reserve',site:'campus',name:'Reserve a room for three',description:'Make one reservation in Ångström, with the requested time and group size.',goal:fixture.examples.booking.goal,requirements:['Room in Ångström','Tuesday · 30 minutes · 3 people','Exactly one reservation'],steps:['Read the room calendar','Set building and group size','Inspect the selected room','Review the reservation']},
  {id:'campus-availability',site:'campus',name:'Check availability without booking',description:'Find a suitable room while leaving the reservation list unchanged.',goal:'Find an available room in Ångström on Tuesday for three people. Report its time and capacity. Do not make a reservation.',requirements:['Suitable room found','Time and capacity reported','No reservation made'],steps:['Read available rooms','Filter for three people','Inspect a matching room','Report the available option']},
  {id:'campus-compare',site:'campus',name:'Compare three study options',description:'Collect enough details to compare three rooms before choosing.',goal:'Compare three study rooms by building, capacity and available time. Do not book any room.',requirements:['First room described','Second room described','Third room described'],steps:['Read the room calendar','Inspect the first room','Inspect the second room','Summarize the recorded options']},
  {id:'fieldnotes-find',site:'fieldnotes',name:'Find a paperback under 200 SEK',description:'Find the requested title and check its format and listed price.',goal:'Find A Field Guide to Noticing in paperback for under 200 SEK. Report the listed price. Do not buy anything.',requirements:['Requested title found','Paperback format','Price below 200 SEK'],steps:['Browse the bookshop','Search for the title','Inspect the paperback','Report its listed price']},
  {id:'fieldnotes-second',site:'fieldnotes',name:'Inspect The Art of Wandering',description:'Open a specific book and report its price without making a purchase.',goal:'Find The Art of Wandering and report its format and price. Do not place an order.',requirements:['Correct book inspected','Format and price reported','No purchase made'],steps:['Browse the bookshop','Inspect the second title','Read format and price','Summarize the book details']},
  {id:'fieldnotes-compare',site:'fieldnotes',name:'Compare three paperbacks',description:'Compare the three sample books by title and price.',goal:'Compare the three displayed paperbacks by title and listed price. Do not buy anything.',requirements:['First title and price','Second title and price','Third title and price'],steps:['Browse the shelves','Inspect the first book','Inspect the second book','Summarize the recorded comparison']},
];
const gradeNames = {success:'Succeeded',failed:'Failed',partial:'Partial',ungraded:'Not graded',unknown:'Unknown',running:'In progress'};
const sampleTime = Date.now() - 3600000;
function taskRecord(id,taskID,grade,minutes) {
  const task=tasks.find(t=>t.id===taskID);
  return {id,site:task.site,kind:'task',task:task.id,title:task.name,goal:task.goal,grade,status:grade==='unknown'?'interrupted':'finished',at:sampleTime-minutes*60000,
    requirements:task.requirements.map((label,i)=>({label,result:grade==='unknown'?null:grade==='success'?true:grade==='partial'?i<2:i!==1})),steps:task.steps,availableSteps:4,
    gradeNote:grade==='partial'?'Sample verifier recorded a partial result: two of three comparison items were supplied.':grade==='failed'?'The sample verifier recorded a failed requirement. The run finishing does not make it a success.':grade==='unknown'?'This sample run was interrupted before grading. No outcome was recorded.':'Sample verifier recorded all task requirements as met.'};
}
function askRecord(id,site,title,minutes) {return {id,site,kind:'ask',title,goal:title,grade:'ungraded',status:'finished',at:sampleTime-minutes*60000,requirements:[],steps:['Read the current page','Inspect relevant controls','Read the displayed details','Answer the user'],availableSteps:4,gradeNote:'No task verifier was attached to this Ask conversation.'};}
const seeded = [taskRecord('sample-campus-success','campus-reserve','success',5),askRecord('sample-campus-ask','campus','Which rooms fit three people?',24),taskRecord('sample-campus-partial','campus-compare','partial',55),taskRecord('sample-campus-failed','campus-reserve','failed',90),taskRecord('sample-campus-unknown','campus-availability','unknown',135),
  taskRecord('sample-books-success','fieldnotes-find','success',12),askRecord('sample-books-ask','fieldnotes','What does the second book cost?',35),taskRecord('sample-books-partial','fieldnotes-compare','partial',65),taskRecord('sample-books-failed','fieldnotes-second','failed',100)];
let added=[];try{added=JSON.parse(sessionStorage.getItem('daylight-site-preview-runs')||'[]');if(!Array.isArray(added))added=[];}catch{}
const records=()=>[...added,...seeded].sort((a,b)=>b.at-a.at);
const state=new Map(sites.map(site=>[site.id,{messages:[],draft:''}]));
const frames=new Map();
let siteID='campus',view='explore',globalPage=false,currentRun=null,currentStep=0,replayTimer=null,taskTimer=null,askBusy=false,pendingTask=null,agentVisible=true;
const siteFor = id => sites.find(s=>s.id===id);
const persist=()=>{try{sessionStorage.setItem('daylight-site-preview-runs',JSON.stringify(added));}catch{}};
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function node(tag,text,className) {const el=document.createElement(tag);if(text!==undefined)el.textContent=text;if(className)el.className=className;return el;}
function gradeBadge(grade) {return node('span',gradeNames[grade]||'Unknown','grade '+(gradeNames[grade]?grade:'unknown'));}
function dateLabel(at) {return new Date(at).toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});}
function saveDraft() {state.get(siteID).draft=$('question').value;}
function pathFor() {return globalPage?'/workspace/replays'+(currentRun&&view==='review'?'?run='+encodeURIComponent(currentRun.id):''):'/workspace?site='+siteID+(view!=='explore'?'&view='+view:'')+(view==='review'&&currentRun?'&run='+encodeURIComponent(currentRun.id):'');}
function syncURL(replace=false) {history[replace?'replaceState':'pushState'](null,'',pathFor());}
function stopReplay() {clearInterval(replayTimer);replayTimer=null;$('review-play').textContent='Play replay';}
function renderSites() {
  const query=$('site-search').value.trim().toLowerCase();
  $('site-folders').replaceChildren();
  for(const collection of [...new Set(sites.map(s=>s.collection))]) {
    const matching=sites.filter(s=>s.collection===collection&&[s.name,s.description,collection].join(' ').toLowerCase().includes(query));
    if(!matching.length)continue;
    const details=node('details',undefined,'site-folder');details.open=true;
    const summary=node('summary',collection);summary.append(node('span',String(matching.length)));details.append(summary);
    for(const site of matching) {
      const button=node('button',undefined,'site-choice');button.type='button';button.dataset.site=site.id;button.disabled=askBusy;
      button.setAttribute('aria-current',String(!globalPage&&site.id===siteID));
      const text=node('span');text.append(node('strong',site.name),node('small',site.id==='campus'?'Rooms · supplies · account':'Books · browsing'));
      button.append(node('span',site.icon,'site-icon'+(site.id==='fieldnotes'?' books':'')),text);button.onclick=()=>selectSite(site.id);details.append(button);
    }
    $('site-folders').append(details);
  }
  $('sites-empty').hidden=!!$('site-folders').children.length;
  for(const id of ['all-replays-link','global-library-link']) {if(globalPage)$(id).setAttribute('aria-current','page');else $(id).removeAttribute('aria-current');}
}
function ensureFrame(id) {
  if(frames.has(id))return frames.get(id);
  const frame=document.createElement('iframe');frame.title=siteFor(id).name+' — interactive website';frame.src=siteFor(id).src;frame.dataset.site=id;
  frame.addEventListener('load',()=>{if(siteID===id)updateAddress();});
  frames.set(id,frame);$('site-frames').append(frame);return frame;
}
function updateAddress() {
  const frame=frames.get(siteID);let suffix='';
  try {if(siteID==='campus'){const area=frame?.contentWindow.location.pathname.split('/').at(-1);suffix={booking:'study rooms',shop:'shop',preferences:'account'}[area]||'study rooms';}}catch{}
  $('site-address').textContent=siteID==='campus'?'campus.demo / '+suffix:'fieldnotes.demo / books';
}
function renderConversation() {
  const messages=state.get(siteID).messages;
  $('conversation').replaceChildren();
  if(!messages.length) {
    const welcome=node('div',undefined,'chat-welcome');welcome.append(node('span','✳'),node('h3','Explore first.\nAsk whenever you need.'),node('p','Click around the site yourself, or ask me to find something. Your tasks and past runs are one tab away.'));$('conversation').append(welcome);
  } else for(const message of messages) {
    const div=node('div',undefined,'message '+message.role);div.append(node('strong',message.role==='user'?'You':'Daylight'),document.createTextNode(message.text));
    if(message.runID){const button=node('button','View this Ask replay ↗','text-button record-link');button.onclick=()=>openRun(records().find(r=>r.id===message.runID),false);div.append(button);}
    $('conversation').append(div);
  }
  $('question').value=state.get(siteID).draft;
  $('conversation').scrollTop=$('conversation').scrollHeight;
  $('suggestions').replaceChildren(...siteFor(siteID).suggestions.map(text=>{const button=node('button',text);button.type='button';button.disabled=askBusy;button.onclick=()=>{$('question').value=text;state.get(siteID).draft=text;$('question').focus();};return button;}));
}
function renderTasks() {
  $('task-list-heading').textContent='Tasks for '+siteFor(siteID).name;
  $('task-cards').replaceChildren(...tasks.filter(t=>t.site===siteID).map((task,i)=>{
    const card=node('article',undefined,'task-card');card.append(node('span','TASK '+String(i+1).padStart(2,'0'),'task-index'),node('h3',task.name),node('p',task.description));
    const button=node('button','View task →');button.type='button';button.dataset.task=task.id;button.onclick=()=>showTask(task);card.append(button);return card;
  }));
  $('replay-site-name').textContent=siteFor(siteID).name;
  const kind=$('replay-kind').value,rows=records().filter(r=>r.site===siteID&&(kind==='all'||r.kind===kind));
  $('replay-rows').replaceChildren(...rows.map(r=>recordRow(r,false)));$('replay-empty').hidden=!!rows.length;
}
function recordRow(record,all) {
  const row=node('tr');row.dataset.run=record.id;row.dataset.site=record.site;row.dataset.kind=record.kind;
  const titleCell=node('td'),title=node('button',undefined,'run-title');title.type='button';title.append(node('span',record.kind==='task'?'Task':'Ask','run-kind '+record.kind),document.createTextNode(record.title));title.onclick=()=>openRun(record,all);
  titleCell.append(title,node('span',(record.status==='interrupted'?'Interrupted · ':'')+'Sample recording · '+(record.kind==='task'?'Fixed goal':'Free-form request'),'run-meta'));row.append(titleCell);
  if(all){const cell=node('td',siteFor(record.site)?.name||'Unknown site','site-cell');cell.append(node('small',siteFor(record.site)?.collection||''));row.append(cell);}
  const grade=node('td');grade.append(gradeBadge(record.grade));row.append(grade,node('td',dateLabel(record.at),'when'));
  const action=node('td'),button=node('button',record.grade==='running'?'Watch →':'Replay ↗','replay-action');button.type='button';button.setAttribute('aria-label','Replay '+(record.kind==='task'?'task: ':'Ask: ')+record.title);button.onclick=()=>openRun(record,all);action.append(button);row.append(action);return row;
}
function renderGlobal() {
  const query=$('global-search').value.trim().toLowerCase(),collection=$('global-collection').value,site=$('global-site').value,kind=$('global-kind').value,grade=$('global-grade').value;
  const all=records(),matches=all.filter(r=>(site==='all'||r.site===site)&&(kind==='all'||r.kind===kind)&&(grade==='all'||r.grade===grade)&&(collection==='all'||siteFor(r.site)?.collection===collection)&&(!query||[r.title,r.goal,r.id,siteFor(r.site)?.name].join(' ').toLowerCase().includes(query)));
  $('global-rows').replaceChildren(...matches.map(r=>recordRow(r,true)));$('global-count').textContent=matches.length+' of '+all.length+' recordings';$('global-empty').hidden=!!matches.length;
}
function render() {
  const site=siteFor(siteID);
  document.querySelector('.site-heading').hidden=globalPage;document.querySelector('.site-tabs').hidden=globalPage;
  $('site-breadcrumb').textContent=site.collection+' / '+site.name;$('site-name').textContent=site.name;$('site-description').textContent=site.description;$('site-label').textContent=site.tag;
  $('explore-view').hidden=globalPage||view!=='explore';$('research-view').hidden=globalPage||view!=='research';$('global-view').hidden=!globalPage||view==='review';$('review-view').hidden=view!=='review';
  $('explore-tab').setAttribute('aria-pressed',String(view==='explore'));$('research-tab').setAttribute('aria-pressed',String(view!=='explore'));
  $('replay-count').textContent=String(records().filter(r=>r.site===siteID).length);
  $('tab-note').textContent=view==='explore'?'Your browser, with an agent beside it.':'Tasks and recorded attempts for this site.';
  $('agent-site').textContent=site.name+' · current page';
  renderSites();
  if(!globalPage&&view==='explore'){ensureFrame(siteID);for(const [id,frame] of frames)frame.hidden=id!==siteID;updateAddress();renderConversation();}
  if(view==='research')renderTasks();
  if(globalPage&&view!=='review')renderGlobal();
  if(view==='review'&&currentRun)renderReview();
}
function selectSite(id) {if(askBusy)return;saveDraft();stopReplay();siteID=id;globalPage=false;view='explore';currentRun=null;$('chat-status').textContent='';render();syncURL();}
function setView(next) {saveDraft();stopReplay();globalPage=false;view=next;currentRun=null;render();syncURL();}
function openGlobal(event) {event?.preventDefault();saveDraft();stopReplay();globalPage=true;view='global';currentRun=null;render();syncURL();}
function showTask(task) {
  pendingTask=task;$('dialog-site').textContent=siteFor(task.site).name+' / Task';$('dialog-task-name').textContent=task.name;$('dialog-goal').textContent=task.goal;
  $('dialog-requirements').replaceChildren(...task.requirements.map(label=>node('li',label)));
  $('try-task').disabled=!!taskTimer;$('try-task').textContent=taskTimer?'A sample task is running…':'Try this task →';$('task-dialog').showModal();
}
function openRun(record,fromGlobal=globalPage) {if(!record)return;saveDraft();stopReplay();currentRun=record;currentStep=0;globalPage=fromGlobal;if(!fromGlobal)siteID=record.site;view='review';render();syncURL();}
function renderReview() {
  const record=currentRun,site=siteFor(record.site),running=record.grade==='running';
  $('back-to-research').textContent=globalPage?'← All traces & replays':'← Tasks & replays';
  $('recording-status').textContent=running?'Scripted sample running · view only':'Sample recording · view only';
  $('review-kind').textContent=(record.kind==='task'?'Task attempt':'Ask the agent')+' · '+site.name;
  $('review-title').textContent=record.title;$('review-grade').replaceChildren(gradeBadge(record.grade));$('recorded-site').textContent=site.name+' / recorded browser';
  $('review-goal-label').textContent=record.kind==='task'?'Exact task goal':'User request';$('review-goal').textContent=record.goal;
  $('review-requirements').replaceChildren(...record.requirements.map(requirement=>{
    const li=node('li');li.append(node('span',requirement.result===true?'✓':requirement.result===false?'×':'–','requirement-icon '+(requirement.result===false?'failed':requirement.result===null?'unknown':'')),node('span',requirement.label));return li;
  }));
  if(!record.requirements.length)$('review-requirements').append(node('li','No fixed-task requirements attached.','muted'));
  $('grade-note').textContent=record.gradeNote;
  const count=record.availableSteps||0;currentStep=Math.max(0,Math.min(currentStep,count-1));
  $('review-events').replaceChildren(...record.steps.slice(0,count).map((step,index)=>{const li=node('li'),button=node('button',(index+1)+'. '+step);button.type='button';button.setAttribute('aria-current',String(index===currentStep));button.onclick=()=>{stopReplay();currentStep=index;renderReview();};li.append(button);return li;}));
  $('recorded-image').src='/preview/images/'+site.image+'-'+Math.min(3,currentStep)+'.png';
  $('recorded-image').alt=site.name+' · illustrative sample viewport for recorded step '+(currentStep+1);
  $('recorded-caption').textContent='Step '+(currentStep+1)+' · sample pre-action viewport · not an interactive page';
  $('review-position').textContent=(currentStep+1)+' / '+count;
  $('review-scrubber').max=String(Math.max(0,count-1));$('review-scrubber').value=String(currentStep);$('review-scrubber').disabled=count<2;
  $('review-previous').disabled=currentStep<=0;$('review-next').disabled=currentStep>=count-1;$('review-play').disabled=count<2||running;
  $('review-details').replaceChildren(...[['Site',site.name],['Activity',record.kind==='task'?'Task · '+record.title:'Ask the agent'],['Run ID',record.id],['Source','Local synthetic design fixture'],['Grade source',record.kind==='task'?'Explicit sample verifier result':'No verifier'],['Execution state',record.status]].flatMap(([key,value])=>[node('dt',key),node('dd',value)]));
}
function setAskBusy(value) {askBusy=value;const frame=frames.get(siteID);if(frame){frame.inert=value;frame.style.pointerEvents=value?'none':'';}$('question').disabled=value;$('send-question').disabled=value;$('reset-page').disabled=value;$('explore-status').textContent=value?'The scripted assistant is using this page…':'You can click, type and navigate freely.';renderSites();document.querySelectorAll('#suggestions button').forEach(button=>button.disabled=value);}
async function scriptedReply(question,id) {
  const frame=ensureFrame(id);let doc=await waitForDocument(frame);await wait(500);
  if(id==='campus') {
    if(/room|people|three|3|available|availability/i.test(question)) {
      if(!doc.querySelector('#room-people')) {const previous=doc;doc.querySelector('[data-page="booking"]').click();doc=await waitForDocument(frame,{previousDocument:previous});}
      for(const [selector,value] of [['#room-building','Ångström'],['#room-people','3']]){const el=doc.querySelector(selector);el.value=value;el.dispatchEvent(new doc.defaultView.Event('change',{bubbles:true}));}
      const first=doc.querySelector('[data-room]');
      return 'Scripted preview: I opened Study rooms and filtered for Ångström and 3 people. '+(first?'The first displayed option is '+first.getAttribute('aria-label').replace(/^Book /,'')+'. ':'')+'I have not made a reservation. You can keep exploring the page.';
    }
    return 'Scripted preview: you’re on '+doc.title+'. You can browse the shop, open Study rooms, change filters, or visit My account. Try “Find a room for three people” to see the sidebar operate the room filters.';
  }
  const second=/second|wandering/i.test(question),title=second?'The Art of Wandering':'A Field Guide to Noticing';
  const input=doc.querySelector('#book-search');if(input){input.value=title;doc.querySelector('#search').click();}
  doc.querySelector('.choose')?.click();
  return 'Scripted preview: I opened '+title+'. The sample page lists the paperback at '+(second?'149':'179')+' SEK. Nothing has been purchased. You can inspect the book or continue browsing yourself.';
}
$('ask-form').onsubmit=async event=>{
  event.preventDefault();const question=$('question').value.trim();if(!question||askBusy)return;
  const id=siteID,conversation=state.get(id);conversation.messages.push({role:'user',text:question});conversation.draft='';renderConversation();setAskBusy(true);$('chat-status').textContent='Running the local scripted example…';
  try {
    const answer=await scriptedReply(question,id),record=askRecord('preview-ask-'+crypto.randomUUID(),id,question,0);record.at=Date.now();record.steps=['Read the current page','Use the relevant page controls','Inspect the displayed result','Reply to the user'];
    added.unshift(record);persist();conversation.messages.push({role:'assistant',text:answer,runID:record.id});$('chat-status').textContent='Saved to this site’s replays · not graded';
  }catch(error){conversation.messages.push({role:'assistant',text:'The scripted preview stopped: '+error.message});$('chat-status').textContent='Preview stopped';}
  finally{setAskBusy(false);renderConversation();$('replay-count').textContent=String(records().filter(r=>r.site===siteID).length);}
};
$('try-task').onclick=()=>{
  if(taskTimer||!pendingTask)return;
  const record=taskRecord('preview-task-'+crypto.randomUUID(),pendingTask.id,'success',0),finalRequirements=record.requirements;
  record.at=Date.now();record.grade='running';record.status='running';record.availableSteps=1;record.requirements=record.requirements.map(r=>({...r,result:null}));record.gradeNote='The scripted sample is in progress. No grade has been recorded yet.';
  added.unshift(record);$('task-dialog').close();openRun(record,false);
  taskTimer=setInterval(()=>{
    if(record.availableSteps<4)record.availableSteps++;
    else{record.grade='success';record.status='finished';record.requirements=finalRequirements;record.gradeNote='The scripted sample has finished. Its sample verifier result is Succeeded.';clearInterval(taskTimer);taskTimer=null;persist();}
    if(currentRun?.id===record.id&&view==='review'){currentStep=record.availableSteps-1;renderReview();}else if(view==='research')renderTasks();else if(globalPage)renderGlobal();
  },1100);
};
$('explore-tab').onclick=()=>setView('explore');$('research-tab').onclick=()=>setView('research');$('sidebar-tasks').onclick=()=>setView('research');
for(const id of ['all-replays-link','global-library-link'])$(id).onclick=openGlobal;
$('question').oninput=()=>{state.get(siteID).draft=$('question').value;};$('site-search').oninput=renderSites;$('replay-kind').onchange=renderTasks;
for(const id of ['global-search','global-collection','global-site','global-kind','global-grade'])$(id).addEventListener(id==='global-search'?'input':'change',()=>{renderGlobal();});
$('clear-filters').onclick=()=>{for(const id of ['global-collection','global-site','global-kind','global-grade'])$(id).value='all';$('global-search').value='';renderGlobal();};
$('toggle-agent').onclick=()=>{agentVisible=!agentVisible;$('agent-sidebar').hidden=!agentVisible;document.querySelector('.explore-layout').classList.toggle('agent-hidden',!agentVisible);$('toggle-agent').textContent=agentVisible?'Hide agent':'Show agent';$('toggle-agent').setAttribute('aria-expanded',String(agentVisible));};
$('reset-page').onclick=()=>{if(askBusy)return;const frame=frames.get(siteID);if(siteID==='campus')window.demoWorld=new World(fixture);frame.src=siteFor(siteID).src;};
$('back-to-research').onclick=()=>{stopReplay();view=globalPage?'global':'research';currentRun=null;render();syncURL();};
$('review-previous').onclick=()=>{stopReplay();currentStep=Math.max(0,currentStep-1);renderReview();};$('review-next').onclick=()=>{stopReplay();currentStep=Math.min(currentRun.availableSteps-1,currentStep+1);renderReview();};
$('review-scrubber').oninput=()=>{stopReplay();currentStep=Number($('review-scrubber').value);renderReview();};
$('review-play').onclick=()=>{if(replayTimer){stopReplay();return;}if(currentStep>=currentRun.availableSteps-1)currentStep=0;$('review-play').textContent='Pause replay';renderReview();replayTimer=setInterval(()=>{if(currentStep>=currentRun.availableSteps-1)stopReplay();else{currentStep++;renderReview();}},1000);};
$('recorded-image').onerror=()=>{$('recorded-caption').textContent='Sample image unavailable. Recording details and requirements remain below.';};
function readRoute(){stopReplay();const params=new URLSearchParams(location.search);globalPage=location.pathname==='/workspace/replays';siteID=siteFor(params.get('site'))?.id||siteID;currentRun=records().find(r=>r.id===params.get('run'))||null;view=currentRun?'review':globalPage?'global':params.get('view')==='research'?'research':'explore';if(currentRun&&!globalPage)siteID=currentRun.site;currentStep=0;render();}
window.addEventListener('popstate',readRoute);window.addEventListener('pagehide',()=>{stopReplay();clearInterval(taskTimer);});
readRoute();
