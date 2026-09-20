// Authenticated, build-generated assets only. No PC, inference or grader access.
import {readFile} from 'node:fs/promises';
import path from 'node:path';
import {createHash} from 'node:crypto';
const base='/environments/prislyktan';
const mime={'.html':'text/html; charset=utf-8','.js':'text/javascript; charset=utf-8','.css':'text/css; charset=utf-8','.svg':'image/svg+xml'};
export async function prislyktanAsset(root,pathname){
 if(pathname!==base&&!pathname.startsWith(base+'/'))return null;
 const directory=path.join(root,'prislyktan'),manifest=JSON.parse(await readFile(path.join(directory,'manifest.json')));
 if(manifest.schema!=='prislyktan-design-preview-v1'||manifest.base_path!==base)throw Error('Invalid preview manifest');
 let name=pathname.slice(base.length).replace(/^\//,'');
 if(!name||name.endsWith('/'))name+='index.html';
 else if(!path.extname(name))name+='/index.html';
 if(name.split('/').some(part=>!part||part==='.'||part==='..')||name.includes('\\')||!Object.hasOwn(manifest.output_files,name))return null;
 const raw=await readFile(path.join(directory,name)),hash=createHash('sha256').update(raw).digest('hex');
 if(hash!==manifest.output_files[name])throw Error('Preview asset changed');
 return {raw,type:mime[path.extname(name)]||'application/octet-stream',etag:'"'+hash+'"'};
}
export const previewCSP="default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'none'; frame-src 'none'; frame-ancestors 'none'; form-action 'none'; base-uri 'none'; sandbox allow-scripts allow-same-origin allow-modals";
