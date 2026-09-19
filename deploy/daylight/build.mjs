import {mkdir,readFile,writeFile,copyFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import path from 'node:path';
import {prepareViewer} from './prepare-viewer.mjs';
const source=path.resolve('../../environments/demo');
await mkdir('private-assets',{recursive:true});await mkdir('public',{recursive:true});
// Vercel rejects an empty output directory. This contains no application data;
// all demo pages, scripts, API routes and traces remain behind the function.
await writeFile('public/robots.txt','User-agent: *\nDisallow: /\n');
for (const file of ['style.css','site.html','rooms.js']) await copyFile(path.join(source,file),'private-assets/'+file);
let html=await readFile(path.join(source,'index.html'),'utf8');
html=html.replace('Local browser demo','Private team demo').replace('Fictional local website','Fictional website')
  .replace('http://localhost:8878','#').replace('<option value="rehearsal">Scripted rehearsal</option><option value="live" disabled>Live agent</option>','<option value="live">Live agent</option>')
  .replace('<span>Daylight demo</span>','<a href="/harness">Test research harness</a> · <a href="/logout">Sign out</a>')
  .replace('<link rel="stylesheet" href="/assets/style.css">','<link rel="stylesheet" href="/assets/style.css"><link rel="stylesheet" href="/assets/tool-activity.css">')
  .replace('<script src="/assets/dashboard.js"></script>','<script type="module" src="/assets/dashboard.js"></script>');
await writeFile('private-assets/index.html',html);
let site=await readFile(path.join(source,'site.js'),'utf8');
site=site.replace(/async function action\(type,data=\{\}\)\{[^\n]+\}/,
  "async function action(type,data={}){try{state=window.parent.demoWorld.action({type,...data});render()}catch(e){alert(e.message)}}")
  .replace("fetch(endpoint).then(r=>r.json()).then(s=>{state=s;render()});",'state=window.parent.demoWorld.public();render();');
await writeFile('private-assets/site.js',site);
for(const file of ['dashboard.js','world.js','observation.js','fixture.json','harness.html','harness.js','harness.css','workspace.html','workspace.js','workspace.css','tool-activity.js','tool-activity.css','inspection.js','inspection.css']) await copyFile('client/'+file,'private-assets/'+file);
const inspectionNames=['full'];
const inspectionRoot=path.resolve('../../environments/inspection_full');
const inspectionManifest=JSON.parse(await readFile(path.join(inspectionRoot,'manifest.json'),'utf8'));
const siteTasks=JSON.parse(await readFile('../../config/team_tasks.json','utf8')).tasks;
if(siteTasks.some(t=>t.build&&t.site_revision!==inspectionManifest.site_revision))throw Error('Client and worker registry site revisions differ');
for(const [file,expected] of Object.entries(inspectionManifest.files)){
 if(!/^(index\.html|darkpattern\.svg|(?:assets|external-assets)\/[a-zA-Z0-9_.-]+)$/.test(file))throw Error('Invalid inspection asset path');
 const raw=await readFile(path.join(inspectionRoot,'dist',file));
 if(createHash('sha256').update(raw).digest('hex')!==expected)throw Error('Inspection source hash mismatch: '+file);
 const dest=path.join('private-assets/inspection-full/dist',file);await mkdir(path.dirname(dest),{recursive:true});await writeFile(dest,raw);
}
await copyFile(path.join(inspectionRoot,'manifest.json'),'private-assets/inspection-full/manifest.json');
// Frozen answer-free review projection only; private graders are never bundled.
const catalogSource='../../data/curation/expansion/hosted-review-catalog.json';
const catalogRaw=await readFile(catalogSource);
if(createHash('sha256').update(catalogRaw).digest('hex')!=='ff5dc3550ed053a9f8c3c7bdd7fe3b375416a219c49fef9c52d58994edbe97f4')throw Error('Review catalog changed; review and pin an explicit new revision');
const catalog=JSON.parse(catalogRaw);
if(catalog.schema!=='browser-task-review-catalog-v1'||catalog.tasks.length!==203||catalog.tasks.some(t=>t.execution_available!==false))throw Error('Invalid review-only catalog');
await writeFile('private-assets/task-catalog.json',catalogRaw);
const viewerFiles=await prepareViewer(path.resolve('private-assets'));
const files=['task-catalog.json',...viewerFiles,'index.html','style.css','site.html','rooms.js','site.js','dashboard.js','world.js','observation.js','fixture.json','harness.html','harness.js','harness.css','workspace.html','workspace.js','workspace.css','tool-activity.js','tool-activity.css','inspection.js','inspection.css',...inspectionNames.map(name=>'inspection-'+name+'/manifest.json')];
const hashes={};for(const file of files)hashes[file]=createHash('sha256').update(await readFile('private-assets/'+file)).digest('hex');
const server={};for(const file of [catalogSource,'api/index.mjs','lib/agent.mjs','lib/auth.mjs','lib/store.mjs','lib/remote-store.mjs','lib/manual-client.mjs','lib/library-client.mjs','prepare-viewer.mjs','vendor/agent_trace/provenance.json','lib/storage-check.mjs','lib/harness.mjs','lib/activity.mjs','lib/inspection.mjs','../../config/team_tasks.json','../../config/team_sites.json','package-lock.json','build.mjs'])server[file]=createHash('sha256').update(await readFile(file)).digest('hex');
await writeFile('private-assets/provenance.json',JSON.stringify({runtime:'daylight-client-demo-v1',commit:process.env.VERCEL_GIT_COMMIT_SHA||null,assets:hashes,server},null,2));
console.log('Built private assets; public/ contains only robots.txt.');
