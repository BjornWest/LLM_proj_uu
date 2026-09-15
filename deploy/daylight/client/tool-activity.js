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
