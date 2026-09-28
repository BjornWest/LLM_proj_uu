"""Publish a disposable local R13 review from retained captures and preview manifest."""
import argparse
import html
import json
from pathlib import Path
import shutil
from markdown_it import MarkdownIt


def main():
    p=argparse.ArgumentParser();p.add_argument('--manifest',type=Path,required=True);a=p.parse_args()
    manifest=json.loads(a.manifest.read_text());origin=manifest['origins']['nordhem'].replace('127.0.0.1','localhost')
    out=Path('.local/review');assets=out/'dense-storefront-assets';assets.mkdir(parents=True,exist_ok=True)
    cases={
        'baseline':Path('.local/dense-storefront/matched-baseline-v1/department-large'),
        'dense':Path('.local/dense-storefront/acceptance-v3/express-generic/initial'),
        'expanded':Path('.local/dense-storefront/acceptance-v3/express-generic/expanded'),
        'shoe':Path('.local/dense-storefront/acceptance-v3/express-shoe/initial'),
    }
    for key,path in cases.items():
        for suffix in ('.outline.txt','.png','.overview.json','.nonverbose.json','.metrics.json'):
            shutil.copyfile(Path(str(path)+suffix),assets/(key+suffix))
    style='<style>body{font:16px/1.5 system-ui;max-width:1250px;padding:25px;margin:auto;color:#24303b}a{color:#075985}.links{display:flex;gap:20px;flex-wrap:wrap;padding:15px;background:#eef4f5}.pair{display:grid;grid-template-columns:1fr 1fr;gap:15px}iframe{width:100%;height:65vh;border:1px solid #aaa;background:#fafafa}img{max-width:100%}table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:8px}pre{overflow:auto;padding:15px;background:#f5f5f5}@media(max-width:800px){.pair{grid-template-columns:1fr}}</style>'
    report=MarkdownIt('commonmark',{'html':False}).enable('table').render(Path('docs/agents/procedural-commerce-dense-storefront.md').read_text())
    (out/'dense-storefront-report.html').write_text('<!doctype html><meta charset="utf-8"><title>Dense storefront implementation</title>'+style+report)
    content=f'''<!doctype html><meta charset="utf-8"><title>Dense storefront: live preview and AX</title>{style}
<h1>Dense storefront</h1><p>Working local store with 99 existing products, native controls and real catalog links. New store-generator integration is still pending. This preview shares one session; browser acceptance used isolated sessions. No model runs.</p>
<nav class="links"><a href="{origin}/">Store home</a><a href="{origin}/products/product-002">Household product</a><a href="{origin}/products/shoe-42-black">Size/colour product</a><a href="{origin}/search">Full catalog</a><a href="dense-storefront-report.html">Implementation and tests</a></nav>
<h2>Same world and same product, different layout</h2><p>Both captures use 99 products and product-002. The earlier department has 123 retained nodes; the dense page has 645 (774 with menu/specifications open). Both have maximum depth seven. These full outlines are audit reconstructions, not one model message.</p>
<div class="pair"><section><h3>Earlier department</h3><iframe title="Earlier department AX" src="dense-storefront-assets/baseline.outline.txt"></iframe></section><section><h3>Dense storefront</h3><iframe title="Dense storefront AX" src="dense-storefront-assets/dense.outline.txt"></iframe></section></div>
<p><a href="dense-storefront-assets/expanded.outline.txt">Expanded tree</a> · <a href="dense-storefront-assets/dense.overview.json">Actual initial AX overview (927 Qwen tokens)</a> · <a href="dense-storefront-assets/dense.nonverbose.json">Full non-verbose projection</a> · <a href="retail-ax-expanded.html">Real retailer references</a></p>
<details><summary>Saved viewport screenshots</summary><div class="pair"><img src="dense-storefront-assets/baseline.png" alt="Earlier department screenshot"><img src="dense-storefront-assets/dense.png" alt="Dense storefront screenshot"></div></details>
<p>Six accepted native-browser shopping cases cover both product types and all three checkout flows. Images remain symbolic, carts remain single-line, and finance/reviews/location mechanics were not added. <a href="dense-storefront-report.html">Full limitations and retained development failures</a>.</p>'''
    (out/'dense-storefront.html').write_text(content)
    print('http://localhost:8876/dense-storefront.html')


if __name__=='__main__':main()
