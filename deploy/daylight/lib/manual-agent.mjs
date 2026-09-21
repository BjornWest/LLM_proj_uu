// Model transport only. BrowserGym supplies policy observations and parses actions.
import {createHash} from 'node:crypto';
import {Agent,completionTokenLimit} from './agent.mjs';
const PROVIDERS=['chutes','dekallm','phala','parasail','akashml','ionstream','cloudflare'];
export function modelRequest(env,sessionID,messages,decision=null){
  const model=env.MODEL_NAME||'qwen/qwen3.8-27b';
  if(model.startsWith('@preset/'))throw Error('Shared browser requires a model slug');
  const native=decision?.protocol==='native-core-v1';
  if(native&&(!Array.isArray(decision.native_options?.tools)||!decision.session_id))throw Error('Missing core policy tools/session');
  return {model,session_id:native?decision.session_id:sessionID,temperature:0,max_tokens:completionTokenLimit(env.OPENROUTER_MAX_TOKENS),stream:false,
    reasoning:{enabled:true},provider:{only:(env.OPENROUTER_PROVIDERS||PROVIDERS.join(',')).split(',').map(s=>s.trim()),allow_fallbacks:true,require_parameters:true,max_price:{prompt:0.5,completion:4,request:0}},
    ...(native?Object.fromEntries(['tools','tool_choice','parallel_tool_calls'].filter(k=>Object.hasOwn(decision.native_options,k)).map(k=>[k,decision.native_options[k]])):{response_format:{type:'json_schema',json_schema:{name:'browsergym_action',strict:true,schema:{type:'object',additionalProperties:false,required:['action'],properties:{action:{type:'string'}}}}}}),messages};
}
export async function infer({store,env,fetcher,sessionID,messages,signal,step,persist}){
  step.request=modelRequest(env,sessionID,messages,step.decision);
  const bytes=Buffer.byteLength(JSON.stringify(step.request));
  if(bytes>(step.decision?.protocol==='native-core-v1'?1000000:100000))throw Error('Shared browser request exceeds input limit');
  const bound=(bytes+2048)*0.5/1e6+step.request.max_tokens*4/1e6;
  await persist();if(signal.aborted)return;
  step.reservation=await new Agent(store,{env}).reserve(bound);
  await persist();if(signal.aborted){step.budget_settlement=await new Agent(store,{env}).settle(step.reservation,{cost:0,not_sent:true});await persist();return;}
  step.dispatch_at=new Date().toISOString();await persist();if(signal.aborted){delete step.dispatch_at;step.budget_settlement=await new Agent(store,{env}).settle(step.reservation,{cost:0,not_sent:true});await persist();return;}
  try{
    const response=await fetcher('https://openrouter.ai/api/v1/chat/completions',{method:'POST',headers:{Authorization:'Bearer '+env.OPENROUTER_API_KEY,'Content-Type':'application/json'},body:JSON.stringify(step.request),signal:AbortSignal.any([signal,AbortSignal.timeout(90000)])});
    step.http_status=response.status;step.response_text=await response.text();step.retry_after=response.headers.get('retry-after');
    try{step.response=JSON.parse(step.response_text);}catch{}
    step.usage=step.response?.usage??null;
    step.routing={session_id:step.request.session_id,requested_model:step.request.model,resolved_model:step.response?.model??null,resolved_provider:step.response?.provider??null,cached_tokens:step.usage?.prompt_tokens_details?.cached_tokens??null};
    if(!response.ok)throw Error('OpenRouter returned HTTP '+response.status);
    const cost=step.usage?.cost;
    if(typeof cost!=='number'||!Number.isFinite(cost)||cost<0||cost>bound)throw Error('Missing or unexpected inference cost; stopped for review');
    step.output=step.response?.choices?.[0]?.message?.content;
    if(step.decision?.protocol!=='native-core-v1'&&(typeof step.output!=='string'||step.output.length>8192))throw Error('Invalid model action output');
  }catch(error){
    step.error=signal.aborted?'Interrupted during inference; billing may be unknown':String(error.message);
    // The core runner decides recovery; every new attempt still reserves here.
    if(step.decision?.protocol==='native-core-v1'&&!signal.aborted&&[408,429,500,502,503,504].includes(step.http_status))return;
    throw error;
  }
  finally{
    step.finished_at=new Date().toISOString();
    // Save the provider evidence even if settlement/storage fails.
    await persist();
    step.budget_settlement=await new Agent(store,{env}).settle(step.reservation,{
      cost:typeof step.usage?.cost==='number'&&Number.isFinite(step.usage.cost)&&step.usage.cost>=0?step.usage.cost:null,
      response_id:step.response?.id??null,response_sha256:step.response_text==null?null:createHash('sha256').update(step.response_text).digest('hex')});
    await persist();
  }
}
