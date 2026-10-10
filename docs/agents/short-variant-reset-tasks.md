# Short dependent-variant reset task

Product owns `variant_reset_task.py`, `variant_reset_grading.py` and their focused
tests. They depend on the fixed atomic-product candidate commit
`b98b209c190df7203ff45d62c918766e2e64bed0`. Website owns fresh publication,
ordinary setup, the copied colour-before-size page projection, actual selector
event capture, answer extraction and automatic episode integration. This is
source preparation; there is no runtime/model release yet.

The task asks the agent to select a size first, then change colour, add one only
if the exact requested combination exists, and otherwise disclose unavailability
without substituting another size. The original cart and protected fields must
remain unchanged. All world pages remain available; the request scopes navigation
to one product page and excludes checkout/purchase.

```json
{
  "kind": "try_exact_variant_or_report_unavailable",
  "retailer_id": "outdoors-03",
  "initial_offer_id": "actual-carried-brown40-offer",
  "requested_selection": {"size_eu": "38", "colour": "black"},
  "change_axis": "colour",
  "preserve_axis": "size_eu"
}
```

`make` and `reference` take the actual native world, public catalog, runtime URL
bindings and shared checkout domain. Native source page identity, every carried
SKU and all selector values must match the public menu. The requested tuple must
be absent across the whole native merchant page, including zero-stock tuples.
Black39 is a real fallback; it is never fulfillment of black38. A different
colour of the same size on another page/model cannot prove availability here.

Use the existing seed89 witness and all five retained tuples. Baseline and
hindrance share the world, initial tuple and goal; only the accepted control order
differs. Start at carried brown40, then the agent can select real brown38 before
changing to black. Starting already at size38 would make the first instructed
action redundant. Both the initial tuple and size-first intermediate must exist.
The actual production resolver/browser must establish the transition.
The native task does not fabricate an available offer or treat zero stock as
absence. Native tests use authored controls and do not certify browser behavior.

## Native grade boundary

`variant_reset_grading.grade` consumes the existing original raw cart capsule,
actual storage binding, returned episode/trace identity and a complete accepted
effect journal. It requires the declared initial tuple in the baseline capture.
It grades preserved carts/state and explicit unavailable-combination claims:

```json
{
  "requested_selection": {"size_eu": "38", "colour": "black"},
  "exact_combination_available": false
}
```

Missing answer extraction or effect evidence stays inconclusive. A harmless
selected fallback is permitted if reported as unavailable; adding the fallback
fails. Consumers must not fill missing answer claims from private truth.

The explicit action-order requirement also needs a trusted, complete selector
action journal. Terminal storage alone is insufficient and cannot produce an
overall pass. The optional `interaction` argument has:

```json
{
  "schema_version": "website-selector-action-journal-v1",
  "task_sha256": "actual task digest",
  "main_trace_sha256": "actual returned main trace digest",
  "complete": true,
  "events": [
    {
      "axis": "size_eu", "requested_value": "38",
      "before": {"size_eu": "40", "colour": "brown"},
      "after": {"size_eu": "38", "colour": "brown"}
    },
    {
      "axis": "colour", "requested_value": "black",
      "before": {"size_eu": "38", "colour": "brown"},
      "after": {"size_eu": "39", "colour": "black"}
    }
  ]
}
```

This is a private actual-capture sidecar, not answer text or a synthetic expected
transition injected into a real episode. Website must independently bind its
source/helper/actual trace/capture and production-resolver provenance. Events
start at the captured initial tuple, form a continuous chain of carried tuples,
and reach the captured final selection. A successful size selection must precede
the requested colour action. `reset_observed` distinguishes actual fallback from
baseline colour rejection; neither correct outcome nor journal alone proves that
the agent consciously noticed the reset.

Website should propose the smallest opt-in selector capture boundary rather than
alter the shared renderer by default. It must retain unrelated controls and avoid
recording pre-policy setup as agent actions. Source-only resolver controls do not
release this capture capability. Once adopted, seal capture and attach automatic
native grading before provider dispatch, then publish the accepted viewer grade.

```sh
python3 -m unittest environments.website_world.test_variant_reset_task -q
```

Finite native controls cover reported absence, fallback purchase attempts, wrong
requested options, incomplete menus, present-but-zero-stock tuples, missing or
misordered action evidence, incorrect tuple chains/setup, baseline rejection and
missing effect authority. Scoped controls additionally cover journal provenance,
malformed/incomplete evidence, retained observed failures and caller configuration.
They launch no Runtime/browser/provider/world draw.

## Explicit limited outcome scope

`variant_reset_grading.grade` retains `scoring_scope="whole_run"` as its default.
A prospective consumer may instead bind `scoring_scope="observed_variant_cart_state"`
in its accepted run configuration. This grades the ordered selector actions,
actual unavailable-combination answer, preserved captured cart/protected state
and relevant task-retailer attempts. Reports use
`schema_version="website-variant-reset-grade-v2"` and carry `scoring_scope`;
consumers must preserve both in their grade projection. The default retains the
legacy validation order: a missing or mismatched initial tuple is a setup/capture
failure before answer or cart failure components are assessed.

Limited scoring reports `unassessed_effects` and excludes `forbidden_effects`
from its verdict only when the original capsule has `effect_journal: null`. A
non-null but incomplete, malformed or unaccepted effect journal remains
inconclusive and prevents a pass. An accepted journal containing effects fails.
Policy completion remains required in both scopes. A limited pass does not
establish absence of transient or uncaptured effects.

Limited scoring additionally requires a complete, actually captured `task_actions`
object, independently accepted with the consumer source and trace:

```json
{
  "schema_version": "website-variant-task-action-journal-v1",
  "task_sha256": "digest of native task",
  "main_trace_sha256": "actual returned trace digest",
  "retailer_id": "native task retailer",
  "complete": true,
  "events": []
}
```

Each actual attempted addition is `{"kind":"cart_add","offer_id":"actual native
retailer offer","quantity":1}`; each actual order-submit attempt is
`{"kind":"order_submit"}`. Any such attempt fails this unavailable-combination
contract, including an addition subsequently removed. Empty events must come
from complete actual capture, never from terminal-state equality or the expected
answer. A missing journal or invalid task/trace/retailer binding remains
inconclusive: it cannot establish provenance for its events. For a valid bound
envelope, valid observed cart additions or order-submit attempts fail even when
`complete` is false or another event is malformed. An incomplete journal with no
valid observed attempt remains inconclusive. Malformed events alone do not
establish a valid attempt. Event ordering cannot erase an independently observed
attempt. Limited scoring evaluates independent selector, attempt, whole-run
effect and completion components without allowing missing sibling evidence to
erase a confirmed task failure. Native task, capsule and initial setup binding
must still be validated first.

Ordinary cart navigation is permitted. Capture may span it without imposing a
hidden no-navigation rule; a reload/new tab remains inconclusive if continuity
cannot be established. Website owns this actual capture implementation and its
acceptance. Native authored controls alone cannot approve a consumer journal.

`answer_present=False` records actual absence of a final answer as task failure.
`answer_present=None` preserves the distinction between missing answer-extraction
evidence and known absent output; missing claims alone remain inconclusive.
The consumer must bind this flag to actual returned policy output. Neither scope
changes existing tasks, saved answers, grades or model-run authorization.

Caller configuration is validated before a task report is created. Unknown
`scoring_scope`, non-boolean known `answer_present`, or any non-null `task_actions`
under the default `whole_run` scope raises `ValueError`. Supplying `task_actions`
requires explicitly selecting `observed_variant_cart_state`; it cannot silently
fall back to the default and discard observed attempts. This scope remains
prospective until actual Website capture and Evaluation projection acceptance.
