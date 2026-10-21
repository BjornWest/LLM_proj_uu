/* API adapter for the app-owned v40 controller. */
window.addEventListener('DOMContentLoaded', () => {
  const c = window.ravenChatDemo;
  const status = document.querySelector('#run-status');
  const stop = document.querySelector('#stop');
  const handover = document.querySelector('#handover');
  let history = [];
  const mode = document.querySelector('#browser-mode');
  const steps = new RavenSteps(document.querySelector('#chat-scene'));
  const append = c.appendMessage.bind(c);
  c.appendMessage = function(text, who, options) {
    append(text, who, options);
    if (who === 'Korp') { steps.finish(c.messages.lastElementChild); window.ravenAnswered?.(); }
  };
  let conversation = crypto.randomUUID();
  if (window.ravenModels) {
    const slot = document.createElement('div'); slot.className = 'controls';
    document.querySelector('#tabs').before(slot);
    window.ravenModels.mount(slot, {hasConversation: () => history.length > 0, currentConversation: () => conversation,
      newConversation: () => {
        if (run) return;
        history = []; conversation = crypto.randomUUID(); c.messages.replaceChildren(); steps.reset(); steps.stop();
        status.textContent = 'New conversation with ' + window.ravenModels.label(window.ravenModels.preferred());
      }});
    window.ravenMemory?.button(slot);
    slot.append(document.querySelector('#tabs'));  // visited/agent pages sit next to the model selector
  }
  // The send button doubles as Stop (a square) while Korp is working.
  const sendButton = document.querySelector('#send-button');
  const syncStop = () => {
    const running = !stop.disabled;
    sendButton.dataset.stop = running ? '1' : '';
    sendButton.title = running ? 'Stop' : '';
    sendButton.setAttribute('aria-label', running ? 'Stop' : 'Send message');
    if (running) sendButton.disabled = false;
  };
  // Thinking indicator inside the conversation (replaces the separate Ready/status line).
  let thinking = null, answered = false;
  window.ravenAnswered = () => { answered = true; thinking?.remove(); thinking = null;
    c.messages.querySelectorAll('.message.note').forEach(n => n.remove()); };  // progress notes give way to the answer
  let reasoning = '';
  const thinkingText = () => {
    if (reasoning) return reasoning;
    const t = status.textContent.trim();
    return !t || /^(Ready|Starting…|Researching…)$/.test(t) ? 'Thinking…' : t;
  };
  window.ravenReasoning = text => { reasoning = text || ''; syncThinking(); };
  window.ravenNote = text => {
    // Consecutive notes share one bubble (one line each) to keep the conversation compact.
    const before = thinking ? thinking.previousElementSibling : c.messages.lastElementChild;
    let note = before?.classList.contains('note') ? before : null;
    if (!note) {
      note = document.createElement('article'); note.className = 'message note';
      note.innerHTML = '<span class="message-label">Korp</span><div class="message-copy"></div>';
      if (thinking) c.messages.insertBefore(note, thinking); else c.messages.append(note);
    }
    const line = document.createElement('div'); line.textContent = text;
    note.querySelector('.message-copy').append(line);
    c.messages.scrollTop = c.messages.scrollHeight;
  };
  const syncThinking = () => {
    const running = !stop.disabled;
    if (!running) { answered = false; reasoning = ''; }
    if (running && !thinking && !answered) {
      thinking = document.createElement('article'); thinking.className = 'message thinking';
      thinking.innerHTML = '<span class="message-label">Korp</span><div class="message-copy"><span class="thinking-dots"><i></i><i></i><i></i></span><span class="thinking-text"></span></div>';
      c.messages.append(thinking);
    }
    if (!running && thinking) { thinking.remove(); thinking = null; }
    if (thinking) {
      thinking.querySelector('.thinking-text').textContent = thinkingText();
      c.messages.append(thinking);  // keep it last
      c.messages.scrollTop = c.messages.scrollHeight;
    }
  };
  new MutationObserver(() => { syncStop(); syncThinking(); }).observe(stop, {attributes: true, attributeFilter: ['disabled']});
  // The chat controller disables the send button while a task runs; as Stop it must stay clickable.
  new MutationObserver(() => { if (!stop.disabled && sendButton.disabled) sendButton.disabled = false; })
    .observe(sendButton, {attributes: true, attributeFilter: ['disabled']});
  new MutationObserver(syncThinking).observe(status, {childList: true, characterData: true, subtree: true});
  sendButton.addEventListener('click', event => {
    if (sendButton.dataset.stop !== '1') return;
    event.preventDefault(); event.stopImmediatePropagation(); stop.click();
  }, true);
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
      if(mode.value === 'background_window' ? tab.owner !== 'agent' : (tab.owner === 'agent' && !tab.focus_id)) continue;
      let site;try {site=new URL(tab.url);} catch {}
      button.textContent = site?.hostname.replace(/^www\./,'') || (tab.title || '').replace(/^\u{1F426}\u200D\u2B1B\s*/u, '') || 'New tab';
      if (site && ['http:','https:'].includes(site.protocol)) {
        const icon=document.createElement('img');icon.src=tab.favicon || site.origin+'/favicon.ico';icon.alt='';icon.width=14;icon.height=14;icon.onerror=()=>icon.remove();button.prepend(icon);
      }
      button.title = 'Show this tab: ' + tab.url;
      button.onclick = () => post('/api/tabs/'+encodeURIComponent(tab.focus_id || tab.tab_id)+'/focus')
        .then(() => { if (!run) status.textContent = 'Showing ' + button.textContent; })
        .catch(() => { tabs.delete(tab.tab_id); drawTabs(); status.textContent = 'That tab was closed.'; });
      root.append(button);
    }
  }
  c.input.placeholder = 'Ask Korp to explore the web…';
  c.updateHint = () => {};
  c.countdown.textContent = 'Your shared browser';
  // The raven stays perched, thinking, until Korp first acts on a page; a reply that comes first
  // (e.g. a follow-up question) is given from the perch without a flight.
  const originalLaunch = c.launch.bind(c);
  let held = null, flying = false;
  const thought = document.createElement('div');
  thought.className = 'thought'; thought.hidden = true; thought.setAttribute('aria-hidden', 'true');
  thought.innerHTML = '<i></i><i></i><b></b>';
  document.querySelector('#chat-scene').append(thought);
  const birdCanvas = document.querySelector('#raven-canvas');
  const placeThought = () => {
    if (held === null) { thought.hidden = true; return; }
    if (c.head) {
      thought.hidden = false;
      thought.style.left = (birdCanvas.offsetLeft + c.head.x) + 'px';
      thought.style.top = (birdCanvas.offsetTop + c.head.y) + 'px';
    }
    requestAnimationFrame(placeThought);
  };
  const answerFromPerch = () => {
    held = null;
    const message = c.agentReply.markdown;
    c.appendMessage(message, 'Korp', {sources: c.agentReply.sources || []});
    c.scene.dispatchEvent(new CustomEvent('raven-chat-reply', {detail: {message}, bubbles: true}));
    c.land(performance.now());
  };
  const takeOff = () => {
    flying = true;
    if (held === null) return;
    const replyMs = held; held = null;
    originalLaunch(replyMs);
    if (c.agentReply) c.reply();
  };
  c.launch = function(replyMs) {
    if (flying) { originalLaunch(replyMs); if (c.agentReply) c.reply(); return; }
    held = replyMs; requestAnimationFrame(placeThought);
    if (c.agentReply) answerFromPerch();
  };
  const originalCancel = c.cancelTask.bind(c);
  c.cancelTask = function(options) { held = null; flying = false; return originalCancel(options); };
  const originalStart = c.start.bind(c);
  c.start = function(options) {
    if (run) return false;
    const text = c.input.value.trim();
    const prior = history.slice();
    c.agentReply = null; held = null; flying = false;
    if (!originalStart(options)) return false;
    history.push({who:'You', text});
    steps.reset();mode.disabled=true;
    const token = ++generation;
    let errorShown = false;
    stop.disabled = false;
    status.textContent = 'Starting…';
    post('/api/tasks', {text, conversation_id:conversation, mode:mode.value, history:prior, model:window.ravenModels?.modelFor(conversation)}).then(data => {
      if (token !== generation) {post('/api/tasks/'+data.run_id+'/cancel');return;}
      run = data.run_id;
      tabs.clear();drawTabs();handovers.clear();showHandover();
      stream = window.ravenTransport.events(run, {onEvent:e => {
        if (token !== generation) return;
        steps.event(e);
        if (e.type === 'status') status.textContent = {starting:'Starting research…',working:'Researching…',finishing:'Preparing your answer…'}[e.state] || 'Researching…';
        if (e.type === 'step' || e.type === 'activity') status.textContent = e.summary;
        if (e.type === 'step' && e.page) takeOff();
        if (e.type === 'reasoning') window.ravenReasoning?.(e.text);
        if (e.type === 'note') window.ravenNote?.(e.text);
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
          c.agentReply=e;if(held!==null)answerFromPerch();else c.reply();history.push({who:'Korp',text:e.markdown});
          document.dispatchEvent(new CustomEvent('raven-web-activity',{detail:{status:'complete'}}));
        }
        if (e.type === 'error') {
          errorShown = true;
          status.textContent=window.ravenTransport.errorMessage(e);c.cancelTask({announce:false});c.appendMessage(status.textContent,'Korp');if(window.ravenTransport.demoMode)status.textContent='Ready';
        }
        if (e.type === 'done') {
          steps.stop();mode.disabled=false;
          stream.close();stream=null;run=null;stop.disabled=true;handovers.clear();showHandover();
          status.textContent=window.ravenTransport.demoMode ? (e.stop_reason === 'cancelled' ? 'Stopped' : 'Ready') : e.stop_reason === 'cancelled' ? 'Stopped' : e.stop_reason === 'agent_finished' ? 'Ready' : "I couldn't finish that: "+({max_total_input_tokens:'the research budget was reached',max_total_output_tokens:'the answer budget was reached',max_input_tokens:'the conversation became too long',error:'please try again'}[e.stop_reason] || 'the task ended before an answer was ready');
          if(!c.agentReply){
            c.cancelTask({announce:false});
            if(window.ravenTransport.demoMode && !errorShown && e.stop_reason !== 'cancelled')
              c.appendMessage(window.ravenTransport.errorMessage(e),'Korp');
          }
        }
      }, onError:error => {
        steps.stop();mode.disabled=false;
        const id=run;generation++;stream?.close();stream=null;run=null;stop.disabled=true;
        handovers.clear();showHandover();c.cancelTask({announce:false});
        status.textContent=window.ravenTransport.errorMessage(error);
        c.appendMessage(status.textContent,'Korp');if(window.ravenTransport.demoMode)status.textContent='Ready';
        if(id)post('/api/tasks/'+id+'/cancel').catch(()=>{});
      }});
    }).catch(e => {mode.disabled=false;status.textContent=window.ravenTransport.errorMessage(e);stop.disabled=true;c.cancelTask({announce:false});c.appendMessage(status.textContent,'Korp');if(window.ravenTransport.demoMode)status.textContent='Ready';});
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
      handovers.delete(tab);showHandover();status.textContent='Returned to Korp';
    } catch(e) {
      if(e.status===400 || e.status===404) {
        handovers.delete(tab);showHandover();status.textContent='That tab is no longer waiting for help. Korp can continue.';
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
  // Keep the page buttons in sync with the browser while idle (the user opens/closes tabs too).
  const refreshTabs = () => fetch('/api/tabs').then(r=>r.json()).then(data=>{
    if (run) return;
    tabs.clear(); for(const t of data.tabs || [])tabs.set(t.tab_id,t); drawTabs();
  }).catch(()=>{});
  refreshTabs(); setInterval(refreshTabs, 3000);
});

// Enter sends; Shift+Enter (or IME composition) keeps a newline.
document.getElementById('message-input')?.addEventListener('keydown', event => {
  if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return;
  event.preventDefault();
  const send = document.getElementById('send-button'), form = event.target.form;
  if (!send || !event.target.value.trim()) return;
  if (send.dataset.stop === '1') return;  // a run is active: the button is Stop, Enter must not stop or resend
  if (!send.disabled) { form.requestSubmit(); return; }
  // The raven is still landing after a reply: send as soon as the composer is ready (not during a run).
  if (!document.getElementById('stop')?.disabled) return;
  const started = Date.now();
  const timer = setInterval(() => {
    if (!send.disabled) { clearInterval(timer); if (event.target.value.trim()) form.requestSubmit(); }
    else if (Date.now() - started > 8000) clearInterval(timer);
  }, 150);
});
