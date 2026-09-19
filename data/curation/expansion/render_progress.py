"""Render the non-authoritative local work board, without private answer keys."""
import argparse
from datetime import datetime, timezone
from html import escape
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def render():
    from data.curation.expansion.accepted_index import collect
    state = json.loads((ROOT/'data/curation/expansion/progress.json').read_text())
    tasks=collect()
    catalog_rows=[]
    for task in tasks:
        values=[task['id'],', '.join(task['sites']),task['origin'],task['template_id'],task['goal']]
        catalog_rows.append('<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in values)+'</tr>')
    rows = []
    for name, dataset in state['datasets'].items():
        total = dataset.get('accepted_development_tasks', 0)
        authored = dataset.get('accepted_authored_instances', 0)
        rows.append('<tr>'+''.join('<td>'+escape(str(v))+'</td>' for v in [name,
            total-authored, authored, total, dataset.get('model_tested_new_tasks', 0)])+'</tr>')
    downloads = ROOT/state.get('resource_ledger','.local/curation-expansion/downloads-ranged/ranges-ledger.json')
    download_note = 'No current download ledger.'
    if downloads.exists():
        ledger = json.loads(downloads.read_text())
        completed = sum(v.get('completed_bytes', 0) for v in ledger['assets'].values())
        download_note = f'{completed / 1e9:.2f} GB in completed data ranges; {ledger["reserved_bytes"] / 1e9:.2f} GB reserved of the approved 200 GB. Partial ranges are additional; images are included in reservations. Maps and Wikipedia are not yet marked runnable. Ledger: {downloads.relative_to(ROOT)}.'
    return '<!doctype html><meta charset="utf-8"><title>Dataset expansion</title><style>body{max-width:950px;margin:40px auto;padding:0 20px;font:17px/1.5 system-ui;color:#19242b;background:#f7f9fb}table{border-collapse:collapse;width:100%;background:white}th,td{padding:12px;text-align:left;border-bottom:1px solid #ccd5db}code{font-size:14px}h1{font-size:30px}.note{background:#fff3ce;padding:14px}</style>'+ \
        '<h1>General-browsing dataset expansion</h1><p>WebArena and Tricky. Existing sites/tasks first; new dark patterns deferred. Target: 100 usable tasks per dataset, with templates and instances counted separately.</p>'+ \
        '<p>Expansion closed for review at user request: 100 Tricky and 103 WebArena tasks. Maps/Wikipedia staging is paused. Snapshot '+escape(datetime.now(timezone.utc).isoformat())+'. This board summarizes evidence; it does not replace the versioned reports.</p>'+ \
        '<table><tr><th>Dataset</th><th>Accepted original</th><th>Accepted authored</th><th>Total</th><th>Model-tested</th></tr>'+''.join(rows)+'</table>'+ \
        '<p>Tricky authored template IDs: '+escape(str(state['datasets']['trickyarena'].get('accepted_authored_templates',0)))+'. Templates, instances and website diversity are separate counts.</p>'+ \
        '<p class="note">Accepted development tasks have scoped scripted evidence and independent review. This is not training approval, full-site safety certification, or teacher-model performance. No model calls were made by this expansion work.</p>'+ \
        '<h2>Current boundaries</h2><ul><li>Tricky: shopping, health records, news, music catalog. Some mutations/audio/downloads are blocked by actual source defects. New objectives are separately attributed project-authored tasks.</li>'+ \
        '<li>WebArena: shopping and forum task expansion. Separate state supports mutation testing. Shopping Admin is a secondary back-office site diagnostic; Maps/Wikipedia remain unvalidated and paused.</li>'+ \
        '<li>Broken or incomplete runs remain recorded. Native grader pass, actual final state, authorization and technical failures are separate.</li></ul>'+ \
        '<h2>Resources</h2><p>'+escape(download_note)+'</p>'+ \
        '<h2>Reproducible work records</h2><ul><li><code>docs/agents/dataset-expansion.md</code></li><li><code>data/curation/expansion/progress.json</code></li><li><code>data/curation/expansion/*independent-review.json</code></li></ul>'+ \
        '<h2>Browse the accepted tasks</h2><p>Tricky: 81 declared templates (21 original task families + 60 authored templates). WebArena: 30 upstream templates. Six website contexts total; repeated instances are not new sites or templates.</p>'+ \
        '<label for="filter">Filter by task ID, site, origin, or goal</label><input id="filter" type="search" style="display:block;width:95%;padding:10px;margin:12px 0"><p id="count">203 tasks</p>'+ \
        '<div style="overflow-x:auto"><table id="catalog"><thead><tr><th>Task</th><th>Site</th><th>Origin</th><th>Template</th><th>Goal</th></tr></thead><tbody>'+''.join(catalog_rows)+'</tbody></table></div>'+ \
        '<script>document.getElementById("filter").addEventListener("input",function(){let n=0;const q=this.value.toLowerCase();document.querySelectorAll("#catalog tbody tr").forEach(r=>{r.hidden=!r.textContent.toLowerCase().includes(q);if(!r.hidden)n++});document.getElementById("count").textContent=n+" tasks"});</script>'+ \
        '<p>Regenerate this board with <code>python3 -m data.curation.expansion.render_progress</code>.</p>'


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, default=ROOT/'.local/review/dataset-expansion/index.html')
    args = p.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render())
    print(args.output)
