import test from 'node:test';
import assert from 'node:assert/strict';
import {checkStorage} from '../lib/storage-check.mjs';
import {StorageError} from '../lib/store.mjs';
function store(weak=false) {
  let value=null,revision=0;
  const strong=()=>`"etag-${revision}"`;
  return {
    async write(key,next,etag=null) {
      assert.match(key,/^daylight\/diagnostics\/test\//);
      if(etag!==(value?strong():null))throw new StorageError('BLOB_WRITE_CONFLICT','write');
      value=structuredClone(next);revision++;return strong();
    },
    async read(){return {value:structuredClone(value),etag:(weak?'W/':'')+strong()};},
  };
}
test('scratch check exercises create, read and chained conditional writes',async()=>{
  const report=await checkStorage(store(),'test');
  assert.equal(report.passed,true);assert.equal(report.checks.length,5);assert.equal(report.model_calls,0);
  assert.equal(report.checks[1].equals_create_etag,true);
});
test('scratch check isolates a mismatching read ETag without retry or weakening preconditions',async()=>{
  const report=await checkStorage(store(true),'test');
  assert.equal(report.passed,false);assert.equal(report.checks.length,3);
  assert.equal(report.checks[1].etag.weak,true);assert.equal(report.checks[1].equals_create_etag,false);
  assert.equal(report.checks[2].stage,'conditional_write_using_read_etag');
  assert.equal(report.checks[2].code,'BLOB_WRITE_CONFLICT');
});
