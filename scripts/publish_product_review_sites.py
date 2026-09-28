"""Local human review page with original-evidence copies, no source mutation."""
import argparse,json,shutil
from pathlib import Path
from html import escape
from markdown_it import MarkdownIt


def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,default=Path('.local/product-review-sites/preview-v5/manifest.json'));a=p.parse_args()
    manifest=json.loads(a.manifest.read_text());out=Path('.local/review');assets=out/'product-review-assets';assets.mkdir(parents=True,exist_ok=True)
    cases={
        'runrepeat':Path('.local/product-review-sites/reference-v1/capture/runrepeat/scrolled'),
        'tomshardware':Path('.local/product-review-sites/reference-v1/capture/tomshardware/scrolled'),
        'untappd':Path('.local/product-review-sites/reference-v1/capture/untappd/scrolled'),
        'lab':Path('.local/product-review-sites/acceptance-v3/footwear-lab-directory/review'),
        'magazine':Path('.local/product-review-sites/acceptance-v3/laptops-editorial-magazine/review'),
        'community':Path('.local/product-review-sites/acceptance-v3/beer-community-feed/review'),
        'same-magazine':Path('.local/product-review-sites/acceptance-v3/footwear-editorial-magazine/review'),
        'same-community':Path('.local/product-review-sites/acceptance-v3/footwear-community-feed/review'),
    }
    for key,prefix in cases.items():
        for suffix in ('.png','.outline.txt','.overview.json','.metrics.json'):
            shutil.copyfile(Path(str(prefix)+suffix),assets/(key+suffix))
    style='''<style>body{font:16px/1.6 system-ui;max-width:1300px;margin:auto;padding:30px;color:#203430;background:#fbfcfb}a{color:#155f98}.grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:22px}.card{border:1px solid #ccd8d2;background:white;padding:20px;border-radius:10px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:22px}img{width:100%;border:1px solid #cdd6d2}iframe{width:100%;height:65vh;border:1px solid #ccc}table{border-collapse:collapse}th,td{border:1px solid #ccc;padding:10px;text-align:left}pre{overflow:auto;padding:16px;background:#edf1ee}.notice{background:#eaf3ed;padding:18px}h1{font-size:38px}.names{display:flex;gap:10px;flex-wrap:wrap}.names span{padding:5px 12px;background:#e7edeb;border-radius:20px}@media(max-width:850px){.grid,.pair{grid-template-columns:1fr}}</style>'''
    report=MarkdownIt('commonmark',{'html':False}).enable('table').render(Path('docs/agents/product-review-sites.md').read_text())
    (out/'product-review-sites-report.html').write_text('<!doctype html><html><meta charset="utf-8"><title>Product review generation report</title>'+style+report+'</html>')
    page='<!doctype html><html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Specialist review sites</title>'+style+'<h1>Specialist review sites</h1><p>Five local publications, three accessible structures, one canonical product world. Start with a site below, then compare the layouts and AX outlines.</p><p class="notice">First browsing foundation: 36 model articles and 864 synthetic reader opinions. Working search, attribute filters, article sections, exact-variant pages, comparisons and review pagination. No independent lab measurements or model/task validation yet.</p><div class="grid">'
    for site in manifest['sites']:
        origin=site['origin'].replace('127.0.0.1','localhost');example=site['example'].replace('127.0.0.1','localhost')
        page+='<section class="card"><h2>'+escape(site['name'])+'</h2><p>'+escape(', '.join(site['families']).replace('_',' '))+'</p><p>'+str(site['article_count'])+' articles · '+escape(site['layout'])+'</p><a href="'+origin+'">Open homepage</a> · <a href="'+example+'">Example review</a></section>'
    page+='</div><p><a href="product-review-sites-report.html">Research, data contract, checks and remaining work</a></p><h2>Merchant-review names</h2><p>Sampled separately from layout or rating quality, stable within a world. <a href="http://localhost:35971/">Open the renamed merchant site: Kundspegeln</a>.</p><div class="names">'
    from environments.merchant_reviews.identity import NAMES
    page+=''.join('<span>'+escape(name)+'</span>' for name in NAMES)+'</div><h2>Three different navigation structures</h2>'
    for key,title,description,ref in [('lab','Specification directory','Left contents, grouped fact tables, right comparison/related links.','runrepeat'),('magazine','Editorial magazine','Masthead, section menu and linked overview/specification/reader pages.','tomshardware'),('community','Community activity','Product facts in a disclosure, rating summary and repeated dated reader entries.','untappd')]:
        page+='<section><h3>'+title+'</h3><p>'+description+'</p><img src="product-review-assets/'+key+'.png" alt="Generated '+title+' screenshot"><details><summary>Reference screenshot and AX outline</summary><p>Reference snapshot includes a consent overlay. Underlying extracted AX is not proof that every control was unobstructed. This is original synthetic implementation, not an imported site.</p><div class="pair"><img src="product-review-assets/'+ref+'.png" alt="Real site reference"><iframe title="'+ref+' AX" src="product-review-assets/'+ref+'.outline.txt"></iframe></div></details></section>'
    page+='<h2>Same footwear data, different AX structures</h2><p>These use the same world, selected SKU and reader corpus. Four reader entries per page for the scripted checks; live previews use twelve. Full outlines are audit reconstructions, not single delivered model prompts.</p><div class="grid">'
    for key,title in [('lab','Directory'),('same-magazine','Magazine overview'),('same-community','Community')]:
        m=json.loads((assets/(key+'.metrics.json')).read_text())
        page+='<section><h3>'+title+'</h3><p>'+str(m['semantic_nodes'])+' semantic nodes · depth '+str(m['max_depth'])+'</p><iframe title="'+title+' AX" src="product-review-assets/'+key+'.outline.txt"></iframe><p><a href="product-review-assets/'+key+'.overview.json">Actual initial AX overview</a></p></section>'
    page+='</div><h2>Family audit and filters</h2><p><a href="product-review-family-audit.html">Open the updated AX comparison, terminology audit and checkbox/range examples.</a></p><h2>Next design discussion</h2><p>How much should sections move between inline text, disclosures and separate pages? How dense should the surrounding articles, fact tables and reader streams be? The factual dataset should stay unchanged when these presentation settings change.</p><p>The next data decision is independent product evidence: test conditions, configuration scope, measurements and noisy opinions. Current facts are catalog specifications; scores are synthetic opinions, not hidden quality labels.</p></html>'
    page=page.replace('</h1>','</h1><p><a href="product-review-structure.html">New: denser review structures, before/after AX and missing world contracts</a> · <a href="review-cookie-popups.html">Cookie-popup designs</a></p>',1)
    (out/'product-review-sites.html').write_text(page)
    print('http://localhost:8876/product-review-sites.html')


if __name__=='__main__':main()
