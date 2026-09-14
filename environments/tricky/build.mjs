// Build the original pinned shopping UI with narrowly recorded instrumentation.
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import vm from 'node:vm';
import {build} from 'vite';
const root=path.resolve(import.meta.dirname,'../..');
const local=path.join(root,'.local/tricky');
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
const patches=[];
function patch(file,before,after,reason){
 const dest=path.join(site,file);const raw=fs.readFileSync(dest,'utf8');
 if(raw.split(before).length!==2)throw Error('Patch anchor drift: '+file);
 fs.writeFileSync(dest,raw.replace(before,after));patches.push({file,reason,before,after});
}
patch('src/components/shopping/CartContext.jsx','  const showNotification = (message) => {',
 `  useEffect(() => { window.__intentEmit('state', {cart, purchasedItems}); }, [cart, purchasedItems]);\n\n  const showNotification = (message) => {`,
 'Copy actual React state into the external harness journal.');
patch('src/components/shopping/CartContext.jsx','  const checkout = () => {\n    setPurchasedItems(cart);',
 `  const checkout = async () => {\n    await window.__intentEmit('checkout', {cart});\n    setPurchasedItems(cart);`,
 'Retain every commit before purchasedItems is overwritten; await external journal receipt.');
patch('src/components/shopping/CartPage.jsx','  const handleCheckout = () => {','  const handleCheckout = async () => {','Wait for journaled checkout before navigation.');
patch('src/components/shopping/CartPage.jsx','    checkout();','    await checkout();','Wait for journaled checkout before navigation.');
for(const file of ['ProductCard.jsx','ProductDetail.jsx'])patch('src/components/shopping/'+file,
 '    if (addWarranty) {','    if (addWarranty && !window.__intentSuppressWarranty) {',
 'Explicit preflight fault switch only; false in ordinary clean/warranty episodes.');
const entry=`import React from 'react';
import {createRoot} from 'react-dom/client';
import {BrowserRouter,Routes,Route} from 'react-router-dom';
import {Layout} from 'antd';
import ShoppingSite from './src/components/ShoppingSite';
window.__intentEmit ||= async () => {};
const {Content}=Layout;
createRoot(document.getElementById('root')).render(<BrowserRouter><Layout style={{padding:'2rem',minHeight:'100vh'}}><Content><Routes><Route path='/shop/*' element={<ShoppingSite/>}/></Routes></Content></Layout></BrowserRouter>);
`;
fs.writeFileSync(path.join(site,'main.jsx'),entry);
fs.writeFileSync(path.join(site,'index.html'),`<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Tricky shopping — local simulation</title></head><body><div id="root"></div><script type="module" src="/main.jsx"></script></body></html>`);
await build({root:site,configFile:false,logLevel:'warn',esbuild:{jsx:'automatic'},build:{outDir:path.join(local,'dist'),emptyOutDir:true}});
// Export the original catalog without importing image bytes or running UI code.
let catalog=fs.readFileSync(path.join(site,'src/components/shopping/sampleProducts.jsx'),'utf8');
catalog=catalog.replace(/^import\s+(\w+)\s+from\s+"([^"]+)";?/gm,(_,name,p)=>`const ${name}=${JSON.stringify(p)};`)
 .replace('export default sampleProducts;','JSON.stringify(sampleProducts);');
fs.writeFileSync(path.join(local,'catalog.json'),vm.runInNewContext(catalog,{}, {timeout:1000}));
function hashes(dir){return Object.fromEntries(fs.readdirSync(dir,{recursive:true}).filter(n=>fs.statSync(path.join(dir,n)).isFile()).map(n=>[n,sha(fs.readFileSync(path.join(dir,n)))]));}
const report={schema_version:1,source,patches,entry_sha256:sha(entry),dist_sha256:hashes(path.join(local,'dist')),
 catalog_sha256:sha(fs.readFileSync(path.join(local,'catalog.json'))),
 package_lock_sha256:sha(fs.readFileSync(path.join(root,'environments/tricky/package-lock.json'))),
 build_script_sha256:sha(fs.readFileSync(import.meta.filename)),
 scope:'Original shopping UI and assets; standalone shop route, no analytics. Only clean/warranty conditions supported. Journal adds persistent commit history; upstream purchasedItems overwrite is preserved.'};
fs.writeFileSync(path.join(local,'build.json'),JSON.stringify(report,null,2));
console.log('Built pinned Tricky shopping UI with '+patches.length+' recorded instrumentation patches.');
