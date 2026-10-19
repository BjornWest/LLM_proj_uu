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
      stream = new EventSource('/api/tasks/'+run+'/events');
      stream.onmessage = msg => {
        if (token !== generation) return;
        const e = JSON.parse(msg.data);
        if (e.type === 'status') status.textContent = e.state;
        if (e.type === 'step') status.textContent = e.summary;
        if (e.type === 'site') {
          document.dispatchEvent(new CustomEvent('raven-web-activity',{detail:{url:e.url,label:e.title}}));
        }
        if (e.type === 'tab') {
          for(const [id,tab] of tabs)if(id!==e.tab_id && tab.url===e.url)tabs.delete(id);
          if(e.action === 'closed') tabs.delete(e.tab_id); else tabs.set(e.tab_id,e);
          drawTabs();
        }
        if (e.type === 'handover') {
          pendingTab=e.tab_id;handover.hidden=false;
          document.querySelector('#handover-message').textContent=e.message;
        }
        if (e.type === 'final') {
          c.agentReply=e;c.reply();history.push({who:'Raven',text:e.markdown});
          document.dispatchEvent(new CustomEvent('raven-web-activity',{detail:{status:'complete'}}));
        }
        if (e.type === 'error') {
          status.textContent=e.message;c.cancelTask({announce:false});c.appendMessage(e.message,'Raven');
        }
        if (e.type === 'done') {
          stream.close();stream=null;run=null;stop.disabled=true;handover.hidden=true;
          status.textContent=e.stop_reason;
          if(!c.agentReply)c.cancelTask({announce:false});
        }
      };
      stream.onerror = () => {status.textContent='Reconnecting…';};
    }).catch(e => {status.textContent=e.message;stop.disabled=true;c.cancelTask({announce:false});});
    return true;
  };
  stop.onclick = async () => {
    generation++;
    const id=run;run=null;stream?.close();stream=null;stop.disabled=true;handover.hidden=true;
    c.cancelTask({announce:false});status.textContent='Cancelled';
    if(id)await post('/api/tasks/'+id+'/cancel');
  };
  document.querySelector('#handback').onclick = async () => {
    try {
      await post('/api/tasks/'+run+'/handback',{tab_id:pendingTab,note:null});
      handover.hidden=true;status.textContent='Returned to Raven';
    } catch(e) {status.textContent=e.message;}
  };
  fetch('/api/tabs').then(r=>r.json()).then(data=>{for(const t of data.tabs)tabs.set(t.tab_id,t);drawTabs();});
});
