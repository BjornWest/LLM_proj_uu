"""Publish a disposable local review of saved captures, never edit the originals."""
import html,json,shutil
from pathlib import Path
BASE=Path('.local/retail-ax-study/20260925-v1')
OUT=Path('.local/review');ASSETS=OUT/'retail-ax-study-v1'
CASES={
 'elgiganten':('Elgiganten: product','capture-v2/elgiganten/scrolled'),
 'elgiganten-specs':('Elgiganten: specifications open','disclosures/elgiganten/specifications'),
 'elgiganten-cookies':('Elgiganten: initial cookie dialog','capture-v2/elgiganten/initial'),
 'amazon':('Amazon: product (delivery country: Sweden)','capture-v2/amazon/scrolled'),
 'amazon-interstitial':('Amazon: second-session interstitial','disclosures/amazon/scrolled'),
 **{d:(f'Our {d}',f'capture-v2/local-{d}/initial') for d in ('department-market','editorial-boutique','technical-catalog')},
}

def main():
 ASSETS.mkdir(parents=True,exist_ok=True);data={}
 for key,(label,path) in CASES.items():
  source=BASE/path
  for suffix in ('.outline.txt','.metrics.json','.nonverbose.json','.overview.json','.png','.raw-ax.json'):
   shutil.copyfile(Path(str(source)+suffix),ASSETS/(key+suffix))
  m=json.loads(Path(str(source)+'.metrics.json').read_text())
  data[key]={'label':label,'metrics':m}
 report=Path('docs/agents/retail-ax-reference-study.md').read_text()
 (OUT/'retail-ax-study-report.html').write_text('<!doctype html><meta charset="utf-8"><title>Retail AX study report</title><style>body{max-width:1100px;margin:35px auto;padding:0 20px;font:16px/1.6 system-ui}pre{white-space:pre-wrap;font:inherit}</style><a href="retail-ax-comparison.html">Back to comparison</a><pre>'+html.escape(report)+'</pre>')
 content=r'''<!doctype html><meta charset="utf-8"><title>Real retail pages versus our AX designs</title>
<style>body{font:16px/1.5 system-ui;margin:25px;color:#1c2830}header{max-width:1100px}a{color:#075985}#panels{display:grid;grid-template-columns:1fr 1fr;gap:20px}.panel{min-width:0;border:1px solid #cbd5e1;padding:16px}select,input{padding:7px;font:inherit;max-width:100%}pre{height:65vh;overflow:auto;font:12px/1.5 monospace;white-space:pre}img{max-width:100%}.metrics{padding:8px;background:#f0f4f5}table{border-collapse:collapse}td,th{padding:6px 14px;border:1px solid #ccd} @media(max-width:850px){#panels{grid-template-columns:1fr}}</style>
<header><h1>Real retail AX versus our generated pages</h1><p>Captured with BrowserGym 0.14.3 and the current compact, non-verbose AX presenter. No model calls, accounts or purchases. Both supplied product pages loaded in the first sessions.</p>
<table><tr><th>Page</th><th>Semantic nodes</th><th>Interactive roles</th><th>Max depth</th></tr><tr><td>Elgiganten</td><td>1,285 → 1,880 with specifications</td><td>196 → 213</td><td>16</td></tr><tr><td>Amazon</td><td>621</td><td>181</td><td>7</td></tr><tr><td>Our three designs</td><td>87–139</td><td>16–24</td><td>8–9</td></tr></table>
<p><b>Main finding:</b> we need meaningful breadth, competing purchase paths and repeated contextual controls—not artificial nesting. Elgiganten's main contains 1,145 nodes; Amazon's main has 133 and much more surrounding site furniture. Our main regions contain 69–96.</p>
<p>Elgiganten exposes seven identically named cart buttons. Amazon has storage, colour, carrier and condition choices; the selected variant cannot ship to Sweden. The Amazon URL actually opened a renewed iPhone 17 Pro Max. A second fresh visit returned an interstitial; it is not counted as the product page.</p>
<p><a href="retail-ax-study-report.html">Full report, recommendations and limitations</a> · <a href="https://www.elgiganten.se/product/mobiler-tablets-smartklockor/mobiltelefon/apple-iphone-18-pro-smarttelefon-256gb-black/1141337" target="_blank" rel="noopener">Original Elgiganten page</a> · <a href="https://www.amazon.com/dp/B0FTCWXD9K" target="_blank" rel="noopener">Original Amazon product</a></p>
<label>View <select id="view"><option value="outline">Non-verbose tree outline</option><option value="overview">Actual budgeted initial overview</option><option value="image">Screenshot</option><option value="json">Full non-verbose node projection</option></select></label>
<label>Find within tree <input id="filter" placeholder="e.g. radio, heading, kundvagn"></label>
<p><small>Full trees are inspection reconstructions; the model initially gets a ≤1,000-token overview and retrieves more through AX tools. Filtered lines are a viewing aid, not a different capture. Semantic state is retained; class names and verbose extraction IDs are excluded from the outline. Captured text can contain untrusted website claims.</small></p></header>
<div id="panels"><section class="panel"><select class="source" id="left"></select><p class="metrics"></p><p><a class="raw">Raw AX</a> · <a class="projection">Non-verbose JSON</a></p><pre></pre><img hidden alt="Browser screenshot"></section><section class="panel"><select class="source" id="right"></select><p class="metrics"></p><p><a class="raw">Raw AX</a> · <a class="projection">Non-verbose JSON</a></p><pre></pre><img hidden alt="Browser screenshot"></section></div>
<script>const DATA=CONFIG;let revision=0;for(const menu of document.querySelectorAll('.source')){for(const [key,v] of Object.entries(DATA)){const o=document.createElement('option');o.value=key;o.textContent=v.label;menu.appendChild(o);}menu.onchange=refresh;}document.querySelector('#left').value='elgiganten';document.querySelector('#right').value='department-market';
async function refresh(){const rev=++revision;const view=document.querySelector('#view').value,query=document.querySelector('#filter').value.toLowerCase();await Promise.all([...document.querySelectorAll('.panel')].map(async panel=>{const key=panel.querySelector('.source').value,m=DATA[key].metrics,prefix='retail-ax-study-v1/'+key;panel.querySelector('.metrics').textContent=`${m.semantic_nodes} semantic nodes · ${m.interactive_nodes} interactive roles · depth ${m.max_depth} (median ${m.median_depth}) · ${m.headings.length} headings`;panel.querySelector('.raw').href=prefix+'.raw-ax.json';panel.querySelector('.projection').href=prefix+'.nonverbose.json';panel.querySelector('img').hidden=view!=='image';panel.querySelector('pre').hidden=view==='image';if(view==='image'){panel.querySelector('img').src=prefix+'.png';return;}const suffix=view==='outline'?'.outline.txt':view==='overview'?'.overview.json':'.nonverbose.json';const response=await fetch(prefix+suffix);let text=await response.text();if(query&&view==='outline')text=text.split('\n').filter(line=>line.toLowerCase().includes(query)).join('\n');if(rev===revision)panel.querySelector('pre').textContent=text;}));}
document.querySelector('#view').onchange=refresh;document.querySelector('#filter').oninput=refresh;refresh();</script>'''.replace('CONFIG',json.dumps(data,ensure_ascii=False).replace('</','<\\/'))
 (OUT/'retail-ax-comparison.html').write_text(content)
 print('http://localhost:8876/retail-ax-comparison.html')
if __name__=='__main__':main()
