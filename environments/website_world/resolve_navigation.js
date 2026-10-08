// Isolated correction candidate. Not adopted by Runtime or any existing host.
// URL fields are navigation intent; ordinary control-change resolution is intact.
export function resolveNavigation(product, params, previous, mode, resolveProduct) {
  const explicit = {};
  for (const option of product.options) {
    if ((mode === 'all' || mode === 'colour' && option.key === 'colour') &&
        params.has(option.key) && option.values.includes(params.get(option.key))) {
      explicit[option.key] = params.get(option.key);
    }
  }
  const requested = {...previous, ...explicit};
  const legacy = resolveProduct(product.id, requested);
  if (!Object.keys(explicit).length || Object.entries(explicit).every(([key,value])=>legacy.variant.selection[key]===value)) {
    return legacy;
  }
  let candidates = product.variants.filter(variant=>Object.entries(explicit).every(([key,value])=>variant.selection[key]===value));
  // Invalid/inconsistent URL combinations retain legacy behavior; no tuple added.
  if (!candidates.length) return legacy;
  for (const option of product.options) {
    const compatible = candidates.filter(variant=>variant.selection[option.key] ===
      (requested[option.key] || candidates[0].selection[option.key]));
    if (compatible.length) candidates = compatible;
  }
  // Resolve a complete existing tuple through the production resolver again.
  return resolveProduct(product.id, candidates[0].selection);
}
