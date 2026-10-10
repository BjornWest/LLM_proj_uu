import {data} from './world-data.js';
import {normalizeProductContent} from './product-content.js';
export const products=data.products.map(normalizeProductContent);
export const categories=[...new Set(products.map(p=>p.category))];
export const brands=[...new Set(products.map(p=>p.brand))].sort();
export const typesFor=category=>[...new Set(products.filter(p=>!category||p.category===category).map(p=>p.type))].sort();
export function resolveProduct(id,selection={}){
  const product=products.find(p=>p.id===id);if(!product)return null;
  let candidates=product.variants;
  for(const option of product.options){const compatible=candidates.filter(v=>v.selection[option.key]===(selection[option.key]||candidates[0].selection[option.key]));if(compatible.length)candidates=compatible;}
  return {product,variant:candidates[0]};
}
export function byVariant(key){for(const product of products){const variant=product.variants.find(v=>v.key===key);if(variant)return {product,variant};}return null;}
