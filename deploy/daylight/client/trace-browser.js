// Browser-specific extension of the pinned shared viewer. Read-only projection data.
import {renderToolReview,traceToolEvidence} from './tool-activity.js';
const element=(tag,text,className)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(className)node.className=className;return node;};
const parse=value=>{try{return typeof value==='string'?JSON.parse(value):value;}catch{return null;}};
export function allowedViewerAsset(value){
  if(typeof value!=='string')return false;
  try{const url=new URL(value,location.origin);return url.origin===location.origin&&/^(?:\/api\/library\/sessions\/[^/]+\/assets\/[^/]+|\/api\/harness\/jobs\/[a-f0-9-]{36}\/replay-assets\/[a-f0-9]{64})$/.test(url.pathname)&&!url.search&&!url.hash;}catch{return false;}
}
async function read(url){const response=await fetch(url,{credentials:'same-origin',redirect:'error'});if(!response.ok)throw Error(response.status===401?'Invitation expired':response.status===404?'Saved session unavailable':'Trace service unavailable');return response;}
const workerSource=()=>new URLSearchParams(location.search).get('source')==='harness';
const sessionURL=id=>workerSource()?'/api/harness/jobs/'+encodeURIComponent(id)+'/session'+(new URLSearchParams(location.search).has('episode')?'?episode='+encodeURIComponent(new URLSearchParams(location.search).get('episode')):''):'/api/library/sessions/'+encodeURIComponent(id);
let selectedResponse=null;
export async function loadViewerIndex(){
  // The embedded view opens one authorized session without downloading the catalog.
  const id=location.hash.slice(1);
  if((new URLSearchParams(location.search).get('embed')==='1'||workerSource())&&id&&id!=='latest'){
    const response=await read(sessionURL(id)),data=await response.json();
    selectedResponse={id,data};const {messages,...summary}=data;
    return new Response(JSON.stringify([{...summary,revision:response.headers.get('etag')||null}]));
  }
  if(workerSource())throw Error('Select a completed worker run.');
  const sessions=[];let cursor=null;
  for(let page=0;page<100;page++){
    const response=await read('/api/library/sessions'+(cursor?'?cursor='+encodeURIComponent(cursor):'')),value=await response.json();
    sessions.push(...(Array.isArray(value)?value:value.sessions||[]));
    if(!value.has_more)return new Response(JSON.stringify(sessions));
    if(!value.cursor||value.cursor===cursor)throw Error('Invalid library pagination');cursor=value.cursor;
  }
  throw Error('Library listing limit reached');
}
export async function loadViewerSession(id){
  if(selectedResponse?.id===id){const data=selectedResponse.data;selectedResponse=null;return new Response(JSON.stringify(data));}
  return read(sessionURL(id));
}
const short=(value,limit=160)=>{const text=typeof value==='string'?value:JSON.stringify(value);return text?.length>limit?text.slice(0,limit)+'…':text||'';};
function collectLabels(text,labels,refs){
  if(typeof text!=='string')return;
  const value=parse(text);
  const reset=()=>{labels.clear();refs.clear();labels.nodes=new Map();};
  if(value&&typeof value==='object'){
    if(value.document&&labels.document!==value.document){reset();labels.document=value.document;}
    labels.nodes??=new Map();
    const walk=(node,depth=0)=>{if(!node||typeof node!=='object'||depth>12)return;
      const old=typeof node.ref==='string'?labels.nodes.get(node.ref):null;
      if(node.removed){if(old?.bid!=null)labels.delete(String(old.bid));refs.delete(node.ref);labels.nodes.delete(node.ref);return;}
      const combined={...old,...node};
      if(typeof node.ref==='string')labels.nodes.set(node.ref,combined);
      if(combined.bid!=null&&typeof combined.name==='string'){
        if(combined.name)labels.set(String(combined.bid),combined.name);else labels.delete(String(combined.bid));
      }
      if(typeof node.ref==='string'&&typeof combined.name==='string'){
        if(combined.name)refs.set(node.ref,combined.name);else refs.delete(node.ref);
      }
      for(const child of Object.values(node))if(typeof child==='object')walk(child,depth+1);
    };walk(value);return;
  }
  // Legacy flat trees are complete snapshots, never merge reused numeric IDs.
  reset();labels.document=null;
  for(const line of text.split('\n')){const match=line.match(/^\s*\[([^\]]+)\]\s+\w+\s+'(.*)'(?:\s|$)/);if(match)labels.set(match[1],match[2]);}
}
function friendlyCall(name,args,labels,refs,fallback){
  if(!args||typeof args!=='object')return {title:fallback,detail:null};
  const target=labels.get(String(args.bid))||('control '+args.bid),quote=x=>'“'+short(x,120)+'”';
  switch(name){
    case 'fill':return {title:'Fill '+quote(target),detail:quote(args.value)};
    case 'select_option':return {title:'Choose '+quote(Array.isArray(args.options)?args.options.join(', '):args.options),detail:target};
    case 'click':return {title:'Click '+quote(target)};
    case 'check':return {title:'Enable '+quote(target)};
    case 'uncheck':return {title:'Disable '+quote(target)};
    case 'press':return {title:'Press '+args.key_comb,detail:target};
    case 'ax_read':return {title:'Read page structure',detail:(args.view||'children')+' · '+(refs.get(args.node_ref)||args.node_ref)};
    case 'ax_search':return {title:'Search page',detail:quote(args.query)};
    case 'ax_changes':return {title:'Check page changes'};
    case 'screenshot':return {title:'Inspect a screenshot'};
    case 'release_image':return {title:'Release image from context',detail:args.image_id};
    case 'scroll_into_view':return {title:'Bring '+quote(target)+' into view'};
    case 'scroll':return {title:'Scroll the page',detail:'Horizontal '+args.delta_x+' · vertical '+args.delta_y};
    case 'web_search':return {title:'Search the web',detail:quote(args.query)};
    case 'goto':return {title:'Open page',detail:short(args.url)};
    case 'go_back':return {title:'Go back'};
    case 'go_forward':return {title:'Go forward'};
    case 'reload':return {title:'Reload page'};
    case 'noop':return {title:'Wait',detail:args.wait_ms!=null?args.wait_ms+' ms':null};
    case 'spawn_agent':return {title:'Ask a helper',detail:short(args.task)};
    case 'wait_agent':return {title:'Wait for helper',detail:args.agent_id};
    case 'get_agent':return {title:'Check helper progress',detail:args.agent_id};
    case 'cancel_agent':return {title:'Stop helper',detail:args.agent_id};
    case 'send_msg_to_user':return {title:'Reply to user',answer:args.text};
    default:return {title:fallback};
  }
}
function resultSummary(result,status){
  if(status==='skipped')return 'Not executed · '+String(result?.reason||'batch stopped').replaceAll('_',' ');
  if(result?.error)return short(result.error,260);
  if(status==='failed')return 'Call failed. Earlier effects may still have occurred.';
  if(status==='unconfirmed')return 'Execution not confirmed in the recording.';
  if(result?.released)return 'Image released; notes retained.';
  if(result?.image_id&&result?.width)return 'Captured '+result.width+' × '+result.height+' viewport.';
  if(Array.isArray(result?.items))return result.items.length+' page entries returned'+(result.next_offset!=null?' · more available':'')+'.';
  return 'Call completed'+(result?.positioning?.status?' · '+result.positioning.status.replaceAll('_',' '):'')+'.';
}
export function browserProjection(session){
  const steps=new Map();
  for(const message of session.messages||[]){
    if(message.turn==null)continue;
    if(!steps.has(message.turn))steps.set(message.turn,{turn:message.turn,messages:[],observations:[],tools:[]});
    const step=steps.get(message.turn);step.messages.push(message);
    if(message.observation_role)step.observations.push(message);
    if(message.kind==='tool')step.tools.push(message);
  }
  const labels=new Map(),refs=new Map();
  return [...steps.values()].map(step=>{
    const prompt=step.messages.find(m=>m.kind==='prompt'&&['retained_request_input','actual_outbound_input'].includes(m.provenance));
    const request=prompt?parse(prompt.text):null;
    const inventory=traceToolEvidence([{id:session.id,steps:[{request:request&&!Array.isArray(request)?request:{}}]}])[0];
    const observation=step.observations.find(m=>m.observation_role==='selected');
    // Selected public observations and previously returned AX results only.
    // Labels are for display, never an inference about agent intent.
    if(observation)collectLabels(observation.text,labels,refs);
    const response=parse(step.messages.find(m=>m.title==='Raw model response')?.text);
    const message=response?.choices?.[0]?.message;
    const native=new Map((message?.tool_calls||[]).map(c=>[c.id,c]));
    const transition=step.messages.find(m=>m.kind==='result'&&m.title==='Browser transition');
    const calls=step.tools.map(tool=>{
      const returned=step.messages.find(m=>m.kind==='result'&&m.tool_call_id&&m.tool_call_id===tool.tool_call_id);
      const evidence=returned?parse(returned.text):transition?parse(transition.text):null;
      const result=evidence?.result??evidence?.policy_feedback??evidence;
      const selectedCall=native.get(tool.tool_call_id)||(step.tools.length===1&&native.size===1?[...native.values()][0]:null);
      const name=selectedCall?.function?.name||(typeof tool.text==='string'?tool.text.match(/^\s*([A-Za-z_]\w*)\s*\(/)?.[1]:null);
      const args=parse(selectedCall?.function?.arguments);
      const status=tool.execution_status==='skipped'?'skipped':tool.status==='error'||transition?.status==='error'?'failed':['completed','returned'].includes(tool.status)?'recorded':'unconfirmed';
      const friendly=friendlyCall(name,args,labels,refs,tool.text||tool.title);
      if(['ax_read','ax_search','ax_changes'].includes(name)&&result)collectLabels(JSON.stringify(result),labels,refs);
      return {name,...friendly,action:tool.text,arguments:args,status,tool_call_id:tool.tool_call_id,batch_call:tool.batch_call,
        observation:observation?{text:observation.text}:null,result,
        resultSummary:resultSummary(result,status),attachments:tool.attachments||[],
        receipt:evidence?{description:'Recorded execution evidence',result:evidence}:null};
    });
    const reasoning=(Array.isArray(message?.reasoning_details)?message.reasoning_details.filter(r=>typeof r.text==='string').map(r=>r.text).join('\n\n'):null)||message?.reasoning||message?.reasoning_content||null;
    const update=step.observations.find(m=>m.observation_role==='consolidated');
    // This update is current for the next decision, not earlier calls in this turn.
    if(update)collectLabels(update.text,labels,refs);
    return {...step,...inventory,browserReview:true,key:session.id+':'+step.turn,label:'Turn '+(Number(step.turn)+1),
      at:step.tools[0]?.at||prompt?.at||null,calls,reasoning,
      reasoningRecorded:!!reasoning||!!message?.reasoning_details?.length,
      agentText:typeof message?.content==='string'?message.content.trim():null,
      error:step.messages.find(m=>m.title==='Step error')?.text||null,
      consolidated:update,events:step.messages.find(m=>m.title?.startsWith('Consolidated batch events'))};
  });
}
function detail(parent,title,text,className='browser-review-detail'){
  const node=element('details',undefined,className);node.append(element('summary',title),element('pre',typeof text==='string'?text:JSON.stringify(text,null,2)));parent.append(node);return node;
}
function renderBrowserTimeline(timeline,steps,session){
  timeline.replaceChildren();
  const calls=steps.flatMap(s=>s.calls),requests=steps.filter(s=>s.messages.some(m=>m.kind==='prompt')).length;
  const completed=calls.filter(c=>c.status==='recorded').length,failed=calls.filter(c=>c.status==='failed').length,skipped=calls.filter(c=>c.status==='skipped').length;
  const intro=element('div',undefined,'browser-review-overview');intro.append(element('strong',requests+' model turns · '+calls.length+' tool calls'),element('p',completed+' completed · '+failed+' failed · '+skipped+' skipped. Tool completion is separate from task grading.','muted'));
  const goal=session.messages.find(m=>m.title==='Recorded policy goal')?.text;
  if(goal&&!goal.startsWith('Goal not separately'))intro.append(element('p',goal,'browser-review-goal'));
  timeline.append(intro);
  for(const step of steps){
    if(!step.calls.length&&!step.reasoningRecorded&&!step.agentText&&!step.error)continue;
    const group=element('section',undefined,'browser-review-turn');group.dataset.turn=String(step.turn);
    const heading=element('div',undefined,'browser-review-heading');heading.append(element('h3',step.label),element('span',step.calls.length+' call'+(step.calls.length===1?'':'')+(step.calls.length>1?' · sequential batch':''),'muted'));group.append(heading);
    if(step.reasoningRecorded)detail(group,'Recorded reasoning',step.reasoning||'Only opaque reasoning data was recorded. See the raw response.','browser-review-reasoning');
    if(step.agentText)detail(group,'Agent message',step.agentText);
    if(step.error)group.append(element('p',step.error,'browser-review-error'));
    if(!step.calls.length)group.append(element('p','No tool execution recorded for this turn.','muted'));
    for(const call of step.calls){
      const card=element('article',undefined,'browser-review-call');card.dataset.state=call.status;
      const header=element('div',undefined,'browser-review-call-heading');header.append(element('strong',call.title),element('span',({recorded:'Completed',failed:'Failed',skipped:'Skipped',unconfirmed:'Unconfirmed'})[call.status],'browser-review-status'));card.append(header);
      if(call.detail)card.append(element('p',call.detail,'browser-review-argument'));
      if(call.answer&&call.status==='recorded'){card.classList.add('browser-review-answer');card.append(element('div',call.answer,'browser-review-answer-text'));}
      else card.append(element('p',call.resultSummary,'browser-review-result'));
      if(call.attachments.length){const images=element('details',undefined,'browser-review-images');images.append(element('summary','Screenshots'));for(const asset of call.attachments){if(!asset.image||!allowedViewerAsset(asset.url))continue;const item=element('figure'),img=element('img');img.loading='lazy';img.alt=asset.label;img.src=asset.url;item.append(element('figcaption',asset.label),img);images.append(item);}if(images.children.length>1)card.append(images);}
      detail(card,'Raw call and result',{action:call.action,arguments:call.arguments,receipt:call.receipt});group.append(card);
    }
    if(step.consolidated)detail(group,'Page changes after this turn',step.consolidated.text);
    if(step.events)detail(group,'Page events during this turn',parse(step.events.text)??step.events.text);
    timeline.append(group);
  }
}
export function createBrowserExtension({jumpToMessage}){
  let current=null,steps=[],position=0,mode='conversation',timer=null;
  const chat=document.getElementById('chat'),main=document.getElementById('main');
  const recorded=element('section',undefined,'browser-recorded-outcome');recorded.hidden=true;chat.before(recorded);
  const outputReview=element('section',undefined,'browser-output-review');chat.before(outputReview);
  const rawRecords=element('details',undefined,'browser-raw-records');rawRecords.append(element('summary','Full message records'));chat.before(rawRecords);rawRecords.append(chat);
  const replay=element('section',undefined,'browser-replay');replay.hidden=true;replay.setAttribute('aria-label','Recorded browser replay');
  const controls=element('div',undefined,'browser-replay-controls'),previous=element('button','← Previous'),play=element('button','Play steps'),next=element('button','Next →');
  for(const button of [previous,play,next])button.type='button';
  const select=element('select');select.setAttribute('aria-label','Recorded browser step');
  const slider=element('input');slider.type='range';slider.min='0';slider.setAttribute('aria-label','Replay step position');
  const phase=element('select');phase.setAttribute('aria-label','Recorded observation type');
  const phaseLabel=element('label','Recorded page state','browser-replay-observation');phaseLabel.append(phase);
  const phaseHelp=element('p',undefined,'muted browser-replay-observation-help');phaseHelp.id='replay-observation-help';phase.setAttribute('aria-describedby',phaseHelp.id);
  controls.append(previous,play,next,select,slider,phaseLabel,phaseHelp);
  const status=element('p',undefined,'muted');status.setAttribute('role','status');
  const stage=element('div',undefined,'browser-replay-stage'),picture=element('img');picture.alt='Recorded browser screenshot';picture.loading='lazy';
  const missing=element('p',undefined,'muted');stage.append(picture,missing);
  const action=element('pre',undefined,'browser-replay-action'),inspect=element('button','Inspect this step’s messages');inspect.type='button';
  const observation=element('details'),observationText=element('pre');observation.append(element('summary','Exact recorded observation text'),observationText);
  replay.append(element('p','Saved screenshots and actions. Playback advances one recorded step per second; it does not run the browser.','muted'),controls,status,stage,action,inspect,observation);chat.before(replay);
  function stop(){clearInterval(timer);timer=null;play.textContent='Play steps';}
  function showStep(){
    const step=steps[position];previous.disabled=position===0;next.disabled=!step||position>=steps.length-1;play.disabled=steps.length<2;select.value=String(position);slider.value=String(position);slider.disabled=steps.length<2;
    phase.replaceChildren();
    for(const [index,item] of (step?.observations||[]).entries()){const option=element('option',item.observation_role==='selected'?'Decision observation':item.observation_role==='transition'?'Transition · separate from decision input':item.observation_role==='consolidated'?'Page update for next turn':'Final recorded observation');option.value=String(index);phase.append(option);}
    const selected=step?.observations.findIndex(item=>item.observation_role==='selected');phase.value=String(selected>=0?selected:0);phaseLabel.hidden=phaseHelp.hidden=!step?.observations.length;
    status.textContent=step?'Step '+step.turn+' · '+(position+1)+' / '+steps.length:'No recorded browser steps available.';
    action.textContent=step?.tools.map(tool=>tool.text).join('\n')||'No browser action recorded at this step.';
    inspect.disabled=!step?.messages.length;const inventory=main.querySelector('.trace-tool-decision');if(step&&inventory&&inventory.value!==step.key){inventory.value=step.key;inventory.dispatchEvent(new Event('change'));}showObservation();
  }
  function showObservation(){
    const observation=steps[position]?.observations[Number(phase.value)],asset=observation?.attachments?.find(item=>item.image&&allowedViewerAsset(item.url));
    picture.hidden=!asset;missing.hidden=!!asset;
    if(asset){picture.src=asset.url;picture.alt=observation.title+' · step '+steps[position].turn;}else{picture.removeAttribute('src');missing.textContent='No screenshot recorded for this observation.';}
    observationText.textContent=observation?.text||'No observation text recorded.';
    phaseHelp.textContent=({selected:'Page state recorded for this turn’s decision.',transition:'Page state immediately after an action; it may differ from the next decision’s input.',consolidated:'Page update saved after this turn for a possible next model request. Another request may not have been sent.',final:'The last recorded page state.'})[observation?.observation_role]||'';
  }
  function move(index){position=Math.min(Math.max(0,index),Math.max(0,steps.length-1));showStep();}
  function showMode(value){mode=value;outputReview.hidden=value!=='conversation';rawRecords.hidden=value!=='conversation';document.body.dataset.browserView=value;replay.hidden=value!=='replay';if(value!=='replay')stop();
    const panel=main.querySelector('.trace-tools-panel');if(!panel)return;
    const timeline=panel.querySelector('.trace-tool-timeline');chat.hidden=value!=='conversation';timeline.hidden=value!=='tools';
    const buttons=panel.querySelectorAll('.trace-view-toggle button');buttons.forEach((button,index)=>button.setAttribute('aria-pressed',String(index===['conversation','tools','replay'].indexOf(value))));
    if(value==='replay')showStep();
  }
  previous.onclick=()=>{stop();move(position-1);};next.onclick=()=>{stop();move(position+1);};select.onchange=()=>{stop();move(Number(select.value));};slider.oninput=()=>{stop();move(Number(slider.value));};phase.onchange=showObservation;
  play.onclick=()=>{if(timer){stop();return;}if(position>=steps.length-1)move(0);play.textContent='Pause';timer=setInterval(()=>{if(position>=steps.length-1)stop();else move(position+1);},1000);};
  inspect.onclick=()=>{showMode('conversation');rawRecords.open=true;jumpToMessage(steps[position].messages[0].id);};
  picture.onerror=()=>{picture.hidden=true;missing.hidden=false;missing.textContent='This recorded screenshot could not be loaded.';};
  document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();});window.addEventListener('pagehide',stop);
  const embed=new URLSearchParams(location.search).get('embed')==='1';document.body.classList.toggle('viewer-embedded',embed);
  function resize(){if(embed&&window.parent!==window)window.parent.postMessage({type:'trace-viewer:size',height:Math.ceil(main.getBoundingClientRect().height+main.offsetTop)},location.origin);}
  new ResizeObserver(resize).observe(main);
  return {update(session){
    if(current===session)return;current=session;stop();
    recorded.replaceChildren();recorded.hidden=!session?.worker_trace;
    if(session?.worker_trace){
      const trace=session.worker_trace;
      if(session.family_sessions?.length>1){
        const family=element('nav');family.setAttribute('aria-label','Agent conversations');
        for(const [index,member] of session.family_sessions.entries()){
          if(!/^[a-f0-9]{20}$/.test(member.episode_id))continue;
          const link=element('a',(member.relationship==='root'?'Parent conversation':'Helper '+index)+(member.selected?' (selected)':''));
          const url=new URL(location.href);url.searchParams.set('episode',member.episode_id);link.href=url.pathname+url.search+url.hash;
          link.style.marginRight='1rem';family.append(link);
        }
        recorded.append(family);
      }
      recorded.append(element('p','Recorded worker run · '+(session.library_metadata?.execution_status||'Unknown status')+' · no grading recomputed.','muted'));
      if(trace.error)recorded.append(element('pre',typeof trace.error==='string'?trace.error:JSON.stringify(trace.error),'browser-replay-action'));
      const verdict=element('details');verdict.append(element('summary','Recorded final evaluation'),element('pre',JSON.stringify(session.library_metadata?.evaluation??null,null,2)));recorded.append(verdict);
      if(trace.id===session.id&&/^[a-f0-9-]{36}$/.test(trace.id)){const link=element('a','Download unchanged original trace ZIP');link.href='/api/harness/jobs/'+trace.id+'/trace';recorded.append(link);}
    }
    steps=session?browserProjection(session):[];position=0;mode='conversation';
    const browser=session?.environment==='browsergym';document.body.classList.toggle('browser-project',browser);
    if(!browser){delete document.body.dataset.browserView;replay.hidden=true;outputReview.hidden=true;rawRecords.hidden=false;rawRecords.open=true;main.querySelector('.trace-tools-panel')?.remove();chat.hidden=false;return;}
    main.querySelector('.trace-tools-panel')?.remove();
    renderToolReview(chat,steps);
    outputReview.before(main.querySelector('.trace-tools-panel'));
    rawRecords.open=false;rawRecords.querySelector('summary').textContent='Full message records · '+session.messages.length+' events';
    renderBrowserTimeline(outputReview,steps,session);
    outputReview.prepend(element('h2','Agent outputs'),element('p','Recorded reasoning, actions and replies by model turn. Full request and response records remain below.','muted'));
    const rawLink=element('button','Show full message records');rawLink.type='button';rawLink.onclick=()=>{rawRecords.open=true;rawRecords.scrollIntoView({behavior:'smooth'});};outputReview.prepend(rawLink);
    const inventory=main.querySelector('.trace-tool-decision');inventory.addEventListener('change',()=>{const index=steps.findIndex(step=>step.key===inventory.value);if(mode==='replay'&&index>=0&&index!==position){stop();move(index);}});
    const toggle=main.querySelector('.trace-view-toggle'),buttons=toggle.querySelectorAll('button');
    buttons[0].addEventListener('click',()=>showMode('conversation'));buttons[1].addEventListener('click',()=>showMode('tools'));
    const replayButton=element('button','Replay');replayButton.type='button';replayButton.onclick=()=>showMode('replay');toggle.append(replayButton);
    // Keep project controls above both the shared message renderer and replay.
    main.querySelector('.trace-tools-panel').after(replay);
    select.replaceChildren();steps.forEach((step,index)=>{const option=element('option','Step '+step.turn);option.value=String(index);select.append(option);});slider.max=String(Math.max(0,steps.length-1));
    showMode(new URLSearchParams(location.search).get('view')==='tools'?'tools':'conversation');resize();
  }};
}
