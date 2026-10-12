# Commerce scenarios: Website host kit

Mounts one generated retailer as a "scenario": server-held consent, newsletter,
extras and promotion codes, a checked report of basket, delivery option and
checkout location, and a host-produced chronological journal
(`website-commerce-session-journal-v1`, with its addenda 1-3). Nothing outside
this package is edited; a `ScenarioRuntime` without a scenario is the native
`Runtime`. The patterns here are deliberately plain. A family adds its own
designs on top through the three attachment points below.

| File | What it is |
|---|---|
| `settings.py` | `options()` validates the settings; `public_settings()` is what the page may see |
| `store.py` | `SessionStore`: state, operations, site rules, journal, completeness |
| `runtime.py` | `ScenarioRuntime`: `POST /api/session`, wrapped quote and order handlers, projected assets |
| `assets.py` | Seam patches of the composed `shop.js`/`quote.js` with an exact inverse |
| `scenario.js`, `scenario.css` | Page helper, served as `commerce-scenario.js`/`.css` on the target retailer only |
| `capture.py`, `episode.py`, `scripted.py` | `SessionCapture`, `ScenarioEpisode`, scripted-run helper |
| `witness.py` | Browser witness with a synthetic settings fixture |

## 1. Settings mapper

Write one function from Product's prepared `setup`/`presentation` to this dict
(every key except `retailer_id` is optional):

```python
{'retailer_id': 'footwear-04',
 'cookie': {'design': 'bottom-banner' | 'center-modal' | 'side-drawer',
            'first_level': ['accept_all', 'reject_all', 'settings'],   # which buttons the first view has
            'emphasis': 'accept_all' | None, 'blocking': False, 'dismissible': False,
            'preselected': {'analytics': False, 'personalisation': False, 'marketing': False}},
 'newsletter': {'label': str, 'preselected': False | 'start' | 'checkout'},
 'extras': [{'id', 'kind', 'label', 'price_minor', 'billing_period': 'one_time' | 'monthly',
             'preselected': False | 'start' | 'checkout'}],
 'promotions': {'field': bool, 'label': str, 'claims': [str]},
 'fees': [{'id', 'label', 'reveal': 'always' | 'checkout'}],          # display text only
 'delivery': {'default': {'choice_id': str} | {'option_id': str},
              'prominent': {'choice_id' | 'option_id': str, 'label': str}},
 'sponsored': [{'offer_id', 'label', 'placement': 'results' | 'product' | 'cart'}],  # passed to the page; not drawn by the kit
 'recurrence': {'cookie': [...], 'newsletter': [...], 'extras': {extra_id: [...]}, 'delivery': [...]},
               # triggers: 'checkout_return', 'checkout_navigation'
 'presentation': {...},      # free public parameters for the family's page piece
 'quote': callable, 'scope': callable,  # in process, both or neither
 'outside_scope_behavior': 'native_quote' | 'reject_quote'}
```

- `preselected: 'start'` puts the selection in the initial state (it is in the
  journal's `before`, no event). `'checkout'` makes the site select it when the
  shopper first enters checkout (`site_preselect`, trigger `initial`).
- `recurrence` re-selects on a later checkout entry (`checkout_return`) or on a
  step change inside a stepped checkout (`checkout_navigation`). For `delivery`
  it clears the shopper's choice so the default applies again; for `cookie` it
  shows the dialog again.
- `delivery.default` replaces the shop's own default whenever the shop would
  pick one. `choice_id` is the native delivery choice id of a single-shipment
  option (`option.shipments[0].delivery.id`); `option_id` is the native basket
  option id.
- Overlay price: `scope(lines, codes, *, delivery_option_id=None) -> {'in_scope': bool, 'reason': str}` and
  `quote(lines, codes, *, delivery_option_id=None) -> {'quote_id', 'total_minor', 'currency',
  'promotion_feedback': {code: {'accepted': bool, 'feedback': str}},
  'lines': [{'label', 'amount_minor'}], 'native_option_id',
  'promotion_codes', 'options': [{'native_option_id', 'shipping_minor', 'total_minor'}]}`
  (the last four optional). `lines` are `[{offer_id, quantity}]`. A selected
  route is passed unchanged and must match `native_option_id`; null is for
  pre-selection estimates/default suggestions. `total_minor` is used as
  returned, fees included; `lines` is a display breakdown only. Out of scope the
  native basket total is used by default and codes are refused with the scope's
  reason. Pricing scenarios select `outside_scope_behavior='reject_quote'`
  to leave the quote unavailable with its scope reason. Authoritative
  `promotion_codes`, when supplied, replace all active codes after each
  recalculation, including non-stacking rejection and quantity changes.
  All consumed overlay fields are validated before publication; a failed
  producer or lost event faults the capture. Actual saved grants/orders are
  retained even when capture is incomplete.
- Nothing private belongs in the settings: no binding, reference or expected value.

## 2. Page pieces

Pass `assets={'my-family.js': bytes, 'my-family.css': bytes}` to
`ScenarioEpisode` (or `scenario_assets=` to `ScenarioRuntime`). A `.js` piece
exports `attach(api)`:

- `api.renderers.cookieFirstLevel`, `cookieSettingsPane`, `checkoutControls`,
  `totals`, `promotionForm`: replace any of them; each returns HTML from
  `{view, settings, ...}`.
- `api.decorators`: functions `(root, {view, settings})` run after every render
  (delivery badges, sponsored placements).
- `api.send(op, fields)`, `api.view()`, `api.refresh()`, `api.settings`,
  `api.presentation`, `api.escape`, `api.money`.

Controls keep working when the markup keeps these attributes:
`data-consent="accept_all|reject_all|save_settings|settings|back|dismiss"`,
`data-consent-purpose`, `data-scenario-newsletter`, `data-scenario-extra="<id>"`,
`form[data-scenario-form="promotion"]` with an input named `code`,
`data-scenario-remove-code="<code>"`.

Session operations (`POST /api/session`, body `{op, session, ...}`):
`state`, `quote`, `cookie_dialog {event: load|dismiss}`,
`cookie_save {action, preferences?}`, `newsletter_set {value}`,
`extras_set {extra_id, value}`, `promotion_apply {code}`,
`promotion_remove {code}`, `order_arm {grand_total_minor}`,
`sync {basket, delivery: {option_id, source}, location, step}`. A refused
operation answers 400 and changes nothing; a refused `sync` also makes the
journal incomplete (`state_fault`).

## 3. Scripted control

```python
episode = ScenarioEpisode(world_dir, settings, assets=pieces, lazy_publication=True,
    task={'task_id', 'user_message', 'memories', 'start': 'retailer' | 'world'},
    bind_episode=bound_binding)   # episode_id -> the bound native prepared.binding (Product's registry.bind_episode)
result = scripted.run(episode, next_action, output, contract=adapter.contract(),
                      finalize=adapter.finalize, metadata={...})
```

`next_action(page)` returns one tool call per step (`scripted.click(node)`,
`scripted.fill(node, value)`, `scripted.say(text)`, or `('goto', {'url': ...})`).
The grading contract must be external-phase: the journal is sealed only after
the browser and the Runtime are closed, and `episode.capture.journal` is the
`(env, trace, outcome) -> journal` callback for the adapter. The sealed journal
is also written to `manual-review-private/commerce-session-journal.private.json`.

`witness.py` is the worked example. The runner prints a long result line; send
stdout to a file rather than a pipe.

For consent-family newsletter or paid-extra orders, and cookie
`preference_preservation` tasks with shopping continuation, the publication API accepts
`prepare_episode(world_dir, instance_path, offer_id='native-offer-id')`. It passes
that explicit target to the existing real-catalog order policy and records it in
`prepared.config['offer_id']`; missing, foreign-retailer or non-in-stock targets
fail preparation before browser dispatch. Other cookie objectives and other
families reject this option. Incomplete order controls validate the target but still start
at the world and finish without visiting the shop. Omit it to retain the default:
the first in-stock offer for order tasks, no shopping continuation for cookie
tasks. The caller authors the matching natural request through
Product's existing `user_message` API; no offer is inferred from prose and native
task prose, preferences, grading and unassessed order-content scope stay unchanged.
For cookie continuation, native grading assesses only preference preservation:
order submission is observed, while shopping completion and order contents remain
unassessed. The canonical task-completion and viewer structured-claims fields
therefore remain null; the viewer's scoped cookie outcome still records pass or
fail.

## Limits worth knowing

- Only the total block of basket and checkout comes from the session quote.
  Product-page prices, basket line prices and the per-option delivery rows are
  still the native ones; a pricing family that overlays those must patch them.
- The native order record is unchanged: items and shipping at the native quote.
  Extras and an overlay total exist only in the journal's `committed.order`.
- `cookie.pending` is what the site preselected for the open dialog. Toggles the
  shopper makes inside the dialog are not state until saved.
- `checkout_navigation` exists only for the stepped checkout layout.
