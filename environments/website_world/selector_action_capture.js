// Private, opt-in retained-document observer. No DOM or user-state writes.
export function selectorJournal(controlToken, maximumEvents=256) {
  const documentToken=crypto.randomUUID();
  let phase='setup', target=null, rows=[], faults=[], active=null, started=0, initial=null, previous=null;
  const copy=value=>JSON.parse(JSON.stringify(value));
  const fault=message=>{if(faults.length<32)faults.push(message);};
  const equal=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
  const freeze=value=>{if(value&&typeof value==='object'){Object.values(value).forEach(freeze);Object.freeze(value);}return value;};
  function begin(token, pageId, initialSelection) {
    if(token!==controlToken||phase!=='setup'||typeof pageId!=='string'||!pageId)
      throw new Error('Selector recorder baseline is invalid or already active');
    target=pageId;rows=[];faults=[];phase='policy';
    initial=copy(initialSelection);previous=copy(initialSelection);
    return {documentToken,phase,pageId,initialSelection:copy(initialSelection)};
  }
  function before(pageId,axis,value,selection) {
    if(phase!=='policy')return null;
    try {
      if(active!==null){fault('Reentrant selector handler');return null;}
      if(!equal(selection,previous))fault('Unobserved selector change before handler');
      active={page_id:pageId,axis,requested_value:value,before:copy(selection),
              started_at:performance.now(),sequence:started++};
      return active;
    }
    catch(error){fault('Unable to capture the actual selector baseline');return null;}
  }
  function after(event,selection,failed) {
    if(phase!=='policy'||event===null)return;
    try {
      if(event!==active){fault('Unpaired selector transition');return;}
      if(failed)fault('Original selector handler threw');
      if(event.page_id!==target)fault('Selector action used another product page');
      if(rows.length>=maximumEvents){fault('Selector journal overflow');return;}
      rows.push({...event,after:copy(selection),finished_at:performance.now()});
      previous=copy(selection);
    } catch(error){fault('Unable to capture the actual selector outcome');}
    finally {active=null;}
  }
  function seal(token,finalSelection) {
    if(token!==controlToken||phase!=='policy')throw new Error('Selector recorder cannot seal twice or without baseline');
    if(active!==null||started!==rows.length)fault('Selector transition was not fully observed');
    if(!equal(previous,finalSelection))fault('Unobserved final selection');
    phase='sealed';
    return freeze({documentToken,pageId:target,initialSelection:copy(initial),finalSelection:copy(finalSelection),
      complete:faults.length===0,events:copy(rows),faults:[...faults]});
  }
  return Object.freeze({begin,before,after,seal});
}
