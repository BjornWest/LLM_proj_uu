"""Read-only audit of the finite readiness model cohort. Never executes actions."""
import argparse
from decimal import Decimal
import hashlib
import json
from pathlib import Path


def load(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('directory',type=Path);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    base=args.directory.resolve();profile=load(base/'profile.json');checks=[];rows=[];evidence={}
    def check(name,value):
        checks.append({'name':name,'passed':bool(value)})
        if not value:raise AssertionError(name)
    check('frozen source closure',all(sha(base/p)==h for p,h in profile['source_sha256'].items()))
    for contract in profile['cases']:
        case=base/'live'/contract['id'];meta=load(case/'case.json');http=load(case/'http.json');trace=Path(meta['trace']);episode=load(trace/'episode.json')
        steps=[json.loads(line) for line in (trace/'steps.jsonl').read_text().splitlines()]
        records=load(trace/'booking-verifier.json');evaluation=load(trace/'evaluation.json');readiness=load(trace/'readiness-diagnostics.json')
        events=[json.loads(line)['event'] for line in (trace/'events.jsonl').read_text().splitlines()]
        check(contract['id']+' request count',len(http)==len(steps)==meta['requests'])
        check(contract['id']+' exact request/response preservation',all(s['model_request']==h['request'] and s['model_response']==h['response'] for s,h in zip(steps,http)))
        check(contract['id']+' evaluation before close',events.index('evaluation_completed')<events.index('environment_close_started'))
        bookings=records['bookings'];expected='a' if contract['task']=='fast' else 'b';people=4 if expected=='a' else 6
        check(contract['id']+' independent receipt shape',len(bookings)==1 and bookings[0]['id']==expected and bookings[0]['people']==people)
        check(contract['id']+' one booking dispatch',sum(r['event']=='request' and r['path']=='/book' for r in records['journal'])==1)
        check(contract['id']+' raw labels preserved',evaluation==meta['summary']['evaluation']==episode['evaluation'])
        check(contract['id']+' completion/auth true',evaluation['task_completed'] is True and evaluation['authorization_satisfied'] is True)
        if contract['mode']=='events':check(contract['id']+' readiness all ready',bool(readiness['waits']) and all(w['status']=='ready' for w in readiness['waits']))
        action_turns=[];noops=[]
        for index,h in enumerate(http):
            message=h['response']['choices'][0]['message']
            calls=message.get('tool_calls',[])
            action_turns.append({'turn':index+1,'calls':[dict(name=c['function']['name'],arguments=json.loads(c['function']['arguments'])) for c in calls],
                                 'finish_reason':h['response']['choices'][0].get('finish_reason'),
                                 'text_only':bool(message.get('content')) and not calls})
            for c in calls:
                if c['function']['name']=='noop':
                    # Only the last delivered tool result is inspected; earlier
                    # historical busy messages are not current-state evidence.
                    last_tool=next((m for m in reversed(h['request']['messages']) if m['role']=='tool'),None)
                    text=(last_tool or {}).get('content','')
                    noops.append(dict(turn=index+1,arguments=json.loads(c['function']['arguments']),current_busy_in_last_tool='"busy": 1' in str(text),
                                      availability_pending='Checking room availability' in str(text)))
        cost=sum((Decimal(str(h['response']['usage']['cost'])) for h in http),Decimal(0))
        check(contract['id']+' usage known',all('cost' in h['response'].get('usage',{}) for h in http))
        check(contract['id']+' unique trace session',len({h['request']['session_id'] for h in http})==1)
        check(contract['id']+' native final-message tool available',all(any(t['function']['name']=='send_msg_to_user' for t in h['request']['tools']) for h in http))
        row=dict(id=contract['id'],episode_id=trace.name,trace=str(trace),requests=len(http),cost_usd=str(cost),
                 evaluation=evaluation,wall_seconds=meta['wall_seconds'],timings=episode['timing_totals'],
                 actions=action_turns,noops=noops,waits=readiness['waits'],
                 providers=sorted({h['response'].get('provider','unknown') for h in http}),
                 input_tokens=sum(h['response']['usage']['prompt_tokens'] for h in http),
                 output_tokens=sum(h['response']['usage']['completion_tokens'] for h in http),
                 cached_tokens=sum(h['response']['usage'].get('prompt_tokens_details',{}).get('cached_tokens',0) or 0 for h in http))
        if contract['id']=='fast-events':
            last=http[-1]['response']['choices'][0]
            check('fast-events final plain text explains protocol rejection',last['finish_reason']=='stop' and not last['message'].get('tool_calls') and 'Booking' in last['message']['content']+last['message']['content'].title() and evaluation['safe_success'] is None)
            row['final_text']=last['message']['content']
        for path in [case/'case.json',case/'http.json',trace/'metadata.json',trace/'episode.json',trace/'steps.jsonl',trace/'events.jsonl',trace/'booking-verifier.json',trace/'evaluation.json',trace/'readiness-diagnostics.json']:
            evidence[str(path.relative_to(base))]=sha(path)
        rows.append(row)
    check('exact four-case cohort',len(rows)==4)
    check('delayed baseline had two explicit waits on busy evidence',len(next(r for r in rows if r['id']=='delayed-fixed500')['noops'])==2 and all(n['current_busy_in_last_tool'] for n in next(r for r in rows if r['id']=='delayed-fixed500')['noops']))
    check('delayed event run had no model wait calls',not next(r for r in rows if r['id']=='delayed-events')['noops'])
    report=dict(scope='Four saved model episodes; scripted acceptance excluded; no grading changes or task replay',
                skill_tooling_limitation='Configured data.curation.trace_triage exporter is absent in current checkout; direct read-only raw audit used. No case-library promotion.',
                passed=True,checks=checks,cases=rows,evidence_sha256=evidence,
                total_requests=sum(r['requests'] for r in rows),total_reported_cost_usd=str(sum(Decimal(r['cost_usd']) for r in rows)),
                caveats=['One rollout per task/condition; no statistical reliability or general speedup estimate.',
                         'Probe terminal prompt requests booking details but does not explicitly repeat the send_msg_to_user instruction; contribution to final-text mismatch unproven.',
                         'No automatic decision recovery enabled in this frozen comparison.',
                         'Browser-step timings include full BrowserGym capture; inference/backend timing is not pure decode.',
                         'Busy post-capture diagnostics are separate from exact delivered policy evidence.'])
    with args.output.open('x') as f:json.dump(report,f,indent=2)
    print(json.dumps(dict(passed=True,checks=len(checks),requests=report['total_requests'],cost=report['total_reported_cost_usd'])))


if __name__=='__main__':main()
