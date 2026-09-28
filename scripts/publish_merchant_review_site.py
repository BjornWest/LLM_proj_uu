"""Publish local review-site evidence; source captures remain unchanged."""
import json,shutil
from pathlib import Path
from markdown_it import MarkdownIt


def main():
    out=Path('.local/review');assets=out/'merchant-review-assets';assets.mkdir(parents=True,exist_ok=True)
    cases={'reference-home':Path('.local/merchant-reviews/reference-v1/capture/trustpilot-home/scrolled'),
           'reference-company':Path('.local/merchant-reviews/reference-v1/capture/trustpilot-elgiganten/scrolled'),
           'generated-home':Path('.local/merchant-reviews/acceptance-v2/normal/home'),
           'generated-company':Path('.local/merchant-reviews/acceptance-v2/normal/company')}
    for key,prefix in cases.items():
        for suffix in ('.png','.outline.txt','.overview.json','.metrics.json'):
            shutil.copyfile(Path(str(prefix)+suffix),assets/(key+suffix))
    style='<style>body{font:16px/1.5 system-ui;max-width:1200px;margin:auto;padding:25px;color:#26312d}a{color:#175ca0}.pair{display:grid;grid-template-columns:1fr 1fr;gap:18px}img{max-width:100%}iframe{width:100%;height:65vh;border:1px solid #aaa}table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:7px}pre{overflow:auto;background:#eee;padding:15px}.links{display:flex;flex-wrap:wrap;gap:20px;padding:18px;background:#eff6f0}@media(max-width:800px){.pair{grid-template-columns:1fr}}</style>'
    report=MarkdownIt('commonmark',{'html':False}).enable('table').render(Path('docs/agents/merchant-review-site.md').read_text())
    (out/'merchant-review-site-report.html').write_text('<!doctype html><meta charset="utf-8"><title>Merchant review implementation</title>'+style+report)
    page='<!doctype html><meta charset="utf-8"><title>Merchant review site</title>'+style+'<h1>Omdömeskollen</h1><nav class="links"><a href="http://localhost:42503/">Open site</a><a href="http://localhost:42503/review/store-001">Example company</a><a href="merchant-review-site-report.html">Report and generation contract</a></nav><p>Eight generated merchants, 384 reviews. Working search, company profiles, rating/topic/date filters, sorting, pagination and replies. No model calls. No copied real review text.</p><p>Reference documents reported HTTP 403 despite rendering these page structures. Captures show observed content, not unrestricted access to Trustpilot. Generated data is fictional testimony, not proof of merchant safety.</p>'
    for kind in ['home','company']:
        page+='<h2>'+kind.capitalize()+' layout reference</h2><div class="pair"><section><h3>Trustpilot reference</h3><img src="merchant-review-assets/reference-'+kind+'.png" alt="Reference screenshot"></section><section><h3>Generated site</h3><img src="merchant-review-assets/generated-'+kind+'.png" alt="Generated screenshot"></section></div><details><summary>Compare full AX outlines</summary><p>Audit reconstructions, not one model message. Actual initial-overview JSON is linked below.</p><div class="pair"><iframe title="Reference '+kind+' AX" src="merchant-review-assets/reference-'+kind+'.outline.txt"></iframe><iframe title="Generated '+kind+' AX" src="merchant-review-assets/generated-'+kind+'.outline.txt"></iframe></div></details>'
    page+='<p><a href="merchant-review-assets/generated-company.overview.json">Generated company: actual initial overview</a></p>'
    (out/'merchant-review-site.html').write_text(page)
    print('http://localhost:8876/merchant-review-site.html')
if __name__=='__main__':main()
