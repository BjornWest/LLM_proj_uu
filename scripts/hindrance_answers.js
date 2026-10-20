// Page piece for answer-corrupting hindrances (scripts/hindrance_answers.py).
// Only adds disclosure text on the apparent winner's shop; every price, delivery
// charge and total shown by the shop stays the native one.
export function attach(api) {
  const p = api.presentation, e = api.escape;
  // Prices in the shop's own money format.
  const stepped = api.money(p.stepped_minor || 0), basePrice = api.money(p.base_minor || 0);
  const base = String(p.execution || '').replace(/_(light|heavy)$/, '');

  function buyingForm(root) {
    const form = root.querySelector('form[data-form="add"][data-key]');
    if (!form) return null;
    const found = api.page.byVariant(form.dataset.key);
    if (!found || !found.product.variants.some(v => v.offerId === p.offer_id)) return null;
    return {form, product: found.product, variant: found.variant};
  }

  function note(root, attribute, html) {
    for (const old of root.querySelectorAll(`[${attribute}]`)) old.remove();
    const page = buyingForm(root);
    if (!page || !html(page)) return;
    const amount = page.form.closest('section')?.querySelector('.amount') || page.form;
    const node = document.createElement('p');
    node.setAttribute(attribute, '');
    node.innerHTML = html(page);
    amount.after(node);
  }

  api.decorators.push(root => {
    if (base === 'size_price_step') {
      note(root, 'data-hindrance-size-note', ({variant}) => String(variant.selection?.[p.field]) === p.size
        ? `<span role="status">Price for size ${e(p.size)}: ${e(stepped)}.</span> Size ${e(p.size)} is priced above this model's other sizes (from ${e(basePrice)}).`
        : `Prices vary by size: size ${e(p.size)} costs ${e(stepped)}.`);
    }
  });
}
