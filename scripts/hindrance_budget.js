// Page piece for the late_fee_over_budget trap (scripts/hindrance_budget.py).
// The shop's mandatory handling fee is a host-owned scenario extra, selected by the
// site at checkout entry and part of every armed order total. It has no control (it
// cannot be removed) and is shown only in the final review: elsewhere the totals
// leave it out. Light announces it in the review; heavy shows only the fee line.
export function attach(api) {
  const p = api.presentation, e = api.escape, money = api.money;
  const native = {totals: api.renderers.totals};

  function atReview() {
    const route = api.page.route();
    if (route.role !== 'checkout') return false;
    if (api.page.conf.modules.checkout !== 'steps') return true;
    return (Math.floor(Number(route.params.get('step'))) || 1) >= 3;
  }

  api.renderers.checkoutControls = ({view}) => p.announce && view.extras[p.fee_id] && atReview()
    ? `<p role="status" data-hindrance-fee-note>A handling fee of ${e(money(p.fee_minor))} applies to every order and has been added to your total.</p>`
    : '';

  api.renderers.totals = ({view, settings}) => {
    if (!view.quote || !view.extras[p.fee_id] || atReview()) return native.totals({view, settings});
    const charges = view.charges.filter(charge => !(charge.kind === 'extra' && charge.id === p.fee_id));
    return native.totals({view: {...view, charges, grand_total_minor: view.grand_total_minor - p.fee_minor}, settings});
  };
}
