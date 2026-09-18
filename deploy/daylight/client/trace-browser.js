// Browser-specific extension of the pinned shared viewer. Read-only projection data.
import {renderToolReview,traceToolEvidence} from './tool-activity.js';
const element=(tag,text,className)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(className)node.className=className;return node;};
const parse=value=>{try{return typeof value==='string'?JSON.parse(value):value;}catch{return null;}};
export function allowedViewerAsset(value){
  if(typeof value!=='string')return false;
  try{const url=new URL(value,location.origin);return url.origin===location.origin&&/^\/api\/library\/sessions\/[^/]+\/assets\/[^/]+$/.test(url.pathname)&&!url.search&&!url.hash;}catch{return false;}
}
async function read(url){const response=await fetch(url,{credentials:'same-origin',redirect:'error'});if(!response.ok)throw Error(response.status===401?'Invitation expired':response.status===404?'Saved session unavailable':'Trace service unavailable');return response;}
let selectedResponse=null;
export async function loadViewerIndex(){
  // The embedded view opens one authorized session without downloading the catalog.
  const id=location.hash.slice(1);
  if(new URLSearchParams(location.search).get('embed')==='1'&&id&&id!=='latest'){
    const response=await read('/api/library/sessions/'+encodeURIComponent(id)),data=await response.json();
    selectedResponse={id,data};const {messages,...summary}=data;
    return new Response(JSON.stringify([{...summary,revision:response.headers.get('etag')||null}]));
  }
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
  return read('/api/library/sessions/'+encodeURIComponent(id));
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
  return [...steps.values()].map(step=>{
    const prompt=step.messages.find(m=>m.kind==='prompt'&&['retained_request_input','actual_outbound_input'].includes(m.provenance));
    const request=prompt?parse(prompt.text):null;
    const inventory=traceToolEvidence([{id:session.id,steps:[{request:request&&!Array.isArray(request)?request:{}}]}])[0];
    const observation=step.observations.find(m=>m.observation_role==='selected');
    const transition=step.messages.find(m=>m.kind==='result'&&m.title==='Browser transition');
    const calls=step.tools.map(tool=>({name:typeof tool.text==='string'?tool.text.match(/^\s*([A-Za-z_]\w*)\s*\(/)?.[1]||null:null,title:tool.text||tool.title,action:tool.text,
      status:tool.status==='error'||transition?.status==='error'?'failed':tool.status==='returned'?'recorded':'unconfirmed',
      observation:observation?{text:observation.text}:null,
      receipt:transition?{description:'Recorded browser transition',result:parse(transition.text)??transition.text}:null}));
    return {...step,...inventory,key:session.id+':'+step.turn,label:'Step '+step.turn,at:step.tools[0]?.at||prompt?.at||null,calls};
  });
}
export function createBrowserExtension({jumpToMessage}){
  let current=null,steps=[],position=0,mode='conversation',timer=null;
  const chat=document.getElementById('chat'),main=document.getElementById('main');
  const replay=element('section',undefined,'browser-replay');replay.hidden=true;replay.setAttribute('aria-label','Recorded browser replay');
  const controls=element('div',undefined,'browser-replay-controls'),previous=element('button','← Previous'),play=element('button','Play steps'),next=element('button','Next →');
  for(const button of [previous,play,next])button.type='button';
  const select=element('select');select.setAttribute('aria-label','Recorded browser step');
  const slider=element('input');slider.type='range';slider.min='0';slider.setAttribute('aria-label','Replay step position');
  const phase=element('select');phase.setAttribute('aria-label','Recorded observation type');
  controls.append(previous,play,next,select,slider,phase);
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
    for(const [index,item] of (step?.observations||[]).entries()){const option=element('option',item.observation_role==='selected'?'Decision observation':item.observation_role==='transition'?'Transition · separate from decision input':'Final recorded observation');option.value=String(index);phase.append(option);}
    const selected=step?.observations.findIndex(item=>item.observation_role==='selected');phase.value=String(selected>=0?selected:0);phase.hidden=!step?.observations.length;
    status.textContent=step?'Step '+step.turn+' · '+(position+1)+' / '+steps.length:'No recorded browser steps available.';
    action.textContent=step?.tools.map(tool=>tool.text).join('\n')||'No browser action recorded at this step.';
    inspect.disabled=!step?.messages.length;const inventory=main.querySelector('.trace-tool-decision');if(step&&inventory&&inventory.value!==step.key){inventory.value=step.key;inventory.dispatchEvent(new Event('change'));}showObservation();
  }
  function showObservation(){
    const observation=steps[position]?.observations[Number(phase.value)],asset=observation?.attachments?.find(item=>item.image&&allowedViewerAsset(item.url));
    picture.hidden=!asset;missing.hidden=!!asset;
    if(asset){picture.src=asset.url;picture.alt=observation.title+' · step '+steps[position].turn;}else{picture.removeAttribute('src');missing.textContent='No screenshot recorded for this observation.';}
    observationText.textContent=observation?.text||'No observation text recorded.';
  }
  function move(index){position=Math.min(Math.max(0,index),Math.max(0,steps.length-1));showStep();}
  function showMode(value){mode=value;document.body.dataset.browserView=value;replay.hidden=value!=='replay';if(value!=='replay')stop();
    const panel=main.querySelector('.trace-tools-panel');if(!panel)return;
    const timeline=panel.querySelector('.trace-tool-timeline');chat.hidden=value!=='conversation';timeline.hidden=value!=='tools';
    const buttons=panel.querySelectorAll('.trace-view-toggle button');buttons.forEach((button,index)=>button.setAttribute('aria-pressed',String(index===['conversation','tools','replay'].indexOf(value))));
    if(value==='replay')showStep();
  }
  previous.onclick=()=>{stop();move(position-1);};next.onclick=()=>{stop();move(position+1);};select.onchange=()=>{stop();move(Number(select.value));};slider.oninput=()=>{stop();move(Number(slider.value));};phase.onchange=showObservation;
  play.onclick=()=>{if(timer){stop();return;}if(position>=steps.length-1)move(0);play.textContent='Pause';timer=setInterval(()=>{if(position>=steps.length-1)stop();else move(position+1);},1000);};
  inspect.onclick=()=>{showMode('conversation');jumpToMessage(steps[position].messages[0].id);};
  picture.onerror=()=>{picture.hidden=true;missing.hidden=false;missing.textContent='This recorded screenshot could not be loaded.';};
  document.addEventListener('visibilitychange',()=>{if(document.hidden)stop();});window.addEventListener('pagehide',stop);
  const embed=new URLSearchParams(location.search).get('embed')==='1';document.body.classList.toggle('viewer-embedded',embed);
  function resize(){if(embed&&window.parent!==window)window.parent.postMessage({type:'trace-viewer:size',height:Math.ceil(main.getBoundingClientRect().height+main.offsetTop)},location.origin);}
  new ResizeObserver(resize).observe(main);
  return {update(session){
    if(current===session)return;current=session;stop();steps=session?browserProjection(session):[];position=0;mode='conversation';
    const browser=session?.environment==='browsergym';document.body.classList.toggle('browser-project',browser);
    if(!browser){delete document.body.dataset.browserView;replay.hidden=true;main.querySelector('.trace-tools-panel')?.remove();chat.hidden=false;return;}
    renderToolReview(chat,steps);
    const inventory=main.querySelector('.trace-tool-decision');inventory.addEventListener('change',()=>{const index=steps.findIndex(step=>step.key===inventory.value);if(mode==='replay'&&index>=0&&index!==position){stop();move(index);}});
    const toggle=main.querySelector('.trace-view-toggle'),buttons=toggle.querySelectorAll('button');
    buttons[0].addEventListener('click',()=>showMode('conversation'));buttons[1].addEventListener('click',()=>showMode('tools'));
    const replayButton=element('button','Replay');replayButton.type='button';replayButton.onclick=()=>showMode('replay');toggle.append(replayButton);
    // Keep project controls above both the shared message renderer and replay.
    main.querySelector('.trace-tools-panel').after(replay);
    select.replaceChildren();steps.forEach((step,index)=>{const option=element('option','Step '+step.turn);option.value=String(index);select.append(option);});slider.max=String(Math.max(0,steps.length-1));
    showMode('conversation');resize();
  }};
}
