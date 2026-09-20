"""Offline RPC/core-runner browser ownership check; no HTTP model calls."""
import argparse,json,os,sys,re,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
from http.server import ThreadingHTTPServer
from threading import Thread
from verify_subagents import Handler
import browsergym.core
import gymnasium as gym
from intent_browser.actions import make_action_set
from intent_browser.interactive_episode import InteractiveEpisode
from intent_browser.trace import write_json

def main():
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir(parents=True,exist_ok=False)
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler);Thread(target=server.serve_forever,daemon=True).start();url=f'http://127.0.0.1:{server.server_port}'
 env=gym.make('browsergym/openended',task_kwargs={'start_url':url,'goal':'Manual session'},headless=True,wait_for_user_message=False,action_mapping=make_action_set().to_python_code);env.reset()
 original_page=env.unwrapped.page;mapping=env.unwrapped.action_mapping
 checks=[]
 def answer(request,name,args):
  return {'request':{'model':'scripted','messages':request['messages'],'session_id':request['session_id'],**{k:request[k] for k in ('tools','tool_choice','parallel_tool_calls') if k in request}},
   'response':{'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':None,'tool_calls':[{'id':name,'type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}}],'usage':{'cost':0}}}
 try:
  episode=InteractiveEpisode(env,'Visit the lookup and report the code.',a.output/'traces',public_history=[{'answer':'Earlier user-facing result'}])
  q=episode.observe();assert q['kind']=='model_request';tools=q['tools'];checks.append('fresh core request')
  assert 'Earlier user-facing result' in json.dumps(q['messages']);checks.append('previous public activity reaches root conversation')
  r=episode.accept(answer(q,'goto',{'url':url+'/lookup'}));assert r['kind']=='ready_for_observation';checks.append('one browser action before RPC returns')
  q=episode.observe();assert q['tools']==tools and 'PINE-74' in json.dumps(q['messages']);checks.append('fixed tools and fresh page feedback')
  r=episode.accept(answer(q,'send_msg_to_user',{'text':'PINE-74'}));assert r['kind']=='finished' and r['answer']=='PINE-74';checks.append('native answer ends Ask')
  assert env.unwrapped.page is original_page and not original_page.is_closed() and env.unwrapped.action_mapping is mapping;checks.append('same human browser remains open and mapping restored')
  cancelled=InteractiveEpisode(env,'Do not change anything',a.output/'traces');q=cancelled.observe();cancelled.cancel(answer(q,'goto',{'url':url+'/'}));assert original_page.url==url+'/lookup';checks.append('cancel retains response without executing it')
  assert cancelled.closed and not original_page.is_closed();checks.append('cancel releases browser')
  mismatch=InteractiveEpisode(env,'Read only',a.output/'traces');q=mismatch.observe();ev=answer(q,'goto',{'url':url+'/'});ev['request']['messages']=[]
  r=mismatch.accept(ev);assert r['kind']=='finished' and r['error'] and original_page.url==url+'/lookup';checks.append('mismatched transport request rejected before action')
  helper=InteractiveEpisode(env,'Delegate checking the supplied evidence; report the helper answer.',a.output/'traces')
  q=helper.observe();parent_session=q['session_id'];parent_tools=q['tools']
  r=helper.accept(answer(q,'spawn_agent',{'task':'Report PINE-74 from this supplied evidence.','browser':'none'}))
  assert r['kind']=='ready_for_observation'
  helper_id=None;child_seen=False
  for index in range(8):
   q=helper.observe()
   if q['session_id']!=parent_session:
    child_seen=True
    assert {t['function']['name'] for t in q['tools']}=={t['function']['name'] for t in parent_tools}-{'spawn_agent'}
    r=helper.accept(answer(q,'send_msg_to_user',{'text':'PINE-74 from supplied evidence'}))
   else:
    tool_text=' '.join(m.get('content','') or '' for m in q['messages'] if m['role']=='tool')
    ids=re.findall(r'"agent_id"\s*:\s*"([a-f0-9]+)"',tool_text)
    if ids:helper_id=ids[0]
    assert helper_id
    if 'PINE-74 from supplied evidence' in tool_text:
     r=helper.accept(answer(q,'send_msg_to_user',{'text':'Helper confirmed PINE-74'}));break
    r=helper.accept(answer(q,'wait_agent',{'agent_id':helper_id,'timeout_seconds':1}))
  assert child_seen and helper.closed and helper.answer=='Helper confirmed PINE-74'
  checks.append('helper transport uses separate session, inherited tools and returns evidence to parent')
  assert env.unwrapped.page is original_page and original_page.url==url+'/lookup'
  checks.append('reasoning helper leaves human browser intact')
  retry=InteractiveEpisode(env,'Report what you see without changing the page.',a.output/'traces')
  q=retry.observe();failed=answer(q,'noop',{'wait_ms':0});failed.update(error='HTTP 429',http_status=429,retry_after='0',response={'error':{'message':'Busy'}})
  r=retry.accept(failed);assert r['kind']=='retry_wait' and r['retry_wait_seconds']==2
  checks.append('HTTP retry returns wait boundary without blocking browser RPC')
  time.sleep(r['retry_wait_seconds'])
  q=retry.observe();assert 'HARNESS RECOVERY NOTICE' in json.dumps(q['messages'])
  r=retry.accept(answer(q,'send_msg_to_user',{'text':'Read only, no action was replayed.'}));assert retry.closed and r['answer']
  assert retry.result[1]['decision_retry_count']==1 and original_page.url==url+'/lookup'
  checks.append('bounded HTTP recovery preserves error and refreshes before next request')
  stopped=[False]
  batch=InteractiveEpisode(env,'Wait twice, then reply',a.output/'traces',
      on_step=lambda *_:stopped.__setitem__(0,True),interrupted=lambda:stopped[0])
  q=batch.observe();ev=answer(q,'noop',{'wait_ms':0});calls=ev['response']['choices'][0]['message']['tool_calls']
  calls.append({'id':'second','type':'function','function':{'name':'noop','arguments':'{"wait_ms":0}'}})
  r=batch.accept(ev)
  assert batch.closed and len(batch.actions)==1 and r['error']
  checks.append('interrupt after first batch action prevents remaining action dispatch')
  write_json(a.output/'report.json',{'passed':True,'checks':checks,'model_calls':0});print(json.dumps(checks))
 finally:env.close();server.shutdown();server.server_close()
if __name__=='__main__':main()
