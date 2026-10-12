# Website consent and extras

Maps Product's prepared `commerce-consent-extras-v1` setup to the shared host.
Product alone owns scenarios, preferences, native grading and completion scope.
This package adds no grader and does not modify the released journal v1 or its
Addenda 1–3. The native simulated order is the newsletter/paid-extra commit.

## Attachment API

```python
from environments.commerce_scenarios.consent_extras import (
    settings_for, assets, sources, accepts_order_target, case_config, policy_for)

native = instance['prepared']                 # frozen Product registry instance
config = case_config(instance, 'positive')    # or 'wrong', 'incomplete'
episode = ScenarioEpisode(world, settings_for(native['setup']), assets=assets(),
    task={'task_id': automatic.task_id(instance),
          'user_message': automatic.public_request(instance),
          'memories': automatic.public_memories(instance), 'start': config['start']},
    bind_episode=lambda actual_id: registry.bind_episode(instance, actual_id)['prepared']['binding'],
    source_files=sources(), lazy_publication=True)
# The parent creates CommerceGrading with episode.capture.journal and the full
# pinned native + kit + family + world closure BEFORE dispatch, then uses:
result = scripted.run(episode, policy_for(episode, instance, config['case']), output,
    contract=adapter.contract(), finalize=adapter.finalize, metadata=config['metadata'],
    max_steps=50)
```

`settings_for(setup)` returns checked detached host settings. It consumes only
the setup, never private expected preferences/reference. Newsletter and each
native extra use `preselected='start'`, preserving the declared selected baseline.
Paid identity, integer SEK price, label and one-time/monthly billing survive
unchanged. The family page displays explicit one-time/monthly terms.

`accepts_order_target(native_prepared)` declares support for ordinary native order
tasks or explicit cookie `preference_preservation`; it evaluates no English order
authority. Publication callers pass `instance['prepared']` to this helper.

`case_config(native_or_registry_instance, case, allowed_selected=False, offer_id=None)` returns
choices, start, expected capture, completion kind/scope and scripted metadata.
`policy_for(episode, native_or_registry_instance, case, allowed_selected=False,
offer_id=None, address=None)` returns a finite live-page `next_action(page)`.
It uses normal tool actions for displayed variant selectors, address, checkout
steps, preferences, shopping terms and the existing native purchase form. A
parent can supply a frozen native in-stock offer/address fixture. Without one,
it chooses the first native in-stock variant and ordinary remembered address.
There is no retry/search if native stock/address/quote fails: retain the failed
attempt and diagnose the fixture.

For required preferences, positive selects them and wrong omits them. Forbidden
positives clear them and wrong selects them. Mixed cookies preserve each purpose's
separate preference. Allowed selected/unselected positives are both supported;
all-allowed has no wrong preference control. Cases `abandon` and
`preserve_without_save` supplement the declared positive/wrong list. The latter
requires the explicit native `preference_preservation` objective; it assesses
no shopping completion. `incomplete` must use `start='world'`; it finishes before
visiting the retailer and allows the original journal to seal as `no_session`.
No callback edits or repairs evidence.

With `objective='preference_preservation'` and an explicit exact `offer_id`, cookie
positive/wrong policies validate the in-stock target before any page action,
resolve the popup with the existing preference actions and then continue the
shared native order flow on the same episode/session. The config records
`cookie_order_continuation=True`; no checkout extras are inferred from cookie
purpose choices. `consent_saved`, preservation without a target and
`preserve_without_save` and `abandon` retain their terminal behavior. Those two
remain scope-only no-save controls, even if a target is supplied; they do not
validate its stock or navigate to it. Shopping continuation
is an observed driver witness; native `task_completion_assessed=False`, canonical
shopping completion and viewer completion stay unassessed. There is no additional
order-content grader or order-authority inference.

The parent owns publication admission/forwarding: accept the explicit target
according to `accepts_order_target(native)` and pass it to `case_config` as well
as `policy_for`. The family extension requires that composed publication source
to be independently reviewed before actual browser use.

## Coverage and acceptance status

| Native mechanism | Host surface | Positive/wrong generator | Browser acceptance |
|---|---|---|---|
| `cookie_asymmetric` | emphasized Accept, quiet first-level Reject, settings | required/forbidden/allowed and mixed purposes | parent pending |
| `cookie_settings_only` | emphasized Accept, settings-only rejection | required/forbidden/allowed and mixed purposes | parent pending |
| `cookie_obstructive` | blocking modal, no dismissal, settings rejection | required/forbidden/allowed and mixed purposes | parent pending |
| `newsletter_prechecked` | selected initial newsletter control | real simulated order, selected or cleared | parent pending |
| `paid_warranty` | selected initial warranty, exact one-time price | real simulated order, selected or cleared | parent pending |
| `paid_membership` | selected initial membership, exact monthly price | real simulated order, selected or cleared | parent pending |
| `paid_subscription` | selected initial subscription, exact monthly price | real simulated order, selected or cleared | parent pending |
| `paid_donation` | selected initial donation, exact one-time price | real simulated order, selected or cleared | parent pending |

One reusable incomplete policy covers the family; preservation/no-save covers all
three cookie surfaces. Source tests exercise native adapter/grader outcomes via
the shared host state machine, with authored fixtures, plus renderer execution
and finite driver regressions. Those are source controls, not browser acceptance.
The parent's finite 51-episode batch supplies actual browser setup/capture,
automatic grade attachment and viewer projection; 17 cases belong to this family.
Authorized-positive, transient grants/revocations, refused totals and extra
missing-evidence matrix proposals remain additional acceptance coverage unless
the parent explicitly includes them in a finite list.

## Reproducible source validation

The isolated base lacks Product modules, so provide the exact pinned Product
composition as the second namespace root. These tests use only small authored
world records, no world generation, browser, provider or cloud call.

```bash
PYTHONPATH="$WEBSITE_TREE:$PRODUCT_TREE" \
python3 /home/bjorn/code/LLM_proj_uu/scripts/run_bounded_job.py --memory-mib 2048 -- \
  /home/bjorn/code/LLM_proj_uu/.venv/bin/python -m unittest \
  environments.commerce_scenarios.consent_extras.test_family \
  environments.commerce_scenarios.consent_extras.test_continuation \
  environments.commerce_scenarios.consent_extras.test_policies -v
```

Acceptance must pin both source closures, the reviewed common post-clear
correction and immutable generated-world assets. Committed true/live false is
valid: read submitted newsletter/extras from `committed.order`. Full raw history
must survive, and cookie preservation must keep
`task_completion_assessed=False`. Scope remains simulated local effects;
order contents and broader billing/tracking effects are unassessed.
