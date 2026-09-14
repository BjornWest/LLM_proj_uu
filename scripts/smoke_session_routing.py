"""Two fresh MiniWoB episodes to inspect OpenRouter session routing and caching.

Explicit --live; persistent $0.05 total reservation cap, no client retries.
Does not resume or relabel the historical Chaos calibration.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import fcntl
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from intent_browser.backend import ChatCompletionsBackend
from intent_browser.openrouter import DEFAULT_PROVIDERS, provider_options
from intent_browser.trace import write_json

CAP = Decimal('0.05')


def now():
    return datetime.now(timezone.utc).isoformat()


class RoutingBudgetBackend(ChatCompletionsBackend):
    def __init__(self, key, providers, ledger, cache_prefix=False):
        options = provider_options(providers)
        # Dollars per million tokens. Includes Cloudflare's advertised output rate.
        options['provider']['max_price'] = {'prompt': 0.25 if cache_prefix == 256 else 0.5,
                                           'completion': 4, 'request': 0}
        super().__init__('https://openrouter.ai/api/v1', 'qwen/qwen3.8-27b', key,
                         max_tokens=128, request_options=options, session_routing=True)
        self.ledger = Path(ledger)
        self.stopped = False
        self.cache_prefix = cache_prefix

    def complete(self, messages):
        if self.stopped or not self.session_id:
            raise ValueError('Probe stopped or session missing; no request sent')
        if self.cache_prefix:
            messages = [dict(message) for message in messages]
            messages[0]['content'] += ('\nSynthetic cache measurement reference; not additional task instructions:\n'
                + '\n'.join(f'Reference entry {i:03d}: stable browser observation cache fixture.'
                            for i in range(256 if self.cache_prefix == 256 else 128)))
        if any(set(m) != {'role','content'} or not isinstance(m['content'], str) for m in messages):
            raise ValueError('Only plain-text messages fit this reservation bound')
        # Deliberately pessimistic UTF-8-byte token bound + chat framing allowance.
        bound = len(json.dumps(messages, ensure_ascii=False).encode()) + 2048
        prices=self.request_options['provider']['max_price']
        reserve = (Decimal(bound) * Decimal(str(prices['prompt']))
                   + Decimal(self.max_tokens) * Decimal(str(prices['completion']))) / Decimal(1000000)
        self.ledger.parent.mkdir(parents=True, exist_ok=True)
        with self.ledger.with_suffix('.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            data = json.loads(self.ledger.read_text()) if self.ledger.exists() else {
                'cap_usd': str(CAP), 'reserved_cost_usd':'0', 'requests':[]}
            if Decimal(data['cap_usd']) != CAP:
                raise ValueError('Unexpected probe budget cap')
            if data['requests']:
                last = data['requests'][-1]
                if last.get('status') != 'completed':
                    raise ValueError('Prior failed/unknown probe needs inspection; no request sent')
                elapsed = (datetime.now(timezone.utc)-datetime.fromisoformat(last['finished_at'])).total_seconds()
                time.sleep(max(0,10-elapsed))
            total = Decimal(data['reserved_cost_usd']) + reserve
            if total > CAP:
                raise ValueError('Persistent $0.05 probe reservation exhausted; no request sent')
            row = {'session_id':self.session_id, 'started_at':now(), 'status':'reserved',
                   'reservation_usd':str(reserve), 'input_token_bound':bound,
                   'reported_cost_usd':None, 'model_request': {
                       'model':self.model,'messages':messages,'temperature':0,'max_tokens':self.max_tokens,
                       'stream':False, **self.request_options, 'session_id':self.session_id}}
            data['requests'].append(row)
            data['reserved_cost_usd'] = str(total)
            write_json(self.ledger, data)  # Full reservation and exact intended request before dispatch.
            try:
                completion = super().complete(messages)
                row['model_response'] = completion.raw
                assert completion.request == row['model_request']
                usage = completion.raw.get('usage') or {}
                cost = usage.get('cost')
                row.update(status='completed', reported_cost_usd=cost)
                if cost is None or not Decimal(str(cost)).is_finite() or not Decimal('0') <= Decimal(str(cost)) <= reserve:
                    row['audit_issue'] = 'Cost missing/invalid or exceeded reservation'
                    self.stopped = True
                for field,limit in [('prompt_tokens',bound),('completion_tokens',self.max_tokens)]:
                    value=usage.get(field)
                    if not isinstance(value,int) or not 0 <= value <= limit:
                        row['audit_issue']='Missing/invalid token usage or reservation bound exceeded'
                        self.stopped=True
                provider = completion.raw.get('provider', '').lower()
                if provider not in self.request_options['provider']['only'] or completion.raw.get('model') != self.model:
                    row['audit_issue'] = 'Unexpected resolved provider/model'
                    self.stopped = True
                if row.get('audit_issue'):
                    row['status'] = 'audit_error'
                return completion
            except BaseException as exc:
                row.update(status='error',error=f'{type(exc).__name__}: {exc}',
                           model_response=getattr(exc,'response_payload',None))
                self.stopped=True
                raise
            finally:
                row['finished_at']=now()
                write_json(self.ledger,data)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--phase',choices=['both','cache','cache-parasail'],default='both',
                        help='cache: full allowlist with synthetic prefix; cache-parasail: double prefix on Parasail only')
    args=parser.parse_args()
    if not args.live:
        print('Plan: Parasail-only then all seven allowed providers; fresh enter-text episode each; $0.05 total cap.')
        return
    from dotenv import load_dotenv
    import browsergym.miniwob  # noqa: F401
    import gymnasium as gym
    from intent_browser.actions import make_action_set
    from intent_browser.runner import run_episode
    load_dotenv(ROOT/'.env',override=False)
    key=os.environ['OPENROUTER_API_KEY']
    os.environ['LD_LIBRARY_PATH']=str(ROOT/'.local/system-libs/usr/lib/x86_64-linux-gnu')+':'+os.getenv('LD_LIBRARY_PATH','')
    os.environ.setdefault('MINIWOB_URL',(ROOT/'.local/miniwob-plusplus/miniwob/html/miniwob').as_uri()+'/')
    ledger=ROOT/'runs/openrouter-session-routing-budget.json'
    results=ROOT/'runs/openrouter-session-routing-results.json'
    # Exclusive suite lock, including across processes; no replay after an error.
    with (ROOT/'runs/openrouter-session-routing-suite.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        reports=json.loads(results.read_text()) if results.exists() else []
        phases=([('cache-parasail',['parasail'])] if args.phase=='cache-parasail' else
                [('cache',list(DEFAULT_PROVIDERS))] if args.phase=='cache' else
                [('narrow',['parasail']),('full',list(DEFAULT_PROVIDERS))])
        for phase,providers in phases:
            backend=RoutingBudgetBackend(key,providers,ledger,
                                         cache_prefix=256 if phase=='cache-parasail' else phase=='cache')
            action_set=make_action_set()
            def environment(video):
                return gym.make('browsergym/miniwob.enter-text',headless=True,slow_mo=250,
                                action_mapping=action_set.to_python_code,record_video_dir=video)
            try:
                directory,summary=run_episode(environment,backend,{
                    'task':'miniwob.enter-text','source':'openrouter-session-routing-probe',
                    'driver':'llm','model':backend.model,'backend':backend.base_url,
                    'headless':True,'verifier':'miniwob','training_eligible':False,'routing_phase':phase,
                    'synthetic_cache_prefix':bool(backend.cache_prefix),
                    'generation':{'temperature':0,'max_tokens':backend.max_tokens,**backend.request_options},
                    'budget':{'cap_usd':str(CAP),'ledger':str(ledger.relative_to(ROOT))},
                },output=ROOT/'runs',max_steps=4,record_video=True)
            finally:
                backend.close()
            rows=[json.loads(line) for line in (directory/'steps.jsonl').read_text().splitlines()]
            observations=[r['routing'] for r in rows]
            resolved=[r['resolved_provider'] for r in observations if r['resolved_provider'] is not None]
            report={'phase':phase,'episode':str(directory.relative_to(ROOT)),
                    'success':summary['success'],'error':summary['error'],'routing':observations,
                    'consistent_provider_observed': len(set(resolved))==1 if len(resolved)>=2 else None,
                    'cache_hit_observed':any((r['cached_tokens'] or 0)>0 for r in observations)}
            reports.append(report)
            write_json(results,reports)
            print(json.dumps(report,indent=2),flush=True)
            if summary['error'] or backend.stopped:
                break


if __name__=='__main__': main()
