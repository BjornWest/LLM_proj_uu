/* API adapter for the app-owned v40 controller. */
window.addEventListener('DOMContentLoaded', () => {
  const c = window.ravenChatDemo;
  const status = document.querySelector('#run-status');
  const stop = document.querySelector('#stop');
  const handover = document.querySelector('#handover');
  const history = [];
  const conversation = crypto.randomUUID();
  let run = null, stream = null, pendingTab = null, generation = 0;
  const post = async (url, body = {}) => {
    const r = await fetch(url, {method: 'POST', headers: {'Content-Type':'application/json'}, body:JSON.stringify(body)});
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || 'Request failed');
    return data;
  };
  const tabs = new Map();
  const handovers = new Map();
  function showHandover() {
    const next = handovers.entries().next().value;
    pendingTab = next?.[0] || null;
    handover.hidden = !next;
    document.querySelector('#handover-message').textContent = next?.[1] || '';
  }
  function drawTabs() {
    const root = document.querySelector('#tabs');
    root.replaceChildren();
    for (const tab of tabs.values()) {
      const button = document.createElement('button');
      button.textContent = tab.title || tab.url || tab.tab_id;
      button.title = tab.url;
      button.onclick = () => post('/api/tabs/'+tab.tab_id+'/focus').catch(e => status.textContent=e.message);
      root.append(button);
    }
  }
  c.input.placeholder = 'Ask Raven to explore the web…';
  c.updateHint = () => {};
  c.countdown.textContent = 'Your shared browser';
  const originalLaunch = c.launch.bind(c);
  c.launch = function(replyMs) {
    originalLaunch(replyMs);
    if(c.agentReply)c.reply();
  };
  const originalStart = c.start.bind(c);
  c.start = function(options) {
    if (run) return false;
    const text = c.input.value.trim();
    const prior = history.slice();
    c.agentReply = null;
    if (!originalStart(options)) return false;
    history.push({who:'You', text});
    const token = ++generation;
    stop.disabled = false;
    status.textContent = 'Starting…';
    post('/api/tasks', {text, conversation_id:conversation, mode:'user_window', history:prior}).then(data => {
      if (token !== generation) {post('/api/tasks/'+data.run_id+'/cancel');return;}
      run = data.run_id;
      tabs.clear();drawTabs();handovers.clear();showHandover();
      stream = new EventSource('/api/tasks/'+run+'/events');
      stream.onmessage = msg => {
        if (token !== generation) return;
        const e = JSON.parse(msg.data);
        if (e.type === 'status') status.textContent = {starting:'Starting research…',working:'Researching…',finishing:'Preparing your answer…'}[e.state] || 'Researching…';
        if (e.type === 'step') status.textContent = e.summary;
        if (e.type === 'site') {
          document.dispatchEvent(new CustomEvent('raven-web-activity',{detail:{url:e.url,label:e.title}}));
        }
        if (e.type === 'tab') {
          if(e.action === 'closed') {tabs.delete(e.tab_id);handovers.delete(e.tab_id);showHandover();} else tabs.set(e.tab_id,e);
          drawTabs();
        }
        if (e.type === 'handover') {
          handovers.set(e.tab_id,e.message);showHandover();
        }
        if (e.type === 'final') {
          c.agentReply=e;c.reply();history.push({who:'Raven',text:e.markdown});
          document.dispatchEvent(new CustomEvent('raven-web-activity',{detail:{status:'complete'}}));
        }
        if (e.type === 'error') {
          status.textContent="I couldn't finish that: "+e.message;c.cancelTask({announce:false});c.appendMessage(status.textContent,'Raven');
        }
        if (e.type === 'done') {
          stream.close();stream=null;run=null;stop.disabled=true;handovers.clear();showHandover();
          status.textContent=e.stop_reason === 'cancelled' ? 'Stopped' : e.stop_reason === 'agent_finished' ? 'Ready' : "I couldn't finish that: "+({max_total_input_tokens:'the research budget was reached',max_total_output_tokens:'the answer budget was reached',max_input_tokens:'the conversation became too long',error:'please try again'}[e.stop_reason] || 'the task ended before an answer was ready');
          if(!c.agentReply)c.cancelTask({announce:false});
        }
      };
      stream.onerror = () => {
        const id=run;generation++;stream?.close();stream=null;run=null;stop.disabled=true;
        handovers.clear();showHandover();c.cancelTask({announce:false});
        status.textContent="I couldn't finish that: the connection was interrupted. Please try again.";
        c.appendMessage(status.textContent,'Raven');
        if(id)post('/api/tasks/'+id+'/cancel').catch(()=>{});
      };
    }).catch(e => {status.textContent="I couldn't finish that: "+e.message;stop.disabled=true;c.cancelTask({announce:false});c.appendMessage(status.textContent,'Raven');});
    return true;
  };
  stop.onclick = async () => {
    generation++;
    const id=run;run=null;stream?.close();stream=null;stop.disabled=true;handovers.clear();showHandover();
    const cancelled = id ? post('/api/tasks/'+id+'/cancel') : Promise.resolve();
    c.cancelTask({announce:false});status.textContent='Cancelled';
    try {await cancelled;} catch(e) {status.textContent=e.message;}
  };
  document.querySelector('#handback').onclick = async () => {
    const tab = pendingTab;
    const button = document.querySelector('#handback');
    button.disabled=true;
    try {
      await post('/api/tasks/'+run+'/handback',{tab_id:tab,note:null});
      handovers.delete(tab);showHandover();status.textContent='Returned to Raven';
    } catch(e) {handovers.delete(tab);showHandover();status.textContent='That tab is no longer waiting for help. Raven can continue.';}
    finally {button.disabled=false;}
  };
  fetch('/api/tabs').then(r=>r.json()).then(data=>{for(const t of data.tabs || [])tabs.set(t.tab_id,t);drawTabs();});
});
