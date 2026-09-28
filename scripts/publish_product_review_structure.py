"""Local, read-only report for reference-inspired review structures."""
import json,shutil
from html import escape
from pathlib import Path
from markdown_it import MarkdownIt


def main():
    out=Path('.local/review');assets=out/'product-review-structure-assets';assets.mkdir(exist_ok=True)
    root=Path('.local/product-review-sites')
    manifest=json.loads((root/'preview-v4/manifest.json').read_text())
    links=' · '.join('<a href="'+escape(s['example'].replace('127.0.0.1','localhost'))+'">'+escape(s['name'])+'</a>' for s in manifest['sites'])
    style='<style>body{font:16px/1.65 system-ui;max-width:1500px;margin:auto;padding:28px;color:#23352f}.triple{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:18px}img{width:100%;border:1px solid #bbb}iframe{width:100%;height:65vh;border:1px solid #aaa}table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:8px;vertical-align:top}a{color:#145987}pre{overflow:auto}@media(max-width:900px){.triple{display:block}}</style>'
    page='<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Product review structures</title>'+style+'<h1>Review sites: closer to real page structure</h1><p>'+links+'</p><p><a href="product-review-structure-report.html">Implementation, measurements and missing-world requirements</a> · <a href="product-review-sites.html">Original design showcase</a></p><p>Same generated facts and twelve reader notes per review page; deeper navigation and meaningful tables. Reference screenshots include consent overlays. This compares observed structures, not visual clones or full upstream imports.</p>'
    for name,reference,title in [('footwear','runrepeat','Directory review'),('computing','tomshardware','Magazine article'),('beer','untappd','Community profile')]:
        page+='<h2>'+title+'</h2><div class="triple">'
        captures=[('Before',root/'family-audit-v1/live-final'/name/'initial'),('Now',root/'structure-v1/capture'/name/'page'),('Reference',root/'reference-v1/capture'/reference/'scrolled')]
        for label,base in captures:
            key=name+'-'+label.lower()
            for ext in ('.png','.outline.txt','.metrics.json'):shutil.copyfile(str(base)+ext,assets/(key+ext))
            m=json.loads(Path(str(base)+'.metrics.json').read_text())
            page+='<section><h3>'+label+'</h3><p>'+str(m['semantic_nodes'])+' AX nodes · '+str(m['interactive_nodes'])+' controls · depth '+str(m['max_depth'])+'</p><a href="product-review-structure-assets/'+key+'.png"><img alt="'+title+' '+label+'" src="product-review-structure-assets/'+key+'.png"></a></section>'
        page+='</div><details><summary>Compare the actual AX outlines</summary><div class="triple">'+''.join('<section><h3>'+label+'</h3><iframe title="'+title+' '+label+' accessibility tree" src="product-review-structure-assets/'+name+'-'+label.lower()+'.outline.txt"></iframe></section>' for label,_ in captures)+'</div></details>'
    page+='<h2>Still missing from the world</h2><p>Independent lab/test results and grounded expert verdicts; bound retailer offers and deal pages; photo/video collections; brewery and venue destinations; authenticated social/write actions; news, subscription and advertising systems. Existing product facts, opinions and identities power the new routes. No missing feature is represented by a fake working button.</p><p>69 unit/HTTP tests, eight native interaction cases, thirteen page captures. No model calls. Local prototypes; not deployed or certified task environments.</p></html>'
    (out/'product-review-structure.html').write_text(page)
    doc=MarkdownIt('commonmark',{'html':False}).enable('table').render(Path('docs/agents/product-review-structure.md').read_text())
    (out/'product-review-structure-report.html').write_text('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Review structure report</title>'+style+doc)
    print('http://localhost:8876/product-review-structure.html')


if __name__=='__main__':main()
