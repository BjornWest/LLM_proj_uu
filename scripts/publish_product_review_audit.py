"""Publish the local family audit; preserve original captures and their hashes."""
import json,shutil
from pathlib import Path
from markdown_it import MarkdownIt


def main():
    out=Path('.local/review');assets=out/'product-review-family-assets';assets.mkdir(parents=True,exist_ok=True)
    root=Path('.local/product-review-sites/family-audit-v1')
    sources={'wine-before':root/'before/wine-catalog/initial','wine-after':root/'live-final/wine-catalog/initial',
             'food-before':root/'before/pets/initial','food-after':root/'live-final/pets/initial'}
    for key,path in sources.items():
        for ext in ('.png','.outline.txt','.overview.json','.metrics.json'):shutil.copyfile(Path(str(path)+ext),assets/(key+ext))
    style='<style>body{font:16px/1.6 system-ui;max-width:1250px;margin:auto;padding:28px;color:#20332e}.pair{display:grid;grid-template-columns:1fr 1fr;gap:22px}img{width:100%;border:1px solid #bbb}iframe{width:100%;height:60vh}table{border-collapse:collapse}th,td{border:1px solid #ccc;padding:10px}a{color:#146299}pre{overflow:auto}@media(max-width:800px){.pair{grid-template-columns:1fr}}</style>'
    report=MarkdownIt('commonmark',{'html':False}).enable('table').render(Path('docs/agents/product-review-family-audit.md').read_text())
    (out/'product-review-family-report.html').write_text('<!doctype html><meta charset="utf-8"><title>Review-site family audit</title>'+style+report)
    page='<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Product-review family audit</title>'+style+'<h1>Product-aware review pages and filters</h1><p><a href="product-review-sites.html">All five sites</a> · <a href="http://localhost:45235/catalog">Try the wine filters</a> · <a href="http://localhost:44673/catalog">Try the pet-food filters</a> · <a href="product-review-family-report.html">Full audit and evidence</a></p><p>Multiple choices within a field; numeric bounds for ordered properties; separate ingredient exclusions. Shared wording now follows the product family rather than the site layout.</p><table><tr><th>Review example</th><th>Our AX nodes</th><th>Real reference</th></tr><tr><td>Footwear</td><td>388</td><td>RunRepeat: 1699</td></tr><tr><td>Laptop overview</td><td>100 (specifications: 126; reader page: 309)</td><td>Tom’s Hardware: 567</td></tr><tr><td>Beer</td><td>368</td><td>Untappd: 669</td></tr><tr><td>Wine</td><td>372</td><td>No valid native reference</td></tr><tr><td>Cat/dog food</td><td>392 each</td><td>No valid native reference</td></tr></table><p>Semantic AX nodes, not message tokens. Generated reviews show twelve reader notes per page. Separate article pages repeat navigation; their totals should not be added as unique content. Real snapshots include consent and surrounding content. Our pages remain materially smaller.</p>'
    for key,title in [('wine','Discoverable, multi-value filters'),('food','Product-specific wording')]:
        page+='<h2>'+title+'</h2><div class="pair">'
        for kind in ('before','after'):page+='<section><h3>'+kind.title()+'</h3><img alt="'+key+' '+kind+'" src="product-review-family-assets/'+key+'-'+kind+'.png"></section>'
        page+='</div><details><summary>Inspect before/after AX</summary><div class="pair">'+''.join('<iframe title="'+key+' '+k+' AX" src="product-review-family-assets/'+key+'-'+k+'.outline.txt"></iframe>' for k in ('before','after'))+'</div></details>'
    page+='<p>The final preview also consumes the product owner’s grape/colour correction. Original captures are preserved; a separate fixed-corpus audit isolates the presentation changes. No model calls.</p>'
    (out/'product-review-family-audit.html').write_text(page)
    print('http://localhost:8876/product-review-family-audit.html')


if __name__=='__main__':main()
