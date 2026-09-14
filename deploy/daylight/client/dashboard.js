import {World} from './world.js';
import {snapshot,execute} from './observation.js';
const $=id=>document.getElementById(id),titles={shop:'Campus Supply',booking:'Campus Rooms',preferences:'Your preferences'};
const fixture=await (await fetch('/assets/fixture.json')).json();
const config=await api('/api/config');
let area='booking',running=false,chatting=false,worldID,conversation=[],activity=[],lastTrace=null;
window.demoWorld=new World(fixture);
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function api(url,data) {
  const response=await fetch(url,data?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)}:{});
  const value=await response.json();if(!response.ok)throw Error(value.error||'Request failed');return value;
}
function message(role,text,trace) {
  $('conversation').querySelector('.chat-welcome')?.remove();
  const div=document.createElement('div');div.className='chat-message '+role;
  const label=document.createElement('span');label.className='message-label';label.textContent=role==='user'?'You':'Daylight';div.append(label);
  div.append(document.createTextNode(text));
  if(trace) {const a=document.createElement('a');a.textContent='Download response record ↗';a.href='/api/traces/'+trace;div.append(a);}
  $('conversation').append(div);$('conversation').scrollTop=$('conversation').scrollHeight;
}
function busy(value) {
  running=value;
  for(const id of ['run','reset','goal'])$(id).disabled=value;
  document.querySelectorAll('.example').forEach(b=>b.disabled=value);
  // Keep the real visible page. Block manual input while an action is being decided.
  $('site').style.pointerEvents=value?'none':'';$('site').inert=value;
  $('sidebar-state').textContent=value?'● Working on your task':'● Connected to this page';
}
function tab(name) {for(const key of ['chat','tasks']) {$(key+'-tab').setAttribute('aria-selected',String(key===name));$(key+'-panel').hidden=key!==name;}}
function showActivity() {
  $('steps').replaceChildren(...activity.map(text=>{const li=document.createElement('li');li.textContent=text;return li;}));
}
async function choose(next) {
  area=next;
  for(const id of ['workspace-title','browser-tab-title','chat-context'])$(id).textContent=titles[area];
  $('address').textContent=area==='booking'?'rooms.campus.demo / reservations':'campus.demo / '+area;
  $('goal').value=fixture.examples[area].goal;
  document.querySelectorAll('.example').forEach(b=>b.classList.toggle('active',b.dataset.area===area));
  $('site').src='/world/'+worldID+'/'+area;
  $('mode-note').textContent='Acts on this fictional page. Up to 12 model calls.'+(area==='booking'?' Stops after one confirmed reservation.':'');
}
async function reset() {
  window.demoWorld=new World(fixture);worldID=crypto.randomUUID();conversation=[];activity=[];lastTrace=null;
  $('conversation').replaceChildren();message('assistant','Ask me about the page, or give me a task in Tasks.');
  $('notice').textContent='';$('outcome').hidden=true;$('trace').removeAttribute('href');$('cost').textContent='';$('status').textContent='Ready';
  showActivity();await choose(area);
}
$('run').onclick=async()=> {
  if(running||chatting)return;
  busy(true);activity=[];showActivity();$('notice').textContent='';$('status').textContent='Working';$('outcome').hidden=true;
  let id,cost=0;
  const before=structuredClone(window.demoWorld.state);
  try {
    ({id}=await api('/api/start',{mode:'task',goal:$('goal').value}));lastTrace=id;$('trace').href='/api/traces/'+id;
    for(let i=0;i<12;i++) {
      // Any pacing happens before snapshot, never between page capture and dispatch.
      if(i)await wait(750);
      const doc=$('site').contentDocument;if(!doc?.querySelector('#content'))throw Error('Wait for the page to finish loading');
      const captured=snapshot(doc);
      const result=await api('/api/step',{id,observation:captured.observation});
      cost+=result.cost||0;$('cost').textContent='Model spend $'+cost.toFixed(4);
      if(result.alerts?.length)$('notice').textContent=result.alerts.join(' ');
      if(result.error)throw Error(result.error);
      let error=null;
      try {execute(result.action,captured,doc);await wait(150);}catch(e){error=e.message;}
      const a=result.action,control=captured.observation.controls.find(c=>c.id===a.id);
      const description=a.action==='done'?a.message:[a.action,control?.label,a.value!==undefined?String(a.value):''].filter(Boolean).join(' · ');
      activity.push((error?'Failed: ':'')+description);showActivity();
      const bookingBoundary=window.demoWorld.state.bookings.length>before.bookings.length;
      const saved=await api('/api/event',{id,result:{error,description,stop:bookingBoundary,
        stop_reason:bookingBoundary?'first_accepted_reservation':a.action==='done'?'model_done':null,
        page_after:snapshot($('site').contentDocument).observation,
        state_after:window.demoWorld.state,events:window.demoWorld.events}});
      if(error)throw Error(error);
      if(saved.status!=='ready') {
        $('status').textContent=saved.status==='step_limit'?'Step limit':'Finished';
        message('assistant',saved.status==='step_limit'?'The task reached its step limit. Review the activity and current page.':
          bookingBoundary?'A reservation was confirmed. Review it under My reservations.':a.message||'The task finished. You can ask me about the recorded steps.');
        break;
      }
    }
  } catch(e) {$('notice').textContent=e.message;$('status').textContent='Stopped';message('assistant','The task stopped: '+e.message+'. Earlier page changes may already have happened.');}
  finally {busy(false);$('watching').textContent='Explore the page';}
};
$('chat-form').onsubmit=async event=> {
  event.preventDefault();const question=$('question').value.trim();if(!question||chatting||running)return;
  chatting=true;$('send-chat').disabled=true;$('run').disabled=true;$('reset').disabled=true;$('question').value='';$('chat-notice').textContent='';
  message('user',question);
  try {
    const {id}=await api('/api/start',{mode:'chat',goal:question});
    const response=await api('/api/step',{id,observation:snapshot($('site').contentDocument).observation,
      conversation,activity:JSON.stringify({last_task_trace:lastTrace,steps:activity})});
    if(response.error)throw Error(response.error);
    message('assistant',response.answer,id);conversation.push({role:'user',content:question},{role:'assistant',content:response.answer});conversation=conversation.slice(-8);
    $('chat-notice').textContent='Model spend $'+Number(response.cost||0).toFixed(4);
  } catch(e){$('chat-notice').textContent=e.message;}
  finally {chatting=false;$('send-chat').disabled=false;$('run').disabled=false;$('reset').disabled=false;}
};
$('chat-tab').onclick=()=>tab('chat');$('tasks-tab').onclick=()=>tab('tasks');
$('toggle-sidebar').onclick=()=>{$('toggle-sidebar').setAttribute('aria-expanded',String(!document.body.classList.toggle('sidebar-closed')));};
$('reset').onclick=reset;
document.querySelectorAll('.example').forEach(b=>b.onclick=()=>choose(b.dataset.area));
document.querySelectorAll('[data-question]').forEach(b=>b.onclick=()=>{$('question').value=b.dataset.question;$('question').focus();});
$('site').addEventListener('load',()=>{
  const next=$('site').contentWindow.location.pathname.split('/').at(-1);
  if(titles[next]) {area=next;for(const id of ['workspace-title','browser-tab-title','chat-context'])$(id).textContent=titles[area];}
});
$('mode').disabled=true;$('question').disabled=!config.live_available;$('send-chat').disabled=!config.live_available;$('run').disabled=!config.live_available;
$('chat-hint').textContent='Read-only chat · Private team demo';
await reset();
if(!config.live_available)$('notice').textContent='OpenRouter has not been configured on this deployment yet.';
