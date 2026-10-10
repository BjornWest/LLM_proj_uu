// Saved-menu diagnosis. Execute the production resolver; do not alter its tuples.
import {readFile, writeFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';

const sha = bytes => createHash('sha256').update(bytes).digest('hex');
const moduleURL = source => `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;

export async function productionResolver(data) {
  const catalog = await readFile(new URL('./catalog.js', import.meta.url), 'utf8');
  const content = await readFile(new URL('../website_drafts/product-content.js', import.meta.url), 'utf8');
  const anchors = ["import {data} from './world-data.js';", "import {normalizeProductContent} from './product-content.js';"];
  for (const anchor of anchors) {
    if (catalog.split(anchor).length !== 2) throw new Error('Production import anchor changed');
  }
  const source = catalog.replace(anchors[0], `const data=${JSON.stringify(data)};`)
    .replace(anchors[1], `import {normalizeProductContent} from '${moduleURL(content)}';`);
  return {module: await import(moduleURL(source)), sources: {
    'environments/website_world/catalog.js': sha(catalog),
    'environments/website_drafts/product-content.js': sha(content),
  }};
}

export async function probe(data, {colourKey='colour', colourValue='black', sizeKey='size_eu'}={}) {
  const {module, sources} = await productionResolver(data);
  const transitions = [], rejectedColour = [], stockOnly = [];
  let inspected = 0;
  for (const product of module.products) {
    const axes = product.options.map(o => o.key);
    if (!axes.includes(colourKey) || !axes.includes(sizeKey)) continue;
    for (const before of product.variants) {
      if (before.selection[colourKey] === colourValue) continue;
      inspected++;
      if (module.resolveProduct(product.id, before.selection).variant.key !== before.key) {
        throw new Error('Ambiguous or unreachable merchant tuple');
      }
      const requested = {...before.selection, [colourKey]:colourValue};
      const after = module.resolveProduct(product.id, requested).variant;
      const sameSize = product.variants.filter(v => v.selection[colourKey] === colourValue
        && v.selection[sizeKey] === before.selection[sizeKey]);
      const record = {page_id:product.id, canonical_product_id:product.canonicalProductId,
        axis_order:axes, before:{sku_id:before.skuId, offer_id:before.offerId,
          key:before.key, selection:before.selection, state:before.state},
        requested, after:{sku_id:after.skuId, offer_id:after.offerId,
          key:after.key, selection:after.selection, state:after.state}};
      if (sameSize.length) {
        if (sameSize.every(v=>v.state==='unavailable')) stockOnly.push(record);
        continue; // Zero stock is still a listed tuple, never absence.
      }
      if (after.selection[colourKey] !== colourValue) {rejectedColour.push(record);continue;}
      if (after.selection[sizeKey] !== before.selection[sizeKey]) transitions.push(record);
    }
  }
  return {schema:'website-variant-transition-probe-v1', input_sha256:sha(JSON.stringify(data)),
    sources, selection_request:{colourKey,colourValue,sizeKey}, inspected,
    transitions, rejected_colour_requests:rejectedColour, stock_only_cases:stockOnly,
    evidence_scope:'Actual production resolver over supplied merchant tuples; no browser, AX capture, world draw or model delivery.'};
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  if (process.argv.length !== 4) throw new Error('Usage: node variant_transition_probe.mjs PUBLIC_CATALOG.json OUTPUT.json');
  const input = JSON.parse(await readFile(process.argv[2], 'utf8'));
  await writeFile(process.argv[3], JSON.stringify(await probe(input), null, 2)+'\n', {flag:'wx'});
}
