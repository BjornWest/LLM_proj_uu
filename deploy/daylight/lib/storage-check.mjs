// Isolated authenticated diagnostic. Never reads a trace/budget or calls a model.
import {randomUUID,createHash} from 'node:crypto';
import {StorageError} from './store.mjs';
const etagInfo=value=>({present:typeof value==='string'&&value.length>0,
  weak:typeof value==='string'&&value.startsWith('W/'),
  quoted:typeof value==='string'&&value.startsWith('"'),
  sha256:typeof value==='string'?createHash('sha256').update(value).digest('hex'):null});
export async function checkStorage(store,owner) {
  const id=randomUUID(),key=`daylight/diagnostics/${owner}/${id}.json`;
  const report={id,model_calls:0,scope:'Isolated scratch object; no trace or budget changes',checks:[]};
  // Larger than typical compression thresholds, unlike the original tiny probe.
  const padding='Synthetic study-room availability. '.repeat(512);
  report.payload_bytes=Buffer.byteLength(padding);
  let stage='create';
  try {
    const initial={diagnostic:id,revision:0,padding};
    const created=await store.write(key,initial);
    report.checks.push({stage,passed:true,etag:etagInfo(created)});
    stage='read_after_create';
    const read=await store.read(key);
    if(!read)throw Error('read_missing');
    report.checks.push({stage,passed:JSON.stringify(read.value)===JSON.stringify(initial),
      etag:etagInfo(read.etag),equals_create_etag:read.etag===created});
    if(!report.checks.at(-1).passed)throw Error('read_mismatch');
    stage='conditional_write_using_read_etag';
    const updated=await store.write(key,{diagnostic:id,revision:1,padding},read.etag);
    report.checks.push({stage,passed:true,etag:etagInfo(updated)});
    stage='conditional_write_using_put_etag';
    const finished=await store.write(key,{diagnostic:id,revision:2,padding},updated);
    report.checks.push({stage,passed:true,etag:etagInfo(finished)});
    stage='read_after_updates';
    const final=await store.read(key);
    const passed=final?.value.revision===2&&final?.value.diagnostic===id;
    report.checks.push({stage,passed,etag:etagInfo(final?.etag),equals_last_put_etag:final?.etag===finished});
    report.passed=passed;
  } catch(error) {
    report.passed=false;
    report.checks.push({stage,passed:false,code:error instanceof StorageError?error.code:'DIAGNOSTIC_CHECK_FAILED'});
  }
  return report;
}
