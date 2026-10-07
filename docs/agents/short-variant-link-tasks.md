# Short exact-variant link tasks

Product owns `environments/website_world/variant_link_task.py` and
`variant_link_grading.py`. Website owns publication, recipient-navigation
capability evidence and eventual episode extraction. Evaluation owns finite
model runs. Current status is a tested native structured-claim oracle;
browser adoption and automatic model-answer grading remain pending.

Declare one carried offer before task publication:

```json
{"kind": "link_exact_variant", "retailer_id": "outdoors-03", "offer_id": "<native offer ID>"}
```

Call `variant_link_task.make(world, spec, catalog=actual_retailer_catalog,
bindings=actual_runtime_bindings, navigation_capability=accepted_capability)`.
Use `reference` with the same inputs. The task starts at that merchant's
product page and asks for a link plus any recipient-side selection needed.
It does not rank prices or ask for a purchase.

The private capability must declare `protocol=explicit-url-fields-first-v1`,
`owner=Product`, `status=accepted`, the exact retailer/page/catalog digest,
served asset digests and `recipient_states=fresh_and_all_carried_tuples`.
It is trusted consumer acceptance evidence, not a user-supplied claim.
The pure native API checks its binding and status; it does not independently
certify a renderer or authenticate a Product acceptance document. The
publication caller must pin and verify the actual Product acceptance receipt.
Source-only renderer preparation is insufficient to release a runnable task.

`required_selection` on legacy Runtime bindings describes fields omitted from
the URL. It cannot by itself establish the recipient's resolved selection.
The accepted navigation protocol must preserve jointly satisfiable explicit
URL fields before choosing omitted fields from recipient state/defaults.
Ordinary option changes retain their existing fallback behavior.

The native grader accepts these explicit synthetic claims:

```json
{
  "url": "https://shop.example/#/product/page-id?colour=brown",
  "selection": {"size_eu": "38", "colour": "brown"},
  "link_encodes_full_selection": false,
  "recipient_must_select": true,
  "manual_selection": {"size_eu": "38"}
}
```

Call `variant_link_grading.grade(world, task, reference, claims, **inputs)`.
Full links require both booleans to reflect that no manual selection remains.
Colour-only links require the omitted axes; product-only links require all
axes. The actual URL mode, complete carried target, merchant route and
query values must match. Parameter order is immaterial; duplicates, foreign
pages, extra unsupported selectors and fallback tuples fail.
Product selectors must occur inside the hash route, as read by the actual
`shop.js` router. Outer URL query fields are rejected; they cannot establish
that the recipient will open the requested variant.

Natural-language extraction/grounding and once-only episode grading are not
implemented by this pure function. Native link correctness also does not
establish stock, reading/exposure, navigation scope or absence of effects.
Keep those component results and unknowns separate in the consumer packet.

Focused local verification is small and does not construct Runtime:

```sh
python3 -m unittest environments.website_world.test_variant_link_task
```

Current renderer release and source-review evidence are under
`.local/coordination/short-task-hindrance-tests-20261007/variant-link-Product-contract-v1.md`.
