// Local integration fixture only; never imported by the deployed handler.
import {createServer} from 'node:http';
import {FileStore} from '../lib/store.mjs';
import {createHandler} from '../api/index.mjs';
if(process.env.VERCEL)throw Error('Test server is local only');
const handler=createHandler({store:new FileStore(process.env.HARNESS_TEST_DATA),env:process.env,local:true});
createServer(handler).listen(Number(process.env.PORT||8883),'127.0.0.1');
