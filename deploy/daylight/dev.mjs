import {createServer} from 'node:http';
import {FileStore} from './lib/store.mjs';
import {createHandler} from './api/index.mjs';
if(process.env.VERCEL)throw Error('Local server must not run on Vercel');
const port=Number(process.env.PORT||8880);
createServer(createHandler({store:new FileStore('.dev-data'),local:true})).listen(port,'127.0.0.1',()=>console.log(`Private demo: http://localhost:${port}`));
