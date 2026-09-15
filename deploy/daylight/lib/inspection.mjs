// Public fixture bytes only. Authentication is enforced by the caller, before
// cache validation. Never expose the private harness package as a web root.
import {readFile} from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import expectedManifest from '../../../environments/inspection_shop/manifest.json' with {type:'json'};
const mime={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.jpg':'image/jpeg','.jpeg':'image/jpeg','.png':'image/png','.svg':'image/svg+xml','.webp':'image/webp'};
const hash=raw=>createHash('sha256').update(raw).digest('hex');
export async function inspectionAsset(assetRoot,pathname) {
  const name=pathname.startsWith('/assets/')?pathname.slice(1):null;
  if(!name||!Object.hasOwn(expectedManifest.files,name))return null;
  const manifest=expectedManifest;
  const raw=await readFile(path.join(assetRoot,'inspection-shop/dist',name));
  if(hash(raw)!==manifest.files[name])throw Error('Inspection asset hash mismatch');
  return {raw,type:mime[path.extname(name)]||'application/octet-stream',etag:'"'+manifest.files[name]+'"'};
}
export async function inspectionHTML(assetRoot) {
  const root=path.join(assetRoot,'inspection-shop');
  const manifest=JSON.parse(await readFile(path.join(root,'manifest.json'),'utf8'));
  const raw=await readFile(path.join(root,'dist/index.html'));
  if(hash(raw)!==manifest.files['index.html'])throw Error('Inspection HTML hash mismatch');
  // The original page body and all dataset assets remain byte-identical. The
  // bootstrap provides isolated tab state, local records and inspection chrome.
  return raw.toString().replace('<head>','<head><script src="/assets/inspection.js"></script><link rel="stylesheet" href="/assets/inspection.css">');
}
export const inspectionCSP="default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'none'; frame-src 'none'; frame-ancestors 'none'; form-action 'none'; base-uri 'none'; sandbox allow-scripts allow-same-origin allow-downloads";
