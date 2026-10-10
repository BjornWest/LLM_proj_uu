// Progressive comment disclosure. All corpus semantics/statistics are native.
const progress = new Map(), rendered = new Map();

function commentHTML(review, e) {
  return `<article data-review-id="${e(review.review_id)}" data-reviewed-sku="${e(review.sku_id)}"><h3>${e(review.reviewer)} · ${e(review.rating)} / 5</h3><p>Reviewed SKU: ${e(review.sku_id)}</p><p>${e(review.text)}</p></article>`;
}

export function renderReviews(product, {e}, settings) {
  const corpus = product.reviewCorpus;
  if (!corpus) return '';
  const s = corpus.rating_summary, written = corpus.reviews.filter(r=>r.text);
  const summary = `<h2>Customer reviews</h2><p>${e(s.average_rating)} / 5 from ${e(s.rating_count)} ratings. ${e(s.written_review_count)} written reviews; ${e(s.rating_only_count)} ratings without comments.</p><p>The average includes ratings without comments. Customer reviews are shared with participating publications; repeated publication does not add votes.</p>`;
  const listId = `customer-comments-${product.id}`;
  let body;
  if (!written.length) {
    body = '<p>No written comments are recorded.</p>';
  } else if (settings.mode === 'inline') {
    body = written.map(r=>commentHTML(r,e)).join('');
  } else {
    const shown = Math.min(written.length, Math.max(settings.initialCount, progress.get(product.id)||0));
    rendered.set(product.id, {written, shown, e, batchSize:settings.batchSize});
    body = `<div id="${e(listId)}" data-review-list>${written.slice(0,shown).map(r=>commentHTML(r,e)).join('')}</div><p data-review-progress aria-live="polite">Showing ${shown} of ${written.length} written comments.</p>`;
    if (shown < written.length) body += `<button type="button" data-review-load-more aria-controls="${e(listId)}">Load more customer comments</button>`;
  }
  return `<section aria-label="Customer reviews" data-customer-review-product="${e(product.id)}" data-review-mode="${e(settings.mode)}">${summary}${body}</section>`;
}

export function appendMore(button) {
  const section = button.closest('[data-customer-review-product]');
  if (!section || button.isConnected === false) return false;
  const record = rendered.get(section.dataset.customerReviewProduct);
  const list = section.querySelector('[data-review-list]');
  const counter = section.querySelector('[data-review-progress]');
  if (!record || !list || !counter || record.shown >= record.written.length) return false;
  const next = Math.min(record.written.length, record.shown + record.batchSize);
  list.insertAdjacentHTML('beforeend', record.written.slice(record.shown,next).map(r=>commentHTML(r,record.e)).join(''));
  record.shown = next;
  progress.set(section.dataset.customerReviewProduct, next);
  counter.textContent = `Showing ${next} of ${record.written.length} written comments.`;
  if (next === record.written.length) button.remove();
  return true;
}

if (typeof document !== 'undefined') document.addEventListener('click', event=>{
  const button = event.target.closest?.('[data-review-load-more]');
  if (button) appendMore(button);
});
