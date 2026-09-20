"""Audit explicitly selected saved Qwen/OpenRouter requests, without inference.

Only visible final responses are attributed; hidden OpenRouter fallback attempts
and transport failures without provider evidence cannot rank operators.
"""
import argparse
from pathlib import Path
import json,hashlib
from collections import Counter,defaultdict
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--root',action='append',required=True,type=Path)
parser.add_argument('--output',required=True,type=Path)
args=parser.parse_args()
if args.output.exists():raise SystemExit('Choose a new evidence output')
roots=args.root
source_files={}
records=[];excluded=Counter();seen={}
for root in roots:
 for file in sorted(root.rglob('steps.jsonl')):
  source_files[str(file)]=hashlib.sha256(file.read_bytes()).hexdigest()
  meta=json.loads((file.parent/'metadata.json').read_text()) if (file.parent/'metadata.json').exists() else {}
  for row in [json.loads(x) for x in file.read_text().splitlines() if x.strip()]:
   req=row.get('model_request') or {};resp=row.get('model_response') or {};err=resp.get('error') or {};err=err if isinstance(err,dict) else {};em=err.get('metadata') or {}
   rid=resp.get('id');model=req.get('model','');provider=resp.get('provider') or em.get('provider_name')
   if not ('qwen' in model.lower() or '@preset/deka' in model.lower()):excluded['other_or_unretained_model']+=1;continue
   if not (rid and str(rid).startswith('gen-')) and not err:excluded['no_generation_id_or_api_error']+=1;continue
   key=rid or hashlib.sha256(json.dumps([req,resp,file.parent.name,row.get('step')],sort_keys=True).encode()).hexdigest()
   response_hash=hashlib.sha256(json.dumps(resp,sort_keys=True).encode()).hexdigest()
   if key in seen:
    if seen[key]!=response_hash:raise ValueError('Conflicting saved response for one generation ID')
    excluded['duplicate_request']+=1;continue
   seen[key]=response_hash
   choice=(resp.get('choices') or [{}])[0];msg=choice.get('message') or {};calls=msg.get('tool_calls') or []
   native=bool(req.get('tools'));error=row.get('error');status=err.get('code');flags=[]
   if err:flags.append('api_error_'+str(status))
   if native and not err:
    if choice.get('finish_reason')=='tool_calls' and not calls:flags.append('claimed_tools_but_missing')
    elif not calls:flags.append('native_no_call_'+str(choice.get('finish_reason')))
    elif len(calls)>1:flags.append('multiple_calls_rejected' if error else 'multiple_calls')
    if error and not flags:flags.append('other_step_error')
   if not native and error and not err:flags.append('text_or_execution_error')
   records.append({'provider':provider,'id':rid,'path':str(file),'step':row.get('step'),'profile':(meta.get('harness_profile') or {}).get('name','legacy'),'model':model,'native':native,'flags':flags,'error':error,'api_message':err.get('message'),'api_code':status,'finish':choice.get('finish_reason'),'date':file.parent.name[:8],'prompt_tokens':(resp.get('usage') or {}).get('prompt_tokens'),'response_sha256':hashlib.sha256(json.dumps(resp,sort_keys=True).encode()).hexdigest()})
summary={}
for provider in sorted(set(str(r['provider']) for r in records)):
 rows=[r for r in records if str(r['provider'])==provider];summary[provider]={'requests':len(rows),'native':sum(r['native'] for r in rows),'flags':dict(Counter(f for r in rows for f in r['flags'])),'profiles':dict(Counter(r['profile'] for r in rows))}
result={'scope':'Saved Qwen/OpenRouter responses in explicit roots; not a complete account ledger or controlled provider comparison. Unknown-provider transport failures and hidden fallback attempts are not ranked.', 'source_files':source_files,'roots':list(map(str,roots)),'excluded':dict(excluded),'requests':len(records),'summary':summary,'records':records}
args.output.parent.mkdir(parents=True,exist_ok=True)
with args.output.open('x') as f:f.write(json.dumps(result,indent=2)+'\n')
print(json.dumps({'requests':len(records),'summary':summary,'excluded':dict(excluded)},indent=2))
