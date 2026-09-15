"""Create dedicated worker secrets locally, never overwrite existing settings."""
import argparse
import json
import os
from pathlib import Path
import secrets
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url',default='',help='Stable Vercel production origin, not a deployment-specific URL')
    args=parser.parse_args()
    folder=ROOT/'.local/team-worker';folder.mkdir(parents=True,exist_ok=True)
    if (folder/'worker.env').exists() or (folder/'vercel.env').exists():
        raise SystemExit('Existing worker configuration retained; edit it locally instead of regenerating credentials.')
    source=dotenv_values(ROOT/'.env')
    token=secrets.token_urlsafe(48)
    values={'HARNESS_URL':args.url,'HARNESS_WORKER_TOKEN':token,
            'DAYLIGHT_OPENROUTER_API_KEY':source.get('DAYLIGHT_OPENROUTER_API_KEY',''),
            'MODEL_NAME':source.get('MODEL_NAME') or 'qwen/qwen3.8-27b',
            'OPENROUTER_PROVIDERS':source.get('OPENROUTER_PROVIDERS') or 'chutes,dekallm,phala,parasail,akashml,ionstream,cloudflare',
            'HARNESS_MODE':'live','HARNESS_POLL_SECONDS':'5'}
    for name,items in [('worker.env',values),('vercel.env',{'HARNESS_WORKER_TOKEN':token})]:
        fd=os.open(folder/name,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as out:
            out.write(''.join(key+'='+json.dumps(value,ensure_ascii=False)+'\n' for key,value in items.items()))
    print('Created .local/team-worker/worker.env and vercel.env with private permissions. No values printed.')
    print('Add HARNESS_WORKER_TOKEN from vercel.env to Vercel Production. Set HARNESS_URL in worker.env to the stable production origin.')

if __name__=='__main__':main()
