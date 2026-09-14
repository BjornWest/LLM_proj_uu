const $ = id => document.getElementById(id);
let config, world, area = 'shop', job = null, version = '', polling = false;
const titles = {shop: 'Campus Supply', booking: 'Campus Rooms', preferences: 'Your preferences'};
const paragraph = text => Object.assign(document.createElement('p'), {textContent: text});
const item = text => Object.assign(document.createElement('li'), {textContent: text});

function notice(text) { $('notice').textContent = text; }
async function api(path, data) {
  const response = await fetch(path, data ? {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data)
  } : {});
  const result = await response.json();
  if (!response.ok) throw Error(result.error || 'Demo unavailable');
  return result;
}
function busy(value) {
  for (const id of ['run', 'reset', 'goal', 'mode']) $(id).disabled = value;
  document.querySelectorAll('.example').forEach(button => button.disabled = value);
}
function modeNote() {
  $('mode-note').textContent = $('mode').value === 'live'
    ? 'Uses the configured model. Each browser action is saved in its activity record.'
    : 'Scripted rehearsal follows this exact example; it is not an LLM run.';
  if (area==='booking') $('mode-note').textContent += ' One reservation per task.';
}
async function reset() {
  busy(true);
  try {
    world = (await api('/api/new', {})).world;
    clearConversation();
    $('site').src = '/world/' + world + '/' + area;
    $('site').hidden = false;
    $('screen').hidden = true;
    $('watching').textContent = 'Explore the page';
    $('resume-page').hidden = true;
    $('outcome').hidden = true;
    $('status').textContent = 'Ready';
    $('steps').replaceChildren(item('Choose a task and I’ll get started.'));
    $('cost').textContent = '';
    $('trace').removeAttribute('href');
    notice('');
    job = null;
    version = '';
  } finally { busy(false); }
}
async function choose(next) {
  area = next;
  $('workspace-title').textContent = titles[area];
  $('browser-tab-title').textContent = titles[area];
  $('address').textContent = (area === 'booking' ? 'rooms.campus.local / reservations' : 'campus.local / ' + area);
  $('chat-context').textContent = titles[area];
  $('goal').value = config.examples[area].goal;
  document.querySelectorAll('.example').forEach(button =>
    button.classList.toggle('active', button.dataset.area === area));
  modeNote();
  if (!world) await reset();
  else {
    // Navigation keeps this browser session and conversation; Start fresh resets it.
    $('site').src='/world/'+world+'/'+area;
    $('site').hidden=false;$('screen').hidden=true;$('resume-page').hidden=true;
    $('watching').textContent='Explore the page';$('outcome').hidden=true;
    notice('');
  }
}
$('run').onclick = async () => {
  try {
    busy(true);
    notice('');
    $('outcome').hidden = true;
    $('resume-page').hidden = true;
    $('status').textContent = 'Starting';
    $('sidebar-state').textContent = '● Running your task';
    const result = await api('/api/run', {world, area, goal: $('goal').value, mode: $('mode').value});
    job = result.job;
    $('steps').replaceChildren(item('Opening the page…'));
    $('watching').textContent = 'Watching the agent';
    poll();
  } catch (error) { notice(error.message); busy(false); }
};
$('reset').onclick = () => reset().catch(error => notice(error.message));
$('mode').onchange = modeNote;
document.querySelectorAll('.example').forEach(button =>
  button.onclick = () => choose(button.dataset.area).catch(error => notice(error.message)));

async function poll() {
  if (!job || polling) return;
  polling = true;
  const currentJob = job;
  try {
    const state = await api('/api/jobs/' + currentJob);
    if (job !== currentJob) return;
    $('status').textContent = state.status === 'running' ? 'Working' : state.error ? 'Stopped' : 'Finished';
    if (state.image && version !== state.image) {
      version = state.image;
      $('screen').src = state.image;
      $('screen').hidden = false;
      $('site').hidden = true;
    }
    if (state.activity.length) $('steps').replaceChildren(...state.activity.map(item));
    if (state.trace_url) $('trace').href = state.trace_url;
    if (state.cost !== null) $('cost').textContent = 'Model spend $' + Number(state.cost).toFixed(4);
    if (state.status !== 'running') {
      busy(false);
      $('resume-page').hidden = false;
      $('watching').textContent = (state.mode === 'live' ? 'Live agent' : 'Scripted rehearsal')
        + (state.error ? ' · stopped' : ' · finished');
      if (state.error) notice('The agent stopped before finishing. The page may already have changed; open the activity record for details.');
      if (state.result) {
        $('outcome').hidden = false;
        $('outcome').replaceChildren(paragraph(state.result.title),
          ...state.result.lines.map(text => paragraph('✓ ' + text)));
      }
      appendMessage('assistant', state.error ? 'The task stopped. You can ask me about the recorded steps.' : 'The task has finished. Ask me what changed or review the activity in Tasks.');
      $('sidebar-state').textContent = state.error ? '● Task stopped' : '● Task finished';
      job = null;
    }
    if (state.alerts.length) notice(state.alerts.join(' '));
  } catch (error) { notice(error.message); }
  finally { polling = false; }
}
$('screen').onerror = () => { version = ''; };
busy(true);
api('/api/config').then(async result => {
  config = result;
  $('mode').querySelector('[value=live]').disabled = !config.live_available;
  if (config.live_available) $('mode').value = 'live';
  modeNote();
  $('question').disabled = !config.live_available;
  $('send-chat').disabled = !config.live_available;
  if (!config.live_available) $('chat-hint').textContent = 'Live chat is unavailable in rehearsal-only mode';
  await choose('booking');
}).catch(error => notice(error.message));
setInterval(poll, 900);


let chatPending = false, chatGeneration = 0;
const welcome = $('conversation').innerHTML;
function tab(name) {
  for (const key of ['chat','tasks']) {
    $(key+'-tab').setAttribute('aria-selected', String(key === name));
    $(key+'-panel').hidden = key !== name;
  }
}
$('chat-tab').onclick = () => tab('chat');
$('tasks-tab').onclick = () => tab('tasks');
$('toggle-sidebar').onclick = () => {
  const closed = document.body.classList.toggle('sidebar-closed');
  $('toggle-sidebar').setAttribute('aria-expanded',String(!closed));
};
function clearConversation() {
  chatGeneration++;
  $('conversation').innerHTML = welcome;
  $('question').value = '';
  $('chat-notice').textContent = '';
  chatPending = false;
  if (config) $('send-chat').disabled = !config.live_available;
}
function appendMessage(role, text, traceURL) {
  $('conversation').querySelector('.chat-welcome')?.remove();
  const node=document.createElement('div');node.className='chat-message '+role;
  const label=document.createElement('span');label.className='message-label';label.textContent=role==='user'?'You':'Daylight';
  node.append(label);
  // Render only inline emphasis/code with text nodes; never trust model HTML.
  for (const part of text.split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/g)) {
    if (part.startsWith('**') && part.endsWith('**')) {const strong=document.createElement('strong');strong.textContent=part.slice(2,-2);node.append(strong);}
    else if (part.startsWith('`') && part.endsWith('`')) {const code=document.createElement('code');code.textContent=part.slice(1,-1);node.append(code);}
    else node.append(document.createTextNode(part));
  }
  if (traceURL) {const link=document.createElement('a');link.href=traceURL;link.target='_blank';link.rel='noopener';link.textContent='Response record ↗';node.append(link);}
  $('conversation').append(node);$('conversation').scrollTop=$('conversation').scrollHeight;
  return node;
}
function pageSnapshot() {
  if ($('site').hidden) return {page_text:'',page_title:titles[area]};
  const doc=$('site').contentDocument;
  if (!doc?.body) return {page_text:'',page_title:titles[area]};
  const controls=[...doc.querySelectorAll('input,select,button[aria-label]')].filter(el=>el.type!=='password').map(el=> {
    const label=el.getAttribute('aria-label')||[...(el.labels||[])].map(l=>l.textContent.trim()).join(' ')||el.name;
    const value=el.tagName==='SELECT'?[...el.selectedOptions].map(o=>o.textContent).join(', '):el.type==='checkbox'?(el.checked?'on':'off'):el.value||'available control';
    return label+': '+value;
  });
  return {page_title:doc.title,page_text:(doc.body.innerText+'\nCurrent controls and selected values:\n'+controls.join('\n')).slice(0,12000)};
}
$('site').addEventListener('load',()=> {
  try {
    const current=$('site').contentWindow.location.pathname.split('/').at(-1);
    if (titles[current] && current!==area && !job) {
      area=current;$('workspace-title').textContent=titles[area];$('browser-tab-title').textContent=titles[area];$('chat-context').textContent=titles[area];
      $('address').textContent=(area==='booking'?'rooms.campus.local / reservations':'campus.local / '+area);
      $('goal').value=config.examples[area].goal;
      document.querySelectorAll('.example').forEach(b=>b.classList.toggle('active',b.dataset.area===area));
    }
  } catch (_) {}
});
$('chat-form').onsubmit=async event=> {
  event.preventDefault();
  const question=$('question').value.trim();
  if (!question || chatPending || !config.live_available) return;
  const generation=chatGeneration;
  chatPending=true;$('send-chat').disabled=true;$('question').value='';$('chat-notice').textContent='';
  appendMessage('user',question);
  const pending=appendMessage('pending','Reading the page…');
  try {
    const response=await api('/api/chat',{world,question,...pageSnapshot()});
    let state;
    do {
      await new Promise(resolve=>setTimeout(resolve,800));
      state=await api('/api/chat/'+response.turn);
    } while (state.status==='running' && generation===chatGeneration);
    if (generation!==chatGeneration) return;
    pending.remove();
    appendMessage(state.error?'error':'assistant',state.error||state.answer,state.trace_url);
    $('chat-notice').textContent=state.alerts.length?state.alerts.join(' '):state.cost!==null?'Response cost $'+Number(state.cost).toFixed(5):'';
  } catch(error) {
    if(generation===chatGeneration){pending.remove();appendMessage('error',error.message);}
  } finally {
    if(generation===chatGeneration){chatPending=false;$('send-chat').disabled=!config.live_available;}
  }
};
$('question').onkeydown=event=>{if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();$('chat-form').requestSubmit();}};
document.querySelectorAll('[data-question]').forEach(button=>button.onclick=()=>{
  $('question').value=button.dataset.question;tab('chat');$('question').focus();
});

$('resume-page').onclick=()=>{
  $('site').src='/world/'+world+'/'+area;
  $('site').hidden=false;$('screen').hidden=true;$('resume-page').hidden=true;
  $('watching').textContent='Explore the page';
};
