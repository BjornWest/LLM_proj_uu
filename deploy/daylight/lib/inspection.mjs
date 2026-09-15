// Authentication precedes all page and asset access. One exact application build
// serves every Tricky site; private task/grade packages are never a web root.
import {readFile} from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
import manifest from '../../../environments/inspection_full/manifest.json' with {type:'json'};
export const inspectionManifests={shop:manifest,music:manifest,health:manifest};
export const inspectionRevision=manifest.site_revision;
const mime={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.jpg':'image/jpeg','.jpeg':'image/jpeg','.png':'image/png','.svg':'image/svg+xml','.webp':'image/webp','.gif':'image/gif','.mp3':'audio/mpeg','.wav':'audio/wav','.ogg':'audio/ogg'};
const hash=raw=>createHash('sha256').update(raw).digest('hex');
export async function inspectionAsset(assetRoot,pathname) {
 const name=pathname.slice(1);
 if(name==='index.html'||!Object.hasOwn(manifest.files,name))return null;
 const raw=await readFile(path.join(assetRoot,'inspection-full/dist',name));
 if(hash(raw)!==manifest.files[name])throw Error('Inspection asset hash mismatch');
 return {raw,type:mime[path.extname(name)]||'application/octet-stream',etag:'"'+manifest.files[name]+'"'};
}
export async function inspectionHTML(assetRoot) {
 const raw=await readFile(path.join(assetRoot,'inspection-full/dist/index.html'));
 if(hash(raw)!==manifest.files['index.html'])throw Error('Inspection HTML hash mismatch');
 return raw.toString().replace('<head>','<head><script defer src="/assets/inspection.js"></script><link rel="stylesheet" href="/assets/inspection.css">');
}
export const inspectionCSP="default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; media-src 'self' blob:; font-src 'self' data:; connect-src 'none'; frame-src 'none'; frame-ancestors 'none'; form-action 'none'; base-uri 'none'; sandbox allow-scripts allow-same-origin allow-downloads allow-modals";
