// Explicit local import only. No HTTP endpoint can publish filesystem paths.
import {parseArgs} from 'node:util';
import {readFile} from 'node:fs/promises';
import {SqliteStore} from './lib/sqlite-store.mjs';
import {TraceLibrary} from './lib/library.mjs';
const {values}=parseArgs({options:{bundle:{type:'string'},owner:{type:'string'},database:{type:'string'},root:{type:'string'},metadata:{type:'string'},'reviewed-for-sharing':{type:'boolean'}}});
if(!values.bundle||!values.owner||!values.database||!values.root||!values['reviewed-for-sharing'])throw Error('Required: --bundle DIRECTORY --owner OWNER --database FILE --root DIRECTORY --reviewed-for-sharing [--metadata FILE]. Review secrets/private data first; originals are not sanitized.');
process.umask(0o077);const store=new SqliteStore(values.database);
try{const result=await new TraceLibrary(store,{root:values.root}).publish(values.bundle,values.owner,values.metadata?JSON.parse(await readFile(values.metadata,'utf8')):{});console.log(JSON.stringify(result));}finally{store.close();}
