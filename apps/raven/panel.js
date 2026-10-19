/* API adapter for the app-owned v40 controller. */
window.addEventListener('DOMContentLoaded', () => {
  const c = window.ravenChatDemo;
  const status = document.querySelector('#run-status');
  const stop = document.querySelector('#stop');
  const handover = document.querySelector('#handover');
  const history = [];
  const mode = document.querySelector('#browser-mode');
  const steps = new RavenSteps(document.querySelector('#chat-scene'));
  const append = c.appendMessage.bind(c);
  c.appendMessage = function(text, who, options) {
    append(text, who, options);
    if (who === 'Raven') steps.finish(c.messages.lastElementChild);
  };
  const conversation = crypto.randomUUID();
  let run = null, stream = null, pendingTab = null, generation = 0;
  const post = async (url, body = {}) => {
    await window.ravenTransport.ready;
    const r = await fetch(url, {method: 'POST', headers: {'Content-Type':'application/json'}, body:JSON.stringify(body)});
    const data = await r.json();
    if (!r.ok) {const error=new Error(data.error || 'Request failed');error.status=r.status;throw error;}
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
      if(mode.value === 'background_window' && tab.owner !== 'agent') continue;
      let site;try {site=new URL(tab.url);} catch {}
      button.textContent = site?.hostname.replace(/^www\./,'') || tab.title || 'New tab';
      if (site && ['http:','https:'].includes(site.protocol)) {
        const icon=document.createElement('img');icon.src=tab.favicon || site.origin+'/favicon.ico';icon.alt='';icon.width=14;icon.height=14;icon.onerror=()=>icon.remove();button.prepend(icon);
      }
      button.title = tab.url;
      button.onclick = () => post('/api/tabs/'+encodeURIComponent(tab.focus_id || tab.tab_id)+'/focus').catch(e => status.textContent=window.ravenTransport.errorMessage(e));
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
    steps.reset();mode.disabled=true;
    const token = ++generation;
    let errorShown = false;
    stop.disabled = false;
    status.textContent = 'Starting…';
    post('/api/tasks', {text, conversation_id:conversation, mode:mode.value, history:prior}).then(data => {
      if (token !== generation) {post('/api/tasks/'+data.run_id+'/cancel');return;}
      run = data.run_id;
      tabs.clear();drawTabs();handovers.clear();showHandover();
      stream = window.ravenTransport.events(run, {onEvent:e => {
        if (token !== generation) return;
        steps.event(e);
        if (e.type === 'status') status.textContent = {starting:'Starting research…',working:'Researching…',finishing:'Preparing your answer…'}[e.state] || 'Researching…';
        if (e.type === 'step') status.textContent = e.summary;
        if (e.type === 'site') {
          const tab=tabs.get(e.tab_id);if(tab){Object.assign(tab,{url:e.url,title:e.title,favicon:e.favicon});drawTabs();}
          document.dispatchEvent(new CustomEvent('raven-web-activity',{detail:{url:e.url,label:e.title}}));
        }
        if (e.type === 'tab') {
          if(e.action === 'closed') {tabs.delete(e.tab_id);handovers.delete(e.tab_id);showHandover();} else tabs.set(e.tab_id,{...e,focus_id:run+':'+e.tab_id});
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
          errorShown = true;
          status.textContent=window.ravenTransport.errorMessage(e);c.cancelTask({announce:false});c.appendMessage(status.textContent,'Raven');if(window.ravenTransport.demoMode)status.textContent='Ready';
        }
        if (e.type === 'done') {
          steps.stop();mode.disabled=false;
          stream.close();stream=null;run=null;stop.disabled=true;handovers.clear();showHandover();
          status.textContent=window.ravenTransport.demoMode ? (e.stop_reason === 'cancelled' ? 'Stopped' : 'Ready') : e.stop_reason === 'cancelled' ? 'Stopped' : e.stop_reason === 'agent_finished' ? 'Ready' : "I couldn't finish that: "+({max_total_input_tokens:'the research budget was reached',max_total_output_tokens:'the answer budget was reached',max_input_tokens:'the conversation became too long',error:'please try again'}[e.stop_reason] || 'the task ended before an answer was ready');
          if(!c.agentReply){
            c.cancelTask({announce:false});
            if(window.ravenTransport.demoMode && !errorShown && e.stop_reason !== 'cancelled')
              c.appendMessage(window.ravenTransport.errorMessage(e),'Raven');
          }
        }
      }, onError:error => {
        steps.stop();mode.disabled=false;
        const id=run;generation++;stream?.close();stream=null;run=null;stop.disabled=true;
        handovers.clear();showHandover();c.cancelTask({announce:false});
        status.textContent=window.ravenTransport.errorMessage(error);
        c.appendMessage(status.textContent,'Raven');if(window.ravenTransport.demoMode)status.textContent='Ready';
        if(id)post('/api/tasks/'+id+'/cancel').catch(()=>{});
      }});
    }).catch(e => {mode.disabled=false;status.textContent=window.ravenTransport.errorMessage(e);stop.disabled=true;c.cancelTask({announce:false});c.appendMessage(status.textContent,'Raven');if(window.ravenTransport.demoMode)status.textContent='Ready';});
    return true;
  };
  stop.onclick = async () => {
    steps.stop();mode.disabled=false;
    generation++;
    const id=run;run=null;stream?.close();stream=null;stop.disabled=true;handovers.clear();showHandover();
    const cancelled = id ? post('/api/tasks/'+id+'/cancel') : Promise.resolve();
    c.cancelTask({announce:false});status.textContent='Cancelled';
    try {await cancelled;} catch(e) {status.textContent=window.ravenTransport.errorMessage(e);}
  };
  document.querySelector('#handback').onclick = async () => {
    const tab = pendingTab;
    const button = document.querySelector('#handback');
    button.disabled=true;
    try {
      await post('/api/tasks/'+run+'/handback',{tab_id:tab,note:null});
      handovers.delete(tab);showHandover();status.textContent='Returned to Raven';
    } catch(e) {
      if(e.status===400 || e.status===404) {
        handovers.delete(tab);showHandover();status.textContent='That tab is no longer waiting for help. Raven can continue.';
      } else status.textContent='I couldn’t return the tab yet. Please try again.';
    }
    finally {button.disabled=false;}
  };
  window.addEventListener('pagehide',()=>{
    generation++;stream?.close();stream=null;
    const id=run;run=null;
    if(id){const url='/api/tasks/'+id+'/cancel';
      if(!navigator.sendBeacon?.(url,'{}'))fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}',keepalive:true}).catch(()=>{});
    }
  });
  fetch('/api/tabs').then(r=>r.json()).then(data=>{for(const t of data.tabs || [])tabs.set(t.tab_id,t);drawTabs();});
});

// Enter sends; Shift+Enter (or IME composition) keeps a newline.
document.getElementById('message-input')?.addEventListener('keydown', event => {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return;
  event.preventDefault();
  const send = document.getElementById('send-button');
  if (send && !send.disabled && event.target.value.trim()) event.target.form.requestSubmit();
});
