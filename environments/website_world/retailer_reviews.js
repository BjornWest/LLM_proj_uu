// Additive surrounding-sites renderer: same corpus, no external review-site link.
export function customerReviews(product, {e}) {
  const corpus=product.reviewCorpus;
  if(!corpus)return '';
  const s=corpus.rating_summary;
  const written=corpus.reviews.filter(r=>r.text);
  const comments=written.map(r=>`<article><h3>${e(r.reviewer)} · ${e(r.rating)} / 5</h3><p>Reviewed SKU: ${e(r.sku_id)}</p><p>${e(r.text)}</p></article>`).join('');
  return `<section aria-label="Customer reviews"><h2>Customer reviews</h2><p>${e(s.average_rating)} / 5 from ${e(s.rating_count)} ratings. ${e(s.written_review_count)} written reviews; ${e(s.rating_only_count)} ratings without comments.</p><p>The average includes ratings without comments. Customer reviews are shared with participating publications; repeated publication does not add votes.</p><details><summary>Read customer comments (${written.length})</summary>${comments||'<p>No written comments are recorded.</p>'}</details></section>`;
}
