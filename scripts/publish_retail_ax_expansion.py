"""Build a disposable local review from saved retail AX evidence; no network calls."""
import html
import json
from pathlib import Path
import shutil

from markdown_it import MarkdownIt

ROOT = Path('.local/retail-ax-study')
BASE = ROOT / '20260925-expansion-v1'
OLD = ROOT / '20260925-v1'
OUT = Path('.local/review')
ASSETS = OUT / 'retail-ax-expanded-assets'
CASES = {
    'ikea': ('IKEA: post-scroll', BASE / 'followup/ikea/scrolled'),
    'ikea-before-scroll': ('IKEA: before scroll', BASE / 'followup/ikea/post-consent'),
    'ikea-materials': ('IKEA: material disclosure', BASE / 'followup/ikea/materials'),
    'uniqlo': ('Uniqlo: product (out of stock)', BASE / 'followup/uniqlo/scrolled'),
    'elgiganten': ('Earlier Elgiganten: product', OLD / 'capture-v2/elgiganten/scrolled'),
    'amazon': ('Earlier Amazon: product', OLD / 'capture-v2/amazon/scrolled'),
    **{d: ('Our ' + d, OLD / f'capture-v2/local-{d}/initial') for d in
       ('department-market', 'editorial-boutique', 'technical-catalog')},
}


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    rows = {}
    for key, (label, prefix) in CASES.items():
        for suffix in ('.outline.txt', '.metrics.json', '.nonverbose.json', '.overview.json', '.png'):
            shutil.copyfile(Path(str(prefix) + suffix), ASSETS / (key + suffix))
        rows[key] = {'label': label, 'metrics': json.loads(Path(str(prefix) + '.metrics.json').read_text())}
    style = '<style>body{font:16px/1.5 system-ui;margin:24px;color:#202d36}a{color:#075985}table{border-collapse:collapse}td,th{padding:7px;border:1px solid #ccc}pre{overflow:auto;background:#f5f6f7;padding:12px}select{padding:8px;font:inherit}.panels{display:grid;grid-template-columns:1fr 1fr;gap:18px}.panel{min-width:0}.panel pre{height:65vh;font:12px/1.4 monospace}.panel img{max-width:100%}.report{max-width:1100px;margin:auto}@media(max-width:800px){.panels{grid-template-columns:1fr}}</style>'
    document = Path('docs/agents/retail-ax-layout-expansion.md').read_text()
    rendered = MarkdownIt('commonmark', {'html': False}).enable('table').render(document)
    (OUT / 'retail-ax-layout-plan.html').write_text('<!doctype html><meta charset="utf-8"><title>Dense retail AX layout plan</title>' + style + '<article class="report">' + rendered + '</article>')
    panel = '<section class="panel"><select class="source"></select><p class="metrics"></p><pre></pre><img hidden alt="Saved browser viewport"></section>'
    content = r'''<!doctype html><meta charset="utf-8"><title>Expanded retailer AX references</title>STYLE
<h1>Retail page structure: additional references</h1>
<p><a href="retail-ax-layout-plan.html">Findings, proposed layout and dependency/effort map</a> · <a href="retail-ax-comparison.html">Earlier study</a></p>
<p>Real saved BrowserGym non-verbose captures, compared with our existing layouts. No new renderer is implemented here. Decathlon and B&amp;H returned security pages and are excluded. Uniqlo is an out-of-stock product state.</p>
<p>Full outlines are audit reconstructions, not one model message. The actual initial overview has a 1,000-token budget; offscreen/extracted nodes are not necessarily visible or tested controls. See the report for frame-extraction limitations.</p>
<label>View <select id="view"><option value="outline.txt">AX outline</option><option value="overview.json">Actual initial overview</option><option value="nonverbose.json">Full non-verbose projection</option><option value="png">Screenshot</option></select></label>
<div class="panels">PANELS</div>
<script>const data=CONFIG;let rev=0;
for(const s of document.querySelectorAll('.source')){for(const [k,v] of Object.entries(data)){const o=document.createElement('option');o.value=k;o.textContent=v.label;s.append(o);}s.addEventListener('change',render);}
document.querySelectorAll('.source')[1].value='department-market';document.querySelector('#view').addEventListener('change',render);
async function render(){const r=++rev,suffix=document.querySelector('#view').value;await Promise.all([...document.querySelectorAll('.panel')].map(async p=>{const k=p.querySelector('select').value,m=data[k].metrics;p.querySelector('.metrics').textContent=`${m.semantic_nodes} retained nodes · ${m.interactive_nodes} interactive roles · ${m.headings.length} headings · max depth ${m.max_depth}`;const image=p.querySelector('img'),pre=p.querySelector('pre'),url=`retail-ax-expanded-assets/${k}.${suffix}`;image.hidden=suffix!=='png';pre.hidden=suffix==='png';if(suffix==='png'){image.src=url;return;}const response=await fetch(url);if(!response.ok)throw Error(response.status);const text=await response.text();if(r===rev)pre.textContent=text;}));}render();</script>'''
    content = content.replace('STYLE', style).replace('PANELS', panel * 2).replace('CONFIG', json.dumps(rows, ensure_ascii=False).replace('<', '\\u003c'))
    (OUT / 'retail-ax-expanded.html').write_text(content)
    print('http://localhost:8876/retail-ax-expanded.html')


if __name__ == '__main__':
    main()
