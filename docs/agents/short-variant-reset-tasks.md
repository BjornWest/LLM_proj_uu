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

Nine finite controls cover reported absence, fallback purchase attempts, wrong
requested options, incomplete menus, present-but-zero-stock tuples, missing or
misordered action evidence, incorrect tuple chains/setup, baseline rejection and
missing effect authority. They launch no Runtime/browser/provider/world draw.
