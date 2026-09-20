// Presentation only: these entries never become model conversation messages.
const labels = {running:'Running',saving:'Saving record',applied:'Applied',failed:'Failed',unrecorded:'Record not saved'};
const element = (tag, className, text) => {
  const el = document.createElement(tag); el.className = className;
  if (text !== undefined) el.textContent = text;
  return el;
};
export function createToolActivity(action, captured, step) {
  // Resolve the target against this exact pre-action snapshot, never the latest DOM.
  const control = captured.observation.controls.find(item => item.id === action.id);
  const target = control?.label || (action.id ? 'Control ' + action.id : 'Page');
  const verb = {click:'Click',select:'Select',check:action.value ? 'Check' : 'Uncheck',fill:'Fill'}[action.action] || action.action;
  const value = action.action === 'select' || action.action === 'fill' ? String(action.value ?? '') : null;
  const title = verb + ' · ' + target + (value === null ? '' : ' → ' + value);
  const root = element('details', 'tool-activity'); root.dataset.step = String(step);
  const summary = element('summary', 'tool-activity-summary');
  const icon = element('span', 'tool-activity-icon', '↗'); icon.setAttribute('aria-hidden', 'true');
  const heading = element('span', 'tool-activity-heading');
  heading.append(element('span', 'tool-activity-label', 'Browser tool · Step ' + step), element('span', 'tool-activity-title', title));
  const status = element('span', 'tool-activity-status');
  summary.append(icon, heading, status);
  const body = element('div', 'tool-activity-details');
  body.append(element('p', 'tool-activity-context', 'Page before action: ' + (captured.observation.title || 'Title not recorded')),
    element('pre', 'tool-activity-action', JSON.stringify(action, null, 2)));
  const note = element('p', 'tool-activity-note'); body.append(note); root.append(summary, body);
  function update(state, error = '') {
    root.dataset.state = state; status.textContent = labels[state];
    note.textContent = error || (state === 'applied' ? 'The browser applied this action and saved its record. Task grading is separate.'
      : state === 'saving' ? 'The browser returned from the action. Saving its record…' : 'Using the target from this step’s recorded observation.');
    summary.title = title + ' · ' + labels[state];
  }
  update('running');
  return {element:root, update};
}
export function keepChatPosition(log, change) {
  const follow = log.scrollHeight - log.scrollTop - log.clientHeight < 64;
  const top = log.scrollTop; change();
  log.scrollTop = follow ? log.scrollHeight : top;
}
export function showChatWorking(log, text) {
  keepChatPosition(log, () => {
    let status = log.querySelector('.chat-working');
    if (!text) { status?.remove(); return; }
    if (!status) { status = element('div', 'chat-working'); log.append(status); }
    status.textContent = text;
  });
}

export function bindChatEnter(textarea, sendButton) {
  textarea.addEventListener('keydown', event => {
    if (event.key !== 'Enter' || event.shiftKey || event.isComposing || event.keyCode === 229 || event.ctrlKey || event.altKey || event.metaKey) return;
    event.preventDefault();
    if (!event.repeat && !textarea.disabled && !sendButton.disabled && textarea.value.trim()) textarea.form.requestSubmit(sendButton);
  });
}

export class TurnInterrupted extends Error {}
export class InterruptibleTurn {
  constructor(api) {
    this.api=api;this.id=null;this.stopped=false;this.failure=null;
    this.signal=new Promise(resolve=>{this.signalStop=resolve;});
    this.done=new Promise(resolve=>{this.finish=resolve;});
  }
  check(){if(this.stopped)throw new TurnInterrupted('Interrupted by a new message');}
  wait(operation){this.check();return Promise.race([operation,this.signal.then(()=>{throw new TurnInterrupted('Interrupted by a new message');})]);}
  async start(body){this.check();this.starting=this.api('/api/start',body).then(value=>{this.id=value.id;return value;});return this.starting;}
  async interrupt(){
    this.stopped=true;this.signalStop();
    try{
      if(this.starting)await this.starting;
      // Leave dispatched inference running so the backend can retain its response
      // and cost. Its decision is suppressed, never executed by this client.
      if(this.id)this.interruptStatus=(await this.api('/api/interrupt',{id:this.id})).status;
    }finally{await this.done;}
    if(this.failure)throw this.failure;
    return this.id;
  }
}
export function interruptionNotice(text='Interrupted by your new message.') {
  const notice=element('div','run-interruption',text);notice.setAttribute('role','status');return notice;
}

// Saved conversation presentation only. All content is text, never uploaded HTML.
export function transcriptBubble(role,label,text){
  const bubble=element('article','transcript-bubble '+role);
  bubble.append(element('strong','transcript-label',label),element('div','transcript-text',text));return bubble;
}
export function transcriptDetail(parent,label,text){
  const detail=element('details','transcript-detail');detail.append(element('summary','',label),element('pre','',text));parent.append(detail);return detail;
}
export function renderTraceConversation(container,traces){
  container.replaceChildren();
  for(const trace of traces){
    const separator=element('div','transcript-turn');separator.dataset.trace=trace.id;
    separator.append(element('span','',new Date(trace.created_at).toLocaleString()+' · '+(trace.status||'Status unknown')));
    const link=element('a','','Original turn record ↗');link.href='/api/traces/'+encodeURIComponent(trace.id);separator.append(link);container.append(separator);
    container.append(transcriptBubble('user',trace.mode==='task'?'Task objective':'You',trace.goal||'No request recorded.'));
    for(const [index,step] of (trace.steps||[]).entries()){
      const action=step.action,receipt=step.client_result;
      const control=step.observation?.controls?.find(row=>row.id===action?.id);
      const description=action?[action.action,control?.label||action.id,action.value!==undefined&&action.value!==null?String(action.value):''].filter(Boolean).join(' · '):'';
      const rawOutput=step.output||step.response?.choices?.[0]?.message?.content;
      const output=action?.action==='done'?action.message:action?description:rawOutput;
      if(output){
        const label=step.error?'Daylight · output rejected':trace.interruption&&!receipt?'Daylight · interrupted output':action?.action==='done'&&!receipt?'Daylight · answer receipt missing':action?.action==='done'||trace.mode==='chat'?'Daylight':'Daylight · decision '+(index+1);
        const bubble=transcriptBubble('assistant',label,typeof output==='string'?output:JSON.stringify(output,null,2));
        if(action&&rawOutput)transcriptDetail(bubble,'Exact model output',typeof rawOutput==='string'?rawOutput:JSON.stringify(rawOutput,null,2));
        if(step.error)bubble.append(element('p','transcript-note',step.error));container.append(bubble);
      }
      if(action&&action.action!=='done'){
        const status=receipt?receipt.error?'Failed':'Applied · receipt saved':'No execution receipt';
        const bubble=transcriptBubble('tool','Browser tool · Step '+(index+1)+' · '+status,description);
        if(receipt?.description&&receipt.description!==description)bubble.append(element('p','transcript-note',receipt.description));if(receipt?.error)bubble.append(element('p','transcript-note',receipt.error));
        if(step.observation)transcriptDetail(bubble,'Page before this decision',step.observation.text||'No text observation recorded.');
        if(receipt?.page_after)transcriptDetail(bubble,'Page after this action · transition feedback',receipt.page_after.text||'No text observation recorded.');
        transcriptDetail(bubble,'Exact action and receipt',JSON.stringify({action,receipt:receipt??null},null,2));container.append(bubble);
      }
      if(step.error&&!output)container.append(element('p','transcript-turn','Step '+(index+1)+' stopped: '+step.error));
    }
    if(trace.interruption)container.append(element('p','transcript-turn','This turn was interrupted. Recorded model output is not evidence that an action was applied.'));
    else if(!(trace.steps||[]).some(step=>step.output||step.action||step.response))container.append(element('p','transcript-turn','No model response was recorded for this turn.'));
  }
  renderToolReview(container,traceToolEvidence(traces));
}

// Evidence-derived display data; never infer the available set from actions taken.
export function traceToolEvidence(traces){
  return traces.flatMap((trace,turn)=> (trace.steps||[]).map((step,index)=>{
    const request=step.request||{},schema=request.response_format?.json_schema?.schema;
    const enums=schema?.properties?.action?.enum;
    let available=null,source=null;
    if(Array.isArray(request.tools)){
      available=request.tools.map(tool=>({name:tool.function?.name||tool.name,description:tool.function?.description||tool.description||'',definition:tool})).filter(tool=>typeof tool.name==='string');
      source='Recorded request.tools';
    }else if(Array.isArray(enums)){
      available=enums.filter(name=>typeof name==='string').map(name=>({name,description:name==='done'?'Return an answer; no browser action.':'',definition:schema}));
      source='Recorded structured action schema';
    }
    const action=step.action,receipt=step.client_result;
    const control=step.observation?.controls?.find(row=>row.id===action?.id);
    const calls=action&&action.action!=='done'?[{name:action.action,title:[action.action,control?.label||action.id,action.value!=null?String(action.value):''].filter(Boolean).join(' · '),action,receipt,observation:step.observation,status:receipt?receipt.error?'failed':'recorded':'unconfirmed'}]:[];
    if(!action)for(const call of step.response?.choices?.[0]?.message?.tool_calls||[]){
      const name=call.function?.name||call.name;
      if(typeof name==='string')calls.push({name,title:name,action:call,receipt:null,status:'unconfirmed'});
    }
    return {key:trace.id+':'+index,label:'Turn '+(turn+1)+' · Step '+(index+1),at:step.requested_at||null,available,source,selected:action?.action||calls[0]?.name||null,calls};
  }));
}
export function renderJobToolReview(container,job){
  const decisions=(job.steps||[]).map(step=>({key:job.id+':'+step.step,label:'Step '+step.step,at:null,available:null,source:null,
    calls:step.action?[{name:null,title:typeof step.action==='string'?step.action:JSON.stringify(step.action),action:step.action,receipt:{browser_stepped:step.browser_stepped??null,error:step.error??null},status:step.error?'failed':step.browser_stepped?'recorded':'unconfirmed'}]:[]}));
  renderToolReview(container,decisions);
}
export function renderToolReview(container,decisions){
  const old=container.parentElement?.querySelector('.trace-tools-panel');
  const previousMode=old?.dataset.mode||'conversation',previousSelection=old?.querySelector('select')?.value,wasOpen=old?.querySelector('.trace-toolbox')?.open||false;
  const panel=element('section','trace-tools-panel'),toolbar=element('div','trace-view-toolbar');panel.dataset.mode=previousMode;
  const toggle=element('div','trace-view-toggle');toggle.setAttribute('role','group');toggle.setAttribute('aria-label','Trace display');
  const conversation=element('button','','Conversation'),toolsOnly=element('button','','Tools only');conversation.type=toolsOnly.type='button';toggle.append(conversation,toolsOnly);toolbar.append(toggle);
  const toolbox=element('details','trace-toolbox'),summary=element('summary','','Available tools');toolbox.open=wasOpen;toolbox.append(summary);
  const inventory=element('div','trace-tool-inventory'),select=element('select','trace-tool-decision');select.setAttribute('aria-label','Available tools at recorded step');
  for(const decision of decisions){const option=element('option','',decision.label);option.value=decision.key;select.append(option);}
  if(decisions.some(decision=>decision.key===previousSelection))select.value=previousSelection;
  const source=element('p','transcript-note'),cards=element('div','trace-tool-cards');inventory.append(select,source,cards);toolbox.append(inventory);toolbar.append(toolbox);panel.append(toolbar);
  const timeline=element('div','trace-tool-timeline'),events=decisions.flatMap(decision=>decision.calls.map(call=>({decision,call})));
  timeline.append(element('p','transcript-note',events.length+' recorded tool event'+(events.length===1?'':'s')+' · chronological order. Missing execution evidence is marked unconfirmed.'));
  const list=element('ol','trace-tool-events');list.setAttribute('aria-label','Chronological tool activity');
  for(const [index,{decision,call}] of events.entries()){
    const item=element('li','trace-tool-event');item.dataset.state=call.status;
    item.append(element('span','trace-tool-number',String(index+1)));
    const body=element('div','trace-tool-event-body');
    const stepButton=element('button','trace-tool-event-step',decision.label+(decision.at?' · '+new Date(decision.at).toLocaleTimeString():''));stepButton.type='button';stepButton.title='Show tools available at this step';stepButton.onclick=()=>{select.value=decision.key;toolbox.open=true;showAvailable();select.focus({preventScroll:true});};
    body.append(stepButton,element('strong','',call.title));
    body.append(element('p','trace-tool-state',call.status==='failed'?'Failed':call.status==='skipped'?'Skipped · not executed':call.status==='recorded'?'Execution recorded':'Execution unconfirmed'));
    if(call.detail)body.append(element('p','trace-tool-argument',call.detail));
    if(call.answer&&call.status==='recorded')body.append(element('p','trace-tool-answer',call.answer));
    if(call.resultSummary)body.append(element('p','transcript-note',call.resultSummary));
    if(!call.resultSummary&&call.receipt?.description)body.append(element('p','transcript-note',call.receipt.description));
    if(call.receipt?.error)body.append(element('p','transcript-note',String(call.receipt.error)));
    if(call.observation)transcriptDetail(body,'Page before this decision',call.observation.text||'No page text recorded.');
    if(call.receipt?.page_after)transcriptDetail(body,'Page after action · transition feedback',call.receipt.page_after.text||'No page text recorded.');
    transcriptDetail(body,'Exact recorded action and execution evidence',JSON.stringify({action:call.action,receipt:call.receipt??null},null,2));
    item.append(body);list.append(item);
  }
  if(!events.length)timeline.append(element('p','trace-tools-empty','No tool calls are recorded in this conversation.'));
  timeline.append(list);panel.append(timeline);
  function showMode(mode){panel.dataset.mode=mode;const onlyTools=mode==='tools';container.hidden=onlyTools;timeline.hidden=!onlyTools;conversation.setAttribute('aria-pressed',String(!onlyTools));toolsOnly.setAttribute('aria-pressed',String(onlyTools));}
  conversation.onclick=()=>showMode('conversation');toolsOnly.onclick=()=>showMode('tools');
  function showAvailable(){
    const decision=decisions.find(row=>row.key===select.value);cards.replaceChildren();select.hidden=!decisions.length;
    const available=decision?.available;summary.textContent='Available tools · '+(available===null||available===undefined?'not recorded':available.length);
    source.textContent=available==null?'Tool definitions are not present in the published request data for this step. Actions taken do not establish which other tools were available.':decision.source+'. Definitions offered at this step; usable targets depend on the page.';
    for(const tool of available||[]){
      const selected=decision.selected===tool.name||decision.calls.some(call=>call.name===tool.name),card=element('div','trace-tool-card');card.dataset.selected=String(selected);
      card.append(element('strong','',tool.name),element('span','trace-tool-card-state',selected?'Selected at this step':'Available'));
      if(tool.description)card.append(element('p','transcript-note',String(tool.description)));
      transcriptDetail(card,'Recorded definition',JSON.stringify(tool.definition,null,2));cards.append(card);
    }
    if(available?.length===0)cards.append(element('p','trace-tools-empty','This request explicitly lists no tools.'));
  }
  select.onchange=showAvailable;showAvailable();showMode(previousMode);
  if(old)old.replaceWith(panel);else container.before(panel);
}

export function groupTraceSessions(rows){
  const byID=new Map(rows.map(row=>[row.id,row])),parent=new Map(rows.map(row=>[row.id,row.id]));
  const root=id=>{while(parent.get(id)!==id)id=parent.get(id);return id;};
  const join=(a,b)=>{a=root(a);b=root(b);if(a!==b)parent.set(b,a);};
  const sessions=new Map();
  for(const row of rows){
    if(row.conversation_id){const earlier=sessions.get(row.conversation_id);if(earlier)join(earlier,row.id);else sessions.set(row.conversation_id,row.id);}
    const previous=row.previous_trace_id;
    if(previous&&byID.has(previous))join(previous,row.id);
  }
  const groups=new Map();for(const row of rows){const key=root(row.id);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(row);}
  return [...groups.values()].map(group=>group.sort((a,b)=>(Date.parse(a.created_at)||0)-(Date.parse(b.created_at)||0)||a.id.localeCompare(b.id)));
}

// Full viewport layout, preserving the live iframe and chat state.
export function createFullScreenMode(enterButton, exitButton, onChange = () => {}) {
  let active = false;
  const documents = new WeakSet();
  const escape = event => {
    if (active && event.key === 'Escape') { event.preventDefault(); setActive(false); }
  };
  function setActive(value, {focus = true} = {}) {
    if (active === value) return;
    active = value; document.body.classList.toggle('site-fullscreen', active);
    enterButton.setAttribute('aria-pressed', String(active)); exitButton.hidden = !active;
    onChange(active);
    if (focus) (active ? exitButton : enterButton).focus({preventScroll:true});
  }
  enterButton.addEventListener('click', () => setActive(true));
  exitButton.addEventListener('click', () => setActive(false));
  window.addEventListener('keydown', escape, true);
  function bindFrame(frame) {
    const listen = () => {
      // Keyboard events inside an iframe do not bubble to the outer page.
      const doc = frame.contentDocument;
      if (doc && !documents.has(doc)) { documents.add(doc); doc.addEventListener('keydown', escape, true); }
    };
    frame.addEventListener('load', listen); listen();
  }
  return {setActive, bindFrame, get active() { return active; }};
}
