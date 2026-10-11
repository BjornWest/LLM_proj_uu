// Family presentation only. Checkbox changes and native order submission remain
// with the shared host; prices and selections always come from its settings/view.
export function attach(api) {
  api.renderers.checkoutControls = ({view, settings}) => {
    const e = api.escape;
    const newsletter = settings.newsletter ? `<fieldset><legend>Stay in touch</legend><label><input type="checkbox" data-scenario-newsletter ${view.newsletter ? 'checked' : ''}> ${e(settings.newsletter.label)}</label><p>Receive product news and shop offers by email.</p></fieldset>` : '';
    const extras = settings.extras.map(extra => `<label><input type="checkbox" data-scenario-extra="${e(extra.id)}" ${view.extras[extra.id] ? 'checked' : ''}> ${e(extra.label)} — ${api.money(extra.price_minor)} ${extra.billing_period === 'monthly' ? 'per month' : 'one-time charge'}</label>`).join('');
    return newsletter + (extras ? `<fieldset><legend>Additional order options</legend>${extras}</fieldset>` : '');
  };
}
