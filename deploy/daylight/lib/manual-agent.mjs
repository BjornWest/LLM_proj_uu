// Model transport only. BrowserGym supplies policy observations and parses actions.
import {Agent,completionTokenLimit} from './agent.mjs';
const PROVIDERS=['chutes','dekallm','phala','parasail','akashml','ionstream','cloudflare'];
export function modelRequest(env,sessionID,messages){
  const model=env.MODEL_NAME||'qwen/qwen3.8-27b';
  if(model.startsWith('@preset/'))throw Error('Shared browser requires a model slug');
  return {model,session_id:sessionID,temperature:0,max_tokens:completionTokenLimit(env.OPENROUTER_MAX_TOKENS),stream:false,
    reasoning:{enabled:true},provider:{only:(env.OPENROUTER_PROVIDERS||PROVIDERS.join(',')).split(',').map(s=>s.trim()),allow_fallbacks:true,require_parameters:true,max_price:{prompt:0.5,completion:4,request:0}},
    response_format:{type:'json_schema',json_schema:{name:'browsergym_action',strict:true,schema:{type:'object',additionalProperties:false,required:['action'],properties:{action:{type:'string'}}}}},messages};
}
export async function infer({store,env,fetcher,sessionID,messages,signal,step,persist}){
  step.request=modelRequest(env,sessionID,messages);
  const bytes=Buffer.byteLength(JSON.stringify(step.request));
  if(bytes>100000)throw Error('Shared browser request exceeds input limit');
  const bound=(bytes+2048)*0.5/1e6+step.request.max_tokens*4/1e6;
  await persist();if(signal.aborted)return;
  step.reservation=await new Agent(store,{env}).reserve(bound);
  await persist();if(signal.aborted)return;
  step.dispatch_at=new Date().toISOString();await persist();if(signal.aborted){delete step.dispatch_at;await persist();return;}
  try{
    const response=await fetcher('https://openrouter.ai/api/v1/chat/completions',{method:'POST',headers:{Authorization:'Bearer '+env.OPENROUTER_API_KEY,'Content-Type':'application/json'},body:JSON.stringify(step.request),signal:AbortSignal.any([signal,AbortSignal.timeout(90000)])});
    step.http_status=response.status;step.response_text=await response.text();step.retry_after=response.headers.get('retry-after');
    try{step.response=JSON.parse(step.response_text);}catch{}
    step.usage=step.response?.usage??null;
    step.routing={session_id:sessionID,requested_model:step.request.model,resolved_model:step.response?.model??null,resolved_provider:step.response?.provider??null,cached_tokens:step.usage?.prompt_tokens_details?.cached_tokens??null};
    if(!response.ok)throw Error('OpenRouter returned HTTP '+response.status);
    const cost=step.usage?.cost;
    if(typeof cost!=='number'||!Number.isFinite(cost)||cost<0||cost>bound)throw Error('Missing or unexpected inference cost; stopped for review');
    step.output=step.response?.choices?.[0]?.message?.content;
    if(typeof step.output!=='string'||step.output.length>8192)throw Error('Invalid model action output');
  }catch(error){step.error=signal.aborted?'Interrupted during inference; billing may be unknown':String(error.message);throw error;}
  finally{step.finished_at=new Date().toISOString();await persist();}
}
