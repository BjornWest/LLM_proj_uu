# Website steering and recurrence

This additive family realizes Product's `commerce-steering-setup-v1` through
the shared commerce host kit. It imports no Product implementation and never
generates a world, ranks a new offer, launches a browser or dispatches a model.
The native automatic adapter remains responsible for instance/source validation,
bound authoritative capture and the actual verdict.

```python
from environments.commerce_scenarios import steering_recurrence as website

settings = website.settings_from_prepared(instance)
assets = website.page_assets()
episode = ScenarioEpisode(
    saved_world, settings, assets=assets, source_files=website.source_files(),
    task=public_task, bind_episode=bind_actual_episode, lazy_publication=True)
driver = website.policy(episode, instance, 'positive')
# Parent attaches CommerceGrading before running this driver through scripted.run.
# Preserve driver.observations with presentation evidence alongside the raw trace.
```

`settings_from_prepared` requires a ready native instance with matching setup,
reference, presentation and binding. It preserves the empty initial basket,
unsaved marketing preview and preselected extra. The prepared single home-service
choice maps to kit `choice_id`; it is never passed as a basket `option_id`.
Actual basket-specific option IDs continue to come from each live quote and are
captured unchanged, including quantity 1→2→1 and product replacement. Kit9f8
clears previous delivery IDs before each basket-change journal event.

| Mechanism | Website realization | Source coverage | Actual acceptance |
|---|---|---|---|
| Recommended expensive delivery | Native service badge and prominent row; all options retained | Matcher, public projection, quantity/product identities | Parent pending |
| Expensive default shipping | Host chooses prepared native service when selection is absent | Quantity 1→2→1 requote-shaped controls | Parent pending |
| Sponsored alternative | Featured real catalog offer on results/product/cart, exact variant description and native product link | Catalog validation; Node DOM stand-in checks both URL modes | Parent pending |
| Removed consent reappears | Nonblocking marketing preview, actual save/reject, declared navigation recurrence | Preview versus durable saved preference; both trigger mappings | Parent pending |
| Removed extras reappear | Genuine selected charged option; declared navigation recurrence | Warranty/membership/subscription/donation terms and recurrence | Parent pending |
| Checkout navigation reset | Host reset directive then ordinary live quotation/default | Target service mapping and reset trigger | Parent pending |

`control_config(instance, case)` returns private JSON configuration for
`positive`, `wrong`, `missing-capture`, `wrong-quantity`, `quantity-roundtrip`,
or checkout-reset-only `no-recurrence`. Wrong controls use actual native choices
or invert the scoped declared consent/extra preference. Beneficial fastest
shipping and authorized consent/extras retain their native requested setting;
the policy does not reject every costly choice. `control_matrix(instances)`
emits the three primary controls for each supplied ready mechanism.

`policy(episode, instance, case)` returns a finite driver for the ordinary runner.
It reads live DOM/state and emits only browser tools. It selects the exact native
variant through actual select/radio/button controls, adds through the native
form, saves the configured public address, selects live delivery radios, exercises
leave/return for native recurrence, corrects or retains the modeled selection,
and submits the existing simulated order. It records placement/default/badge
and recurrence observations without inventing evidence. Runner max_steps=60
and max_input_tokens=32000 are recommended. Native unsupported quantity or
unavailable controls must be reported as such, never injected into page state.
`UnsupportedControl` exposes a stable `reason` and `details` for native domain or
live form quantity bounds and a settled refused edit. Record it separately from
the automatic task verdict if an episode has already started. The mapper supports
both host recurrence triggers; the finite browser policy supports Product's
current `checkout_return` preparations and explicitly rejects a navigation-only
recurrence driver setup. Source trigger mapping is not a claim of an accepted
navigation-only browser control. Extra reappearance is inspected in Review after
delivery correction, avoiding an unnecessary backward step that resets addresses.

`missing-capture` still drives the correct real shopping sequence. Its config
explicitly asks the parent to seal and retain the genuine journal, then suppress
only the automatic adapter callback. The family policy does not change capture;
the parent must implement this separately labeled incomplete-evidence control.
Every config carries `scripted` metadata tags; pass them to the runner preserving
other tags. The parent owns automatic native/canonical/viewer agreement and the
full SR01–SR27 browser acceptance matrix. This source candidate is not accepted
browser or evaluation readiness.

Extra billing terms are Website-owned: accident cover 49 SEK once, shopping club
39 SEK/month, shoe care subscription 59 SEK/month, and donation 15 SEK once.
`extra_terms={label, price_minor, billing_period}` can replace the declared terms
for the one modeled extra. The kit renders these terms and charges the selected
amount in the committed order; the native family does not grade extra prices.
Sponsored URLs encode only axes supported by the existing site's URL behavior.
Remaining exact options are visibly listed and selected through the native form.

Source-only checks (no host, browser or world generation):

```bash
python3 /home/bjorn/code/LLM_proj_uu/scripts/run_bounded_job.py --memory-mib 2048 -- \
  /home/bjorn/code/LLM_proj_uu/.venv/bin/python -m pytest \
  environments/commerce_scenarios/steering_recurrence/test_steering_recurrence.py -q
```

Family files live in a nested directory, so pass `source_files()` explicitly;
the common kit's `kit_sources()` scans only its own top-level sources. No shared
kit, Product grader or composition source is owned by this family.
