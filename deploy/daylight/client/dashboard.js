import {createToolActivity,keepChatPosition,showChatWorking} from './tool-activity.js';
import {World} from './world.js';
import {snapshot,executeAndWait,waitForDocument} from './observation.js';
const $=id=>document.getElementById(id),titles={shop:'Campus Supply',booking:'Campus Rooms',preferences:'Your preferences'};
const fixture=await (await fetch('/assets/fixture.json')).json();
const config=await api('/api/config');
let area='booking',running=false,worldID,conversation=[],activity=[],lastTrace=null,pendingDocument=null;
window.demoWorld=new World(fixture);
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function api(url,data) {
  const response=await fetch(url,{credentials:'same-origin',redirect:'manual',...(data?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}:{})});
  if(response.status===401||response.type==='opaqueredirect')throw Error('Your session expired. Sign in again before starting another request.');
  const value=await response.json().catch(()=>null);if(!response.ok||!value)throw Error(value?.error||'Request failed');return value;
}
function message(role,text,trace) {
  $('conversation').querySelector('.chat-welcome')?.remove();
  const div=document.createElement('div');div.className='chat-message '+role;
  const label=document.createElement('span');label.className='message-label';label.textContent=role==='user'?'You':'Daylight';div.append(label);
  div.append(document.createTextNode(text));
  if(trace) {const a=document.createElement('a');a.textContent='Download original turn record ↗';a.href='/api/traces/'+encodeURIComponent(trace);div.append(a);}
  $('conversation').append(div);$('conversation').scrollTop=$('conversation').scrollHeight;
}
function busy(value) {
  running=value;
  for(const id of ['reset','goal'])$(id).disabled=value;
  for(const id of ['run','question','send-chat'])$(id).disabled=value||!config.live_available;
  document.querySelectorAll('.example,[data-question]').forEach(b=>b.disabled=value);
  $('site').style.pointerEvents=value?'none':'';$('site').inert=value;
  $('sidebar-state').textContent=value?'● Working on your request':'● Connected to this page';
  $('watching').textContent=value?'Agent is using this page':'Explore the page';
}
function tab(name) {for(const key of ['chat','tasks']) {$(key+'-tab').setAttribute('aria-selected',String(key===name));$(key+'-panel').hidden=key!==name;}}
function showActivity() {
  $('steps').replaceChildren(...activity.map(text=>{const li=document.createElement('li');li.textContent=text;return li;}));
}
function context() {
  for(const id of ['workspace-title','browser-tab-title','chat-context'])$(id).textContent=titles[area];
  $('address').textContent=area==='booking'?'rooms.campus.demo / reservations':'campus.demo / '+area;
  document.querySelectorAll('.example').forEach(b=>b.classList.toggle('active',b.dataset.area===area));
  $('mode-note').textContent='Acts on this fictional page. Up to 12 model calls.'+(area==='booking'?' The demo stops after its first accepted reservation.':'');
}
function choose(next) {
  if(running)return;
  area=next;context();$('goal').value=fixture.examples[area].goal;
  pendingDocument=$('site').contentDocument;
  $('site').src='/world/'+worldID+'/'+area;
}
async function currentPage() {
  const previous=pendingDocument;
  const doc=await waitForDocument($('site'),{previousDocument:previous});
  if(pendingDocument===previous)pendingDocument=null;
  return doc;
}
function reset() {
  if(running)return;
  window.demoWorld=new World(fixture);worldID=crypto.randomUUID();conversation=[];activity=[];lastTrace=null;
  $('conversation').replaceChildren();message('assistant','Ask me to explore this page, find an option, or carry out a request.');
  $('notice').textContent='';$('chat-notice').textContent='';$('outcome').hidden=true;$('trace').removeAttribute('href');$('cost').textContent='';$('status').textContent='Ready';
  showActivity();choose(area);
}
function actionDescription(action,captured) {
  const control=captured.observation.controls.find(c=>c.id===action.id);
  return action.action==='done'?'Agent supplied an answer':
    [action.action,control?.label,action.value!==undefined?String(action.value):''].filter(Boolean).join(' · ');
}
async function runTurn(mode,goal) {
  const previousActivity={last_trace:lastTrace,steps:[...activity]};
  busy(true);activity=[];showActivity();$('notice').textContent='';$('status').textContent='Working';$('outcome').hidden=true;
  if(mode==='assist'){$('chat-notice').textContent='';showChatWorking($('conversation'),'Looking at the page…');}
  let id,cost=0,unknownCosts=0,pendingTool=null,actionError=null;
  const updateTool=(state,error)=>{if(pendingTool)keepChatPosition($('conversation'),()=>pendingTool.update(state,error));};
  const before=structuredClone(window.demoWorld.state);
  const spend=()=> 'Model spend $'+cost.toFixed(4)+(unknownCosts?' · '+unknownCosts+' attempt(s) with unknown cost':'');
  try {
    // Do not start an episode against an empty or still-navigating iframe.
    await currentPage();
    ({id}=await api('/api/start',{mode,goal}));lastTrace=id;$('trace').href='/api/traces/'+encodeURIComponent(id);
    for(let i=0;i<12;i++) {
      if(mode==='assist')showChatWorking($('conversation'),i?'Choosing the next action…':'Looking at the page…');
      if(i)await wait(750); // Pacing precedes the decision observation.
      const doc=await currentPage(),captured=snapshot(doc);
      // A dispatched request with no delivered response has unknown cost.
      unknownCosts++;
      const result=await api('/api/step',{id,observation:captured.observation,
        ...(mode==='assist'?{conversation,activity:JSON.stringify(previousActivity)}:{})});
      if(typeof result.cost==='number'&&Number.isFinite(result.cost)){cost+=result.cost;unknownCosts--;}
      $('cost').textContent=spend();
      if(result.alerts?.length)$('notice').textContent=result.alerts.join(' ');
      if(result.error)throw Error(result.error);
      if(!result.action)throw Error('No complete action was returned.');
      const a=result.action,description=actionDescription(a,captured);
      showChatWorking($('conversation'),'');actionError=null;
      if(mode==='assist'&&a.action!=='done'){pendingTool=createToolActivity(a,captured,i+1);keepChatPosition($('conversation'),()=>$('conversation').append(pendingTool.element));}
      let error=null,after=null;
      try {after=snapshot(await executeAndWait(a,captured,$('site'))).observation;}catch(e){error=e.message;}
      actionError=error;updateTool(error?'failed':'saving',error);
      activity.push((error?'Failed: ':'')+description);showActivity();
      const bookingBoundary=window.demoWorld.state.bookings.length>before.bookings.length;
      // A failed navigation/action still gets a receipt. Never snapshot a stale
      // document or retry an action merely to fill in its missing page_after.
      const saved=await api('/api/event',{id,result:{error,description,stop:bookingBoundary,
        stop_reason:error?'client_execution_error':bookingBoundary?'first_accepted_reservation':a.action==='done'?'model_done':null,
        page_after:after,state_after:window.demoWorld.state,events:window.demoWorld.events}});
      updateTool(error?'failed':'applied',error);pendingTool=null;
      if(error)throw Error(error);
      if(saved.status!=='ready') {
        if(!['complete','step_limit'].includes(saved.status))throw Error('The server stopped this turn ('+saved.status+').');
        const answer=saved.status==='step_limit'?'This request reached its step limit. Review the activity and current page.':
          bookingBoundary?'The demo recorded a reservation and stopped at its one-reservation limit. Review it under My reservations.':
          result.answer||a.message||'The request finished. Review the recorded activity.';
        $('status').textContent=saved.status==='step_limit'?'Step limit':'Finished';
        message('assistant',answer,id);
        if(mode==='assist') {
          conversation.push({role:'user',content:goal},{role:'assistant',content:answer});conversation=conversation.slice(-8);
          $('chat-notice').textContent=spend();
        }
        return;
      }
    }
    throw Error('The turn reached the client step limit without a terminal receipt.');
  } catch(e) {
    updateTool(actionError?'failed':'unrecorded',(actionError?actionError+' ':'')+'Receipt not saved: '+e.message);
    const text='The request stopped: '+e.message+' Earlier page changes may already have happened.';
    $('notice').textContent=e.message;$('status').textContent='Stopped';
    if(mode==='assist')$('chat-notice').textContent=e.message+' · '+spend();
    message('assistant',text,id);
  } finally {showChatWorking($('conversation'),'');busy(false);}
}
$('run').onclick=async()=> {if(running||!config.live_available)return;await runTurn('task',$('goal').value);};
$('chat-form').onsubmit=async event=> {
  event.preventDefault();const question=$('question').value.trim();if(!question||running||!config.live_available)return;
  $('question').value='';message('user',question);await runTurn('assist',question);
};
$('chat-tab').onclick=()=>tab('chat');$('tasks-tab').onclick=()=>tab('tasks');
$('toggle-sidebar').onclick=()=>{$('toggle-sidebar').setAttribute('aria-expanded',String(!document.body.classList.toggle('sidebar-closed')));};
$('reset').onclick=reset;
document.querySelectorAll('.example').forEach(b=>b.onclick=()=>choose(b.dataset.area));
document.querySelectorAll('[data-question]').forEach(b=>b.onclick=()=>{if(!running){$('question').value=b.dataset.question;$('question').focus();}});
$('site').addEventListener('load',()=>{
  const next=$('site').contentWindow.location.pathname.split('/').at(-1);
  if(titles[next]) {area=next;context();}
});
$('mode').disabled=true;
$('chat-hint').textContent='Can navigate and act · Private demo';
document.querySelector('.read-only-tag').textContent='Interactive';
$('question').placeholder='Ask a question or give a request…';
$('question').setAttribute('aria-label','Ask Daylight a question or give a request');
reset();busy(false);
if(!config.live_available)$('notice').textContent='OpenRouter has not been configured on this deployment yet.';
