import test from 'node:test';
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';

// Import from a different cwd, as with a preserved monorepo function bundle.
function probe(options='{}') {
  const script=`
    import {createHandler} from ${JSON.stringify(new URL('../api/index.mjs',import.meta.url).href)};
    import {config,digest,login,sessionCookie} from ${JSON.stringify(new URL('../lib/auth.mjs',import.meta.url).href)};
    const env={DEMO_SESSION_SECRET:'s'.repeat(64),DEMO_INVITES_JSON:JSON.stringify({test:digest('a'.repeat(43))})};
    const handler=createHandler({env,...${options}});
    const cookie=sessionCookie(login('a'.repeat(43),config(env)));
    for(const url of ['/','/assets/fixture.json','/api/config']) {
      const res={setHeader(){},end(value){console.log(JSON.stringify({url,status:this.statusCode,body:String(value)}));}};
      await handler({method:'GET',url,headers:{host:'demo.example',cookie}},res);
    }
  `;
  const child=spawnSync(process.execPath,['--input-type=module','-e',script],{
    cwd:fileURLToPath(new URL('../../../',import.meta.url)),encoding:'utf8'});
  assert.equal(child.status,0,child.stderr);
  return {rows:child.stdout.trim().split('\n').map(JSON.parse),stderr:child.stderr};
}
test('authenticated pages and provenance load from repository-root working directory',()=>{
  const {rows}=probe();
  assert.deepEqual(rows.map(r=>r.status),[200,200,200]);
  assert.match(rows[0].body,/Daylight/);
  assert.ok(JSON.parse(rows[1].body).rooms.length);
  assert.equal(JSON.parse(rows[2].body).owner,'test');
});
test('missing deployment assets return a specific safe diagnostic',()=>{
  const {rows,stderr}=probe("{assetRoot:'/nonexistent-private-daylight-assets'}");
  for(const row of rows) {
    assert.equal(row.status,503);
    assert.equal(JSON.parse(row.body).code,'PRIVATE_ASSETS_UNAVAILABLE');
    assert.ok(!row.body.includes('/nonexistent'));
  }
  assert.equal(stderr.trim().split('\n').length,3);
  for(const line of stderr.trim().split('\n'))assert.deepEqual(JSON.parse(line),{
    event:'daylight_request_failed',code:'PRIVATE_ASSETS_UNAVAILABLE',stage:'private_assets',missing_file:true});
});
