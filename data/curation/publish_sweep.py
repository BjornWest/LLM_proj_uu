"""Render a read-only local HTML dashboard from saved sweep cases."""
import argparse
from collections import defaultdict
from datetime import datetime,timezone
from decimal import Decimal
import hashlib
import html
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def read(path):return json.loads(path.read_text())
def esc(value):return html.escape(str(value))
def verdict(value):return 'unknown' if value is None else 'pass' if value else 'fail'


def render(suite,destination):
    profile=read(suite/'profile.json'); groups=defaultdict(list); records=[]
    for case in profile['cases']:
        path=suite/'cases'/f"{case['case_id']}.json"
        record=read(path) if path.exists() else {**case,'status':'unexecuted'}
        groups[(case['source'],case['task'],case['condition'])].append(record);records.append(record)
    done=[r for r in records if r['status']=='completed']
    total=len(profile['cases']); successes=sum(r['evaluation']['safe_success'] is True for r in done)
    unknown=sum(r['evaluation']['safe_success'] is None for r in done)
    tech=sum(bool(r['evaluation']['technical_error']) for r in done)
    spent=sum((Decimal(r['reported_cost_usd']) for r in done),Decimal(0))
    budget=read(suite.parent/'budget.json') if (suite.parent/'budget.json').exists() else None
    pieces=['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">',
        '<title>Browser agent sweep</title><style>body{font:16px/1.55 system-ui;max-width:1250px;margin:32px auto;padding:0 20px;color:#172435}h1{line-height:1.15}table{border-collapse:collapse;width:100%}th,td{padding:9px;border-bottom:1px solid #d8e0e8;text-align:left;vertical-align:top}th{background:#edf2f6}a{color:#075fa8}.pass{color:#176c3c}.fail{color:#a82e2e}.unknown{color:#775714}.cards{display:flex;gap:12px;flex-wrap:wrap}.card{padding:14px 20px;background:#edf3f8;border-radius:8px}.card strong{display:block;font-size:1.5em}details{margin:14px 0;border:1px solid #d8e0e8;border-radius:6px;padding:12px}summary{cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f5f7;padding:12px}select{padding:8px;margin:12px 0}.wrap{overflow:auto}code{font-size:.85em}</style>',
        '<h1>Browser-agent development sweep</h1>',f'<p>{esc(suite.name)} · Updated {esc(datetime.now(timezone.utc).isoformat(timespec="seconds"))}</p>',
        '<div class="cards">',f'<div class="card"><strong>{len(done)} / {total}</strong>episodes completed</div>',
        f'<div class="card"><strong>{successes}</strong>safe completions</div>',f'<div class="card"><strong>{unknown}</strong>unknown safe outcomes</div>',
        f'<div class="card"><strong>{tech}</strong>technical interruptions</div>',f'<div class="card"><strong>${spent:.6f}</strong>reported completed-case cost</div></div>',
        '<p>This is a selected, locally derived development suite, not a published benchmark score. Three rounds are planned; unexecuted conditions remain visible. Clean/deceptive pairs share goals. Provider routing and generated Chaos variants can differ between runs.</p>']
    if budget:pieces.append(f"<p>Cumulative calibration reservations: <strong>${esc(budget['reserved_cost_usd'])} / ${esc(budget['approved_cap_usd'])}</strong>, including historical ${esc(budget['carried_reservations_usd'])}. Reservations are retained, not refunds or actual spend. Team demo funding is separate.</p>")
    pieces += ['<h2>Task coverage</h2><div class="wrap"><table><tr><th>Source / task</th><th>Condition</th><th>Run</th><th>Safe: pass / fail / unknown</th><th>Completion failures</th><th>Authorization failures</th><th>Technical errors</th></tr>']
    for (source,task,condition),values in groups.items():
        executed=[v for v in values if v['status']=='completed']
        vals=[sum(v['evaluation']['safe_success'] is label for v in executed) for label in (True,False,None)]
        failures=[sum(v['evaluation'][field] is False for v in executed) for field in ('task_completed','authorization_satisfied')]
        errors=sum(bool(v['evaluation']['technical_error']) for v in executed)
        pieces.append(f'<tr><td>{esc(source)} / {esc(task)}</td><td>{esc(condition)}</td><td>{len(executed)}/{len(values)}</td><td>{" / ".join(map(str,vals))}</td><td>{failures[0]}</td><td>{failures[1]}</td><td>{errors}</td></tr>')
    pieces += ['</table></div><h2>Inspect episodes</h2><label>Show <select id="filter"><option value="all">All completed episodes</option><option value="fail">Safe failures</option><option value="unknown">Unknown / interrupted</option><option value="pass">Safe passes</option></select></label>']
    for case in done:
        directory=ROOT/case['episode'];episode=read(directory/'episode.json')
        steps=[json.loads(l) for l in (directory/'steps.jsonl').read_text().splitlines()]
        evaluation=case['evaluation'];status=verdict(evaluation['safe_success'])
        key=hashlib.sha256(('browsergym:'+directory.name).encode()).hexdigest()[:20]
        actions='\n'.join(f"{s['step']+1}. {s.get('action') or '[no parsed action]'}"+(f" — {s.get('error') or s.get('action_error')}" if s.get('error') or s.get('action_error') else '') for s in steps)
        usage=[s['model_response'].get('usage',{}) for s in steps if isinstance(s.get('model_response'),dict)]
        prompt=sum(u.get('prompt_tokens',0) or 0 for u in usage);output=sum(u.get('completion_tokens',0) or 0 for u in usage)
        pieces.append(f'<details class="episode" data-status="{status}"><summary><strong>{esc(case["case_id"])}</strong> · <span class="{status}">{status}</span> · {case["requests"]} calls · {esc(", ".join(dict.fromkeys(case["providers"])))}</summary>')
        pieces.append(f'<p><a href="http://localhost:8878/#{key}">Open full trace</a> · {esc(directory.name)} · step limit: {profile["config"]["max_steps"]} · stop: {esc(case["stop_reason"])}</p>')
        pieces.append(f'<p>Completion: {verdict(evaluation["task_completed"])}; authorization: {verdict(evaluation["authorization_satisfied"])}; exposure: {esc(evaluation["injection_exposed"])}; action errors: {case["action_error_count"]}. Prompt tokens across requests: {prompt}; output tokens: {output}; reported cost: ${esc(case["reported_cost_usd"])}.</p>')
        pieces.append('<pre>'+esc(actions)+'</pre>')
        if evaluation['unauthorized_effects']:pieces.append('<p>Unauthorized effects: '+esc(', '.join(evaluation['unauthorized_effects']))+'</p>')
        if evaluation['technical_error']:pieces.append('<p>Technical interruption: '+esc(evaluation['technical_error'])+'</p>')
        pieces.append('</details>')
    pieces += ['<h2>Interpretation</h2><p>Completion, authorization, exposure, and technical failures are separate. A failed or interrupted request is never automatically retried. Task state is verified before browser close; claiming “Done” alone does not establish success. All records remain training-ineligible. The model receives accessibility-tree text; screenshots in the viewer are review evidence, not model vision input.</p>',
               '<script>document.querySelector("#filter").addEventListener("change",e=>document.querySelectorAll(".episode").forEach(x=>x.hidden=e.target.value!=="all"&&x.dataset.status!==e.target.value))</script></html>']
    destination.parent.mkdir(parents=True,exist_ok=True);destination.write_text(''.join(pieces))
    print(json.dumps({'episodes':len(done),'safe':successes,'unknown':unknown,'reported_cost':str(spent),'output':str(destination)}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--suite',default='external-baseline-v1');p.add_argument('--output',type=Path,default=ROOT/'.local/review/external-sweep.html')
    a=p.parse_args();render(ROOT/'data/curation/sweeps'/a.suite,a.output)
