// Writes credentials only to an ignored mode-0600 local file. Never prints them.
import {mkdir,writeFile} from 'node:fs/promises';
import {randomBytes,createHash} from 'node:crypto';
import path from 'node:path';
const ids=process.argv.slice(2);
if(!ids.length||ids.some(id=>!/^[a-z0-9-]{1,40}$/.test(id))||new Set(ids).size!==ids.length)throw Error('Usage: node scripts/create_invites.mjs bjorn teammate-1 teammate-2');
const directory=path.resolve('../../.local/vercel-demo');
await mkdir(directory,{recursive:true,mode:0o700});
const codes=Object.fromEntries(ids.map(id=>[id,randomBytes(32).toString('base64url')]));
const hashes=Object.fromEntries(Object.entries(codes).map(([id,code])=>[id,createHash('sha256').update(code).digest('hex')]));
await writeFile(path.join(directory,'access.env'),`DEMO_SESSION_SECRET=${randomBytes(48).toString('base64url')}\nDEMO_INVITES_JSON=${JSON.stringify(hashes)}\n`,{mode:0o600,flag:'wx'});
await writeFile(path.join(directory,'invitation-codes.json'),JSON.stringify(codes,null,2)+'\n',{mode:0o600,flag:'wx'});
console.log(`Created private access.env and invitation-codes.json in ${directory}. Existing files are never overwritten.`);
