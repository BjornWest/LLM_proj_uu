"""Publish saved cookie-popup comparisons with live preview links."""
import json,shutil
from pathlib import Path
from markdown_it import MarkdownIt


def main():
    out=Path('.local/review');assets=out/'review-consent-assets';assets.mkdir(exist_ok=True)
    root=Path('.local/product-review-sites/consent-v1/acceptance')
    style='<style>body{font:16px/1.6 system-ui;max-width:1400px;margin:auto;padding:28px;color:#24342d}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:20px}img{width:100%}iframe{width:100%;height:55vh}table{border-collapse:collapse}td,th{border:1px solid #bbb;padding:10px}a{color:#14618b}pre{overflow:auto}@media(max-width:900px){.grid{display:block}}</style>'
    html='<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Cookie popup designs</title>'+style+'<h1>Three independent cookie-popup designs</h1><p>These can be combined with any review-page layout. The screenshots compare the same footwear page. Try the live examples below; after choosing, use Cookie settings to reopen them.</p><p><a href="review-cookie-popups-report.html">Behavior, diagnostics and validation</a> · <a href="product-review-structure.html">Review site structures</a></p><div class="grid">'
    examples=[('bottom-banner','Bottom banner','http://localhost:33429/reviews/laptops-model-0002'),('center-modal','Centered modal','http://localhost:44673/reviews/cat_food-model-0004'),('side-drawer','Side drawer','http://localhost:46493/reviews/footwear-model-0001')]
    for design,title,url in examples:
        for stage in ['initial','preferences']:
            for ext in ['.png','.outline.txt','.metrics.json']:shutil.copyfile(root/(design+'-lab-directory')/(stage+ext),assets/(design+'-'+stage+ext))
        html+='<section><h2>'+title+'</h2><p><a href="'+url+'">Try this design</a></p><a href="review-consent-assets/'+design+'-initial.png"><img alt="'+title+'" src="review-consent-assets/'+design+'-initial.png"></a><details><summary>Open preference controls and AX outlines</summary><img alt="'+title+' preferences" src="review-consent-assets/'+design+'-preferences.png"><h3>Initial AX</h3><iframe title="'+title+' initial AX" src="review-consent-assets/'+design+'-initial.outline.txt"></iframe><h3>Preferences AX</h3><iframe title="'+title+' preferences AX" src="review-consent-assets/'+design+'-preferences.outline.txt"></iframe></details></section>'
    html+='</div><p>Banner: direct necessary-only choice and page remains available. Modal: direct necessary-only choice and switches. Drawer: manage preferences first, then reject optional cookies, with purpose disclosures. Optional choices are off initially. No real tracking services.</p><p>All nine layout/design combinations passed scripted browser checks. Local previews; no model calls or deployment.</p>'
    (out/'review-cookie-popups.html').write_text(html)
    rendered=MarkdownIt('commonmark',{'html':False}).enable('table').render(Path('docs/agents/review-cookie-popups.md').read_text())
    (out/'review-cookie-popups-report.html').write_text('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Consent implementation</title>'+style+rendered)
    print('http://localhost:8876/review-cookie-popups.html')


if __name__=='__main__':main()
