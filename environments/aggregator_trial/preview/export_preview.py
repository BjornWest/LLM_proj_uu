#!/usr/bin/env python3
"""Export the aggregator trial UI as a clearly labeled static design preview.

The generated tree contains the public aggregator and retailer UI plus a small
browser-local API shim. It is intended for visual review and manual demos.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
from datetime import datetime, timezone


ROOT = Path(__file__).resolve().parents[1]
RETAILERS = ("nordbyte", "hemteknik", "signalboden")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def clean_base(value: str) -> str:
    value = "/" + value.strip().strip("/") if value.strip("/") else ""
    return value.rstrip("/")


def public_config(catalog: dict, base: str) -> dict:
    retailers = {row["id"]: row for row in catalog["retailers"]}
    products = {row["id"]: row for row in catalog["products"]}
    offers = []
    for raw in catalog["offers"]:
        product = products[raw["product_id"]]
        offer = {"offer_id": f'{raw["retailer"]}:{raw["product_id"]}', **product, "product_id": product["id"],
                 "unit_price_ore": raw["unit_price_ore"], "shipping_ore": raw["shipping_ore"],
                 "stock": raw["stock"], "delivery": raw["delivery"],
                 "warranties": raw.get("warranties", []), "image": f"{base}/assets/product.svg",
                 "retailer": raw["retailer"], "retailer_name": retailers[raw["retailer"]]["name"],
                 "retailer_rating": retailers[raw["retailer"]]["rating"],
                 "quote_ore": raw["quote_ore"], "quote_note": raw.get("quote_note"),
                 "retailer_url": f'{base}/retailers/{raw["retailer"]}/?product_id={product["id"]}'}
        offers.append(offer)
    return {"products": list(products.values()), "offers": offers,
            "retailers": catalog["retailers"], "participating_retailers": list(RETAILERS),
            "homepage": catalog["homepage"],
            "unavailable_directory_examples": ["Budgethörnan", "KlickTeknik"]}


def shim(config: dict, catalog: dict, base: str) -> str:
    payload = json.dumps(config, ensure_ascii=False, separators=(",", ":"))
    products = {p["id"]: p for p in catalog["products"]}
    offers = config["offers"]
    offer_json = json.dumps(offers, ensure_ascii=False, separators=(",", ":"))
    retailer_json = json.dumps({r: next(x for x in catalog["retailers"] if x["id"] == r) for r in RETAILERS}, ensure_ascii=False, separators=(",", ":"))
    return f'''/* Generated preview shim: all state is local to this browser. */
(function () {{
  const BASE = {json.dumps(base)};
  const CONFIG = {payload};
  const OFFERS = {offer_json};
  const RETAILERS = {retailer_json};
  const key = () => {{ const m = location.pathname.match(new RegExp(BASE + '/retailers/([^/]+)')); return m ? m[1] : 'aggregator'; }};
  const storageKey = () => 'prislyktan-preview-cart-' + key();
  const read = () => JSON.parse(localStorage.getItem(storageKey()) || '{{"items":[],"extras":[]}}');
  const save = cart => {{ localStorage.setItem(storageKey(), JSON.stringify(cart)); return cart; }};
  const offer = id => OFFERS.find(x => x.offer_id === id);
  const view = cart => {{ const items = cart.items.map(x => {{ const o=offer(x.offer_id); return {{line_id:x.line_id,offer_id:x.offer_id,product_id:o.product_id,name:o.name,model:o.model,variant:o.variant,capacity:o.capacity,quantity:x.quantity,unit_price_ore:o.unit_price_ore}}; }}); const shipping=Math.max(0,...items.map(x=>offer(x.offer_id).shipping_ore)); const subtotal=items.reduce((n,x)=>n+x.unit_price_ore*x.quantity,0); const extras=cart.extras||[]; const extraTotal=extras.reduce((n,x)=>n+x.price_ore,0); return {{items,extras,shipping_ore:shipping,subtotal_ore:subtotal,extras_ore:extraTotal,delivered_ore:subtotal+shipping+extraTotal}}; }};
  const response = (body, status=200) => Promise.resolve(new Response(JSON.stringify(body), {{status,headers:{{'Content-Type':'application/json'}}}}));
  const originalFetch = window.fetch;
  window.fetch = (input, options={{}}) => {{
    const url = new URL(typeof input === 'string' ? input : input.url, location.href); const path=url.pathname;
    if (!path.includes('/api/')) return originalFetch(input, options);
    const method=(options.method||'GET').toUpperCase(); const body=options.body ? JSON.parse(options.body) : {{}}; const retailer=key();
    if (retailer==='aggregator' && path.endsWith('/api/config')) return response(CONFIG);
    if (retailer!=='aggregator' && path.endsWith('/api/store')) return response({{...RETAILERS[retailer],currency:'SEK',checkout_notice:'Design preview — local simulated state'}});
    if (retailer!=='aggregator' && path.endsWith('/api/catalog')) {{ const q=(url.searchParams.get('q')||'').toLowerCase(); const cat=url.searchParams.get('category')||''; return response({{categories:[...new Set(OFFERS.filter(x=>x.retailer===retailer).map(x=>x.category))],offers:OFFERS.filter(x=>x.retailer===retailer&&(!cat||x.category===cat)&&(!q||[x.name,x.brand,x.model,x.variant,x.capacity,x.category,x.description].join(' ').toLowerCase().includes(q)))}}); }}
    if (retailer!=='aggregator' && path.includes('/api/offers/')) {{ const x=offer(decodeURIComponent(path.split('/api/offers/')[1])); return x ? response(x) : response({{error:'unknown_offer',message:'Erbjudandet finns inte'}},404); }}
    if (retailer!=='aggregator' && path.endsWith('/api/cart') && method==='GET') return response(view(read()));
    if (retailer!=='aggregator' && path.endsWith('/api/cart/items') && method==='POST') {{ const c=read(); const x=c.items.find(i=>i.offer_id===body.offer_id); if(x)x.quantity+=body.quantity; else c.items.push({{line_id:Math.random().toString(36).slice(2),offer_id:body.offer_id,quantity:body.quantity}}); return response(view(save(c))); }}
    if (retailer!=='aggregator' && path.includes('/api/cart/items/') && (method==='DELETE'||method==='PATCH')) {{ const id=decodeURIComponent(path.split('/api/cart/items/')[1]); const c=read(); const item=c.items.find(x=>x.line_id===id); if(item){{ if(method==='DELETE'||body.quantity===0)c.items=c.items.filter(x=>x!==item); else item.quantity=body.quantity; }} return response(view(save(c))); }}
    if (retailer!=='aggregator' && path.endsWith('/api/cart/warranty')) {{ const c=read(); c.extras=(c.extras||[]).filter(x=>x.offer_id!==body.offer_id); const o=offer(body.offer_id); const w=o?.warranties?.find(x=>x.id===body.warranty_id); if(w)c.extras.push({{...w,kind:'warranty',offer_id:body.offer_id}}); return response(view(save(c))); }}
    if (retailer!=='aggregator' && path.endsWith('/api/checkout')) {{ const c=view(read()); if(!c.items.length)return response({{error:'empty_cart',message:'Varukorgen är tom'}},409); const receipt={{order_id:'PREVIEW-'+Math.random().toString(36).slice(2,8).toUpperCase(),...c,customer:body.customer,notice:'Design preview — local simulated state'}}; localStorage.setItem('prislyktan-preview-last-order-'+retailer,JSON.stringify(receipt)); save({{items:[],extras:[]}}); return response(receipt,201); }}
    if (retailer!=='aggregator' && path.endsWith('/api/orders')) {{ const last=localStorage.getItem('prislyktan-preview-last-order-'+retailer); return response({{orders:last?[JSON.parse(last)]:[]}}); }}
    return response({{error:'preview_route',message:'Preview API route unavailable'}},404);
  }};
}})();
'''


BANNER = '<div class="preview-banner" role="note">Design preview — local simulated state; use task/manual modes for real runs</div>'
BANNER_CSS = '.preview-banner{position:sticky;top:0;z-index:99;background:#fff4bf;color:#4a3900;border-bottom:1px solid #d6b73c;padding:8px 18px;text-align:center;font:600 13px/1.3 system-ui,sans-serif}'


def patch_html(text: str, base: str, script: str, css: str) -> str:
    text = text.replace('href="/styles.css"', 'href="styles.css"').replace('src="/app.js"', 'src="app.js"')
    text = text.replace('<body>', f'<body>{BANNER}<script src="{script}"></script>')
    text = text.replace('</head>', f'<style>{css}</style></head>')
    return text


def patch_js(text: str, base: str, retailer: str | None = None) -> str:
    text = text.replace("'/products/", f"'{base}/products/").replace('"/products/', f'"{base}/products/')
    text = text.replace('`/products/', f'`{base}/products/')
    text = text.replace('"/assets/', f'"{base}/assets/').replace("'/assets/", f"'{base}/assets/")
    if retailer is None:
        root = base or ''
        text = text.replace("location.pathname.match(/^\\/products\\/([^/]+)$/)", f"location.pathname.match(new RegExp('^{root}/products/([^/]+)/?$'))")
        text = text.replace("`/?category=", f"`{root}/?category=").replace("`/?q=", f"`{root}/?q=")
        text = text.replace(" : '/');", f" : '{root}/');")
        text = text.replace('href="/">', f'href="{root}/">')
    if retailer == 'nordbyte':
        text = text.replace("'/?product_id=", f"'{base}/retailers/nordbyte/?product_id=")
        text = text.replace("history.replaceState(null,'','/')", f"history.replaceState(null,'','{base}/retailers/nordbyte/')")
    return text


def export(output: Path, base: str) -> dict:
    catalog = json.loads((ROOT / 'catalog.json').read_text())
    config = public_config(catalog, base)
    if output.exists() or output.is_symlink():
        raise FileExistsError(f'Output already exists; refusing to replace it: {output}')
    output.mkdir(parents=True)
    (output / 'assets').mkdir()
    shutil.copy2(ROOT / 'assets/product.svg', output / 'assets/product.svg')
    (output / 'preview-shim.js').write_text(shim(config, catalog, base))
    (output / 'index.html').write_text(patch_html((ROOT/'aggregator/index.html').read_text(), base, f'{base}/preview-shim.js', BANNER_CSS))
    (output / 'styles.css').write_text((ROOT/'aggregator/styles.css').read_text() + '\n' + BANNER_CSS)
    (output / 'app.js').write_text(patch_js((ROOT/'aggregator/app.js').read_text(), base))
    (output / 'products').mkdir()
    for product in catalog['products']:
        folder = output / 'products' / product['id']; folder.mkdir()
        product_html = (output/'index.html').read_text().replace('href="styles.css"', f'href="{base}/styles.css"').replace('src="app.js"', f'src="{base}/app.js"')
        (folder/'index.html').write_text(product_html)
    for retailer in RETAILERS:
        folder = output / 'retailers' / retailer; folder.mkdir(parents=True)
        source = ROOT / 'retailers' / retailer
        (folder/'index.html').write_text(patch_html((source/'index.html').read_text(), base, f'{base}/preview-shim.js', BANNER_CSS))
        (folder/'styles.css').write_text((source/'styles.css').read_text() + '\n' + BANNER_CSS)
        (folder/'app.js').write_text(patch_js((source/'app.js').read_text(), base, retailer))
    source_paths = [ROOT / 'catalog.json', ROOT / 'assets/product.svg', ROOT / 'aggregator/index.html', ROOT / 'aggregator/styles.css', ROOT / 'aggregator/app.js']
    source_paths += [ROOT / 'retailers' / retailer / name for retailer in RETAILERS for name in ('index.html', 'styles.css', 'app.js')]
    manifest = {'schema':'prislyktan-design-preview-v1','generated_at':datetime.now(timezone.utc).isoformat(),'base_path':base or '/', 'exporter_sha256':sha256(Path(__file__)), 'source_files':{str(path.relative_to(ROOT)):sha256(path) for path in source_paths}, 'output_files':{str(p.relative_to(output)):sha256(p) for p in sorted(output.rglob('*')) if p.is_file()}}
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    return manifest


def main() -> None:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--base-path', default='')
    args=parser.parse_args()
    manifest=export(args.output, clean_base(args.base_path))
    print(json.dumps({'output':str(args.output),'files':len(manifest['output_files']),'base_path':manifest['base_path']}))


if __name__ == '__main__': main()
