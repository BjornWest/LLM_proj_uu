// Derived local Chaos fixture: serialize original UI events, never replay clicks.
export function createStageQueue({send,onOutcome=()=>{},onError=()=>{}}) {
  let tail=Promise.resolve(),closed=false,reason=null,sequence=0;
  const log=[];
  const record=(phase,id,event,extra={})=>log.push({phase,id,kind:event?.kind,target:event?.target,
    timestamp:Date.now(),...extra});
  function close(why='unmounted') {if(!closed){closed=true;reason=why;}}
  async function callback(fn,value,name,id,event) {
    try {await fn(value);} catch {
      record('callback_failed',id,event,{callback:name});
      close('callback_failed:'+name);
    }
  }
  function emit(input) {
    const id=sequence++,event=JSON.parse(JSON.stringify(input));
    record('queued',id,event);
    const operation=tail.then(async()=>{
      if(closed){record('discarded',id,event,{reason});return {dispatched:false,reason};}
      record('dispatched',id,event);
      let result;
      try {result=await send(event);} catch {
        record('failed',id,event);
        if(!closed){close('request_failed');await callback(onError,undefined,'onError',id,event);}
        return {dispatched:true,error:true};
      }
      record('completed',id,event,{outcome:result?.outcome??null});
      if(closed)return {dispatched:true,ignored_after_close:true};
      if(['success','failure','rejected','skipped'].includes(result?.outcome))close('terminal:'+result.outcome);
      await callback(onOutcome,result,'onOutcome',id,event);
      return {dispatched:true,result};
    });
    // Transport and callback failures are contained separately. A closed queue
    // discards subsequent events, without retrying any dispatched operation.
    tail=operation;
    return operation;
  }
  return {emit,close,drain:()=>tail,snapshot:()=>({version:'stage-fifo-v2',closed,reason,events:log.map(e=>({...e}))})};
}
