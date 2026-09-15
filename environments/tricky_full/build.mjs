// Build the complete pinned upstream application, never a task-selected subtree.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import {build} from 'vite';
import vm from 'node:vm';
import {instrument} from './instrument.mjs';
const root=path.resolve(import.meta.dirname,'../..'),local=path.join(root,'.local/tricky-full-v1');
const source=JSON.parse(fs.readFileSync(path.join(local,'source-manifest.json'))),site=path.join(local,'site');
const sha=x=>crypto.createHash('sha256').update(x).digest('hex');
fs.rmSync(site,{recursive:true,force:true});fs.mkdirSync(site,{recursive:true});
for(const [name,pin] of Object.entries(source.files)){
 const data=fs.readFileSync(path.join(local,'upstream',name));if(sha(data)!==pin.sha256)throw Error('Source mismatch '+name);
 const dest=path.join(site,name);fs.mkdirSync(path.dirname(dest),{recursive:true});fs.writeFileSync(dest,data);
}
if(!fs.existsSync(path.join(site,'node_modules')))fs.symlinkSync(path.join(root,'environments/tricky_full/node_modules'),path.join(site,'node_modules'),'dir');
const patches=[];
function patch(file,before,after,reason){
 const p=path.join(site,file),s=fs.readFileSync(p,'utf8');if(s.split(before).length!==2)throw Error('Patch anchor drift '+file+': '+before);
 fs.writeFileSync(p,s.replace(before,after));patches.push({file,before,after,reason});
}
patch('src/App.jsx','import { Analytics } from "@vercel/analytics/react"','', 'Disable upstream-owner telemetry in isolated deployments; no visible component removed.');
patch('src/App.jsx','      <Analytics />','', 'Disable upstream-owner telemetry in isolated deployments; no visible component removed.');
patch('src/components/health/Appointments.jsx','import { doc } from "prettier";','', 'Remove unused formatter import; no runtime behavior.');
const originalHTML=fs.readFileSync(path.join(site,'index.html'),'utf8');
const telemetry=originalHTML.match(/    <script src="https:\/\/cdn\.amplitude\.com[^\n]+/);
if(!telemetry)throw Error('Expected pinned telemetry scripts');
patch('index.html',telemetry[0],'','Disable upstream-owner Amplitude telemetry and its bootstrap; no visible element removed.');
const reference=process.argv.includes('--reference');
const media=JSON.parse(fs.readFileSync(path.join(local,'media-manifest.json')));
if(JSON.stringify(media)!==JSON.stringify(JSON.parse(fs.readFileSync(path.join(import.meta.dirname,'media-snapshot.json')))))throw Error('Media snapshot differs from the reviewed version; do not silently refresh resources.');
if(!reference){
 instrument(patch);
 fs.copyFileSync(path.join(root,'environments/tricky_full/runtime.js'),path.join(site,'src/full-runtime.js'));
 for(const [url,r] of Object.entries(media.resources)){
  const mapped='/external-assets/'+crypto.createHash('sha256').update(url).digest('hex')+(r.local_path?path.extname(r.local_path):'.missing');
  for(const name of r.sources){
   const p=path.join(site,name),raw=fs.readFileSync(p,'utf8');
   if(raw.includes(url)){fs.writeFileSync(p,raw.split(url).join(mapped));patches.push({file:name,before:url,after:mapped,reason:r.local_path?'Exact cached original media bytes.':'Original media unavailable at snapshot time; preserve control and local failed-resource behavior, no invented replacement.'});}
  }
  if(r.local_path){if(sha(fs.readFileSync(path.join(local,r.local_path)))!==r.sha256)throw Error('Media hash mismatch');const p=path.join(site,'public',mapped);fs.mkdirSync(path.dirname(p),{recursive:true});fs.copyFileSync(path.join(local,r.local_path),p);}
 }
}
const runtime_sha256=reference?null:sha(fs.readFileSync(path.join(root,'environments/tricky_full/runtime.js')));
const package_lock_sha256=sha(fs.readFileSync(path.join(root,'environments/tricky_full/package-lock.json')));
const site_revision=sha(JSON.stringify({source:source.files,patches,runtime_sha256,package_lock_sha256,media:media.resources,build:sha(fs.readFileSync(import.meta.filename)),instrument:sha(fs.readFileSync(path.join(import.meta.dirname,"instrument.mjs")))}));
if(!reference){const p=path.join(site,'index.html');fs.writeFileSync(p,fs.readFileSync(p,'utf8').replace('<head>','<head>\n    <meta name="intent-site-revision" content="'+site_revision+'">'));}
const out=path.join(local,reference?'reference-dist':'dist');
await build({root:site,configFile:false,logLevel:'warn',esbuild:{jsx:'automatic'},build:{target:'esnext',outDir:out,emptyOutDir:true}});
const files=Object.fromEntries(fs.readdirSync(out,{recursive:true}).filter(x=>fs.statSync(path.join(out,x)).isFile()).map(x=>[x,sha(fs.readFileSync(path.join(out,x)))]));
// Public catalogs are extracted from exact source, not copied from task answers.
let catalog=fs.readFileSync(path.join(site,'src/components/shopping/sampleProducts.jsx'),'utf8');
catalog=catalog.replace(/^import\s+(\w+)\s+from\s+"([^"]+)";?/gm,(_,name,p)=>`const ${name}=${JSON.stringify(p)};`).replace('export default sampleProducts;','JSON.stringify(sampleProducts);');
fs.writeFileSync(path.join(local,'catalog.json'),vm.runInNewContext(catalog,{}, {timeout:1000}));
const pricing=fs.readFileSync(path.join(site,'src/components/spotify/darkPatterns/AestheticManipulation.jsx'),'utf8');
const plans=pricing.slice(pricing.indexOf('const plans = ')+14,pricing.indexOf('\n];')+2);
fs.writeFileSync(path.join(local,'membership-catalog.json'),JSON.stringify(vm.runInNewContext('('+plans+')',{}, {timeout:1000}),null,2));
let users=fs.readFileSync(path.join(site,'src/components/health/data/users.jsx'),'utf8').replace('export default users;','JSON.stringify(users.find(u=>u.id==="1").appointments);');
fs.writeFileSync(path.join(local,'appointments.json'),vm.runInNewContext(users,{}, {timeout:1000}));
const report={schema_version:2,site_revision,full_site:!reference,source,patches,runtime_sha256,package_lock_sha256,dist_sha256:files,
 catalog_sha256:sha(fs.readFileSync(path.join(local,'catalog.json'))),membership_catalog_sha256:sha(fs.readFileSync(path.join(local,'membership-catalog.json'))),appointments_sha256:sha(fs.readFileSync(path.join(local,'appointments.json'))),
 build_script_sha256:sha(fs.readFileSync(import.meta.filename)),instrumentation_sha256:sha(fs.readFileSync(path.join(root,'environments/tricky_full/instrument.mjs'))),
 scope:reference?'Complete original application, telemetry disabled and unused formatter import removed.':'Complete pinned application and original layouts/navigation; shared outcome-state instrumentation, cached media, unavailable source resources explicitly retained as failures. Privacy/activation persistence are derived semantics.',
 missing_resources:Object.values(media.resources).filter(r=>!r.local_path).map(r=>({url:r.url,status:r.status,error:r.error||null})),
 absent_upstream_files:['/downloads/lab_results.pdf','/downloads/blood_test.pdf','/downloads/xray.pdf']};
fs.writeFileSync(path.join(local,reference?'reference-build.json':'build.json'),JSON.stringify(report,null,2));
console.log('Complete '+(reference?'reference':'instrumented')+' build:',Object.keys(files).length,'assets; version',site_revision);
