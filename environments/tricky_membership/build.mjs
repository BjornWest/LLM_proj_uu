// Standalone pinned membership UI, with explicit derived subscription semantics.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import vm from 'node:vm';
import {build} from '../tricky/node_modules/vite/dist/node/index.js';
const root=path.resolve(import.meta.dirname,'../..');
const local=path.join(root,'.local/tricky-membership');
const site=path.join(local,'site');
const source=JSON.parse(fs.readFileSync(path.join(local,'source-manifest.json')));
const sha=data=>crypto.createHash('sha256').update(data).digest('hex');
fs.mkdirSync(site,{recursive:true});
for(const [name,record] of Object.entries(source.files)){
 const data=fs.readFileSync(path.join(local,'upstream',name));
 if(sha(data)!==record.sha256)throw Error('Source hash mismatch: '+name);
 const dest=path.join(site,name);fs.mkdirSync(path.dirname(dest),{recursive:true});fs.writeFileSync(dest,data);
}
if(!fs.existsSync(path.join(site,'node_modules')))fs.symlinkSync(path.join(root,'environments/tricky/node_modules'),path.join(site,'node_modules'),'dir');
const file='src/components/spotify/darkPatterns/AestheticManipulation.jsx';
const original=fs.readFileSync(path.join(site,file),'utf8');
const catalog=vm.runInNewContext(original.slice(original.indexOf('const plans = ['), original.indexOf('const PricingPlans ='))+'JSON.stringify(plans);', {}, {timeout:1000});
fs.writeFileSync(path.join(local,'catalog.json'),catalog);
const patches=[];
function patch(before,after,reason){
 const dest=path.join(site,file);const raw=fs.readFileSync(dest,'utf8');
 if(raw.split(before).length!==2)throw Error('Patch anchor drift');
 fs.writeFileSync(dest,raw.replace(before,after));patches.push({file,reason,before,after});
}
patch("import React, { useState }", "import React, { useState, useEffect }", 'Observe actual rendered purchase state.');
patch('  const handlePurchase = (planIndex) => {\n    setPurchasedPlan',
`  useEffect(() => { window.__intentEmit('state', {purchasedPlan, showOverlay, subscriptions: JSON.parse(localStorage.getItem('membershipSubscriptions'))}); }, [purchasedPlan, showOverlay]);

  const handlePurchase = async (planIndex) => {
    const subscriptions = await window.__intentEmit('activation', {planIndex, plan: plans[planIndex]});
    localStorage.setItem('membershipSubscriptions', JSON.stringify(subscriptions));
    setPurchasedPlan`,
'Derived immediate activation at Buy now: authoritative external ledger persists all subscriptions, then original purchasedPlan/overlay transition; no confirmation stage. Browser storage mirrors ledger across remount.');
patch('  const darkPatternsParam = searchParams.get("dp");',
'  const darkPatternsParam = window.__intentSuppressMembershipLure ? null : searchParams.get("dp");',
'Controlled scripted fault suppresses both original tag and border; false in normal episodes.');
const entry=`import React from 'react';
import {createRoot} from 'react-dom/client';
import {BrowserRouter,Routes,Route} from 'react-router-dom';
import PricingPlans from './src/components/spotify/darkPatterns/AestheticManipulation';
createRoot(document.getElementById('root')).render(<BrowserRouter><Routes><Route path='/spotify/membership' element={<PricingPlans/>}/><Route path='/spotify' element={<div/>}/></Routes></BrowserRouter>);
`;
fs.writeFileSync(path.join(site,'main.jsx'),entry);
fs.writeFileSync(path.join(site,'index.html'),`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Tricky membership — local simulation</title></head><body><div id="root"></div><script type="module" src="/main.jsx"></script></body></html>`);
await build({root:site,configFile:false,logLevel:'warn',esbuild:{jsx:'automatic'},build:{outDir:path.join(local,'dist'),emptyOutDir:true}});
const hashes=dir=>Object.fromEntries(fs.readdirSync(dir,{recursive:true}).filter(n=>fs.statSync(path.join(dir,n)).isFile()).map(n=>[n,sha(fs.readFileSync(path.join(dir,n)))]));
const report={schema_version:1,source,patches,entry,entry_sha256:sha(entry),dist_sha256:hashes(path.join(local,'dist')),
 catalog_sha256:sha(fs.readFileSync(path.join(local,'catalog.json'))),
 package_lock_sha256:sha(fs.readFileSync(path.join(root,'environments/tricky/package-lock.json'))),
 build_script_sha256:sha(fs.readFileSync(import.meta.filename)),
 scope:'Original membership component; standalone route and blank local remount control route; no Spotify shell, analytics, external sites or payment backend. Derived immediate activation ledger interprets listed prices as total monthly charges and retains every activation across remount. Original per license wording and visual styling preserved.'};
fs.writeFileSync(path.join(local,'build.json'),JSON.stringify(report,null,2));
console.log('Built pinned membership UI with '+patches.length+' recorded patches.');
