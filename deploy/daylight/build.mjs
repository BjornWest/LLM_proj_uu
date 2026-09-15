import {mkdir,readFile,writeFile,copyFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import path from 'node:path';
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
  .replace('</head>','<link rel="stylesheet" href="/assets/tool-activity.css"></head>')
  .replace('<script src="/assets/dashboard.js"></script>','<script type="module" src="/assets/dashboard.js"></script>');
await writeFile('private-assets/index.html',html);
let site=await readFile(path.join(source,'site.js'),'utf8');
site=site.replace(/async function action\(type,data=\{\}\)\{[^\n]+\}/,
  "async function action(type,data={}){try{state=window.parent.demoWorld.action({type,...data});render()}catch(e){alert(e.message)}}")
  .replace("fetch(endpoint).then(r=>r.json()).then(s=>{state=s;render()});",'state=window.parent.demoWorld.public();render();');
await writeFile('private-assets/site.js',site);
for(const file of ['dashboard.js','world.js','observation.js','fixture.json','harness.html','harness.js','harness.css','workspace.html','workspace.js','workspace.css','tool-activity.js','tool-activity.css']) await copyFile('client/'+file,'private-assets/'+file);
const files=['index.html','style.css','site.html','rooms.js','site.js','dashboard.js','world.js','observation.js','fixture.json','harness.html','harness.js','harness.css','workspace.html','workspace.js','workspace.css','tool-activity.js','tool-activity.css'];
const hashes={};for(const file of files)hashes[file]=createHash('sha256').update(await readFile('private-assets/'+file)).digest('hex');
const server={};for(const file of ['api/index.mjs','lib/agent.mjs','lib/auth.mjs','lib/store.mjs','lib/storage-check.mjs','lib/harness.mjs','lib/activity.mjs','../../config/team_tasks.json','../../config/team_sites.json','package-lock.json','build.mjs'])server[file]=createHash('sha256').update(await readFile(file)).digest('hex');
await writeFile('private-assets/provenance.json',JSON.stringify({runtime:'daylight-client-demo-v1',commit:process.env.VERCEL_GIT_COMMIT_SHA||null,assets:hashes,server},null,2));
console.log('Built private assets; public/ contains only robots.txt.');
