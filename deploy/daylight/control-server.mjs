import {createServer} from 'node:http';
import {timingSafeEqual} from 'node:crypto';
import {pathToFileURL} from 'node:url';
import {SqliteStore} from './lib/sqlite-store.mjs';
import {Harness,workerAuthorized} from './lib/harness.mjs';
import {Manual} from './lib/manual.mjs';

const authorized=(header,token)=>{
  if(typeof token!=='string'||token.length<43||typeof header!=='string')return false;
  const a=Buffer.from(header),b=Buffer.from('Bearer '+token);
  return a.length===b.length&&timingSafeEqual(a,b);
};
export function controlHandler({store,env=process.env,fetcher=fetch}={}) {
  if(!env.DAYLIGHT_CONTROL_TOKEN||env.DAYLIGHT_CONTROL_TOKEN.length<43)throw Error('Control token required');
  const manual=new Manual(store,{env,fetcher});
  const handler=async(req,res)=>{
    res.setHeader('Cache-Control','no-store');res.setHeader('Content-Type','application/json');
    const send=(status,value)=>{res.statusCode=status;res.end(JSON.stringify(value));};
    const route=req.url;
    const worker=route.startsWith('/api/harness/worker/');
    if(!(worker?workerAuthorized(req.headers.authorization,env):authorized(req.headers.authorization,env.DAYLIGHT_CONTROL_TOKEN)))return send(401,{error:'Authentication required'});
    if(req.method!=='POST')return send(405,{error:'Method not allowed'});
    try {
      const operation=route.split('/').at(-1);
      const isManual=route.startsWith('/internal/manual/');
      if(worker?!['poll','checkpoint','reserve','artifact','update'].includes(operation):
        isManual?!['config','start','list','read','action','observe','close','artifact','ask','interrupt'].includes(operation):
        !['/internal/store/read','/internal/store/write','/internal/store/list'].includes(route))return send(404,{error:'Not found'});
      const chunks=[];let size=0;
      for await(const chunk of req){size+=chunk.length;if(size>16*1024*1024)return send(413,{error:'Request too large'});chunks.push(chunk);}
      let value;try{value=JSON.parse(Buffer.concat(chunks).toString('utf8'));}catch{return send(400,{error:'Invalid JSON'});}
      if(!value||typeof value!=='object'||Array.isArray(value))return send(400,{error:'Invalid request'});
      if(env.DAYLIGHT_CONTROL_READ_ONLY==='1'&&(worker||operation==='write'||isManual))return send(503,{error:'Storage maintenance; no writes accepted'});
      if(worker)return send(200,await new Harness(store,{env})[operation](value));
      if(isManual){
        if(operation==='config')return send(200,await manual.config());
        if(operation==='ask'||operation==='interrupt')return send(200,await manual[operation](value.owner,value.id,value));
        if(operation==='start')return send(200,await manual.start(value.owner,value));
        if(operation==='list')return send(200,await manual.list(value.owner));
        if(operation==='read')return send(200,await manual.read(value.owner,value.id));
        if(operation==='artifact')return send(200,await manual.artifact(value.owner,value.id,value.frame_id,value.part));
        return send(200,await manual.command(value.owner,value.id,operation,value));
      }
      const result=operation==='read'?await store.read(value.key):operation==='write'?
        await store.write(value.key,value.value,value.etag??null):await store.listKeys(value.prefix,{cursor:value.cursor,limit:value.limit});
      return send(200,result);
    }catch(error){
      // No request bodies, tokens or database contents in logs/errors.
      const status=[400,404,409,413,429,503].includes(error.status)?error.status:503;
      if(status===503)console.error(JSON.stringify({event:'control_request_failed',status}));
      return send(status,{error:status===409?'Storage conflict':'Control request failed'});
    }
  };
  handler.shutdown=()=>manual.shutdown();
  return handler;
}
if(process.argv[1]&&import.meta.url===pathToFileURL(process.argv[1]).href){
  process.umask(0o077);
  const store=new SqliteStore(process.env.DAYLIGHT_SQLITE_PATH||'.local/control/state.sqlite');
  const handler=controlHandler({store});
  const server=createServer(handler);server.requestTimeout=30000;
  server.listen(Number(process.env.PORT||8894),process.env.BIND_HOST||'127.0.0.1',()=>console.log('Control service ready'));
  for(const signal of ['SIGTERM','SIGINT'])process.on(signal,()=>{handler.shutdown();server.close(()=>{store.close();process.exit(0);});});
}
