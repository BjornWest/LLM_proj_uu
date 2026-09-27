# Qwen manual-review depth preparation

User decision, 2026-09-26: evaluate the first batch by reading natural answers and
traces against frozen world facts. New graders and answer-extraction work are deferred.
No paid run was started by this preparation.

## Ownership split

Product owns task bindings, private reference facts/math, hidden specification replies
and realized-world ambiguity checks. Website/Curation owns the normal harness adapter,
public task/memory delivery, browser isolation, natural final answers, trace/reference
attachments and site readiness. The current runner lacks a nonterminal question tool;
Curation is coordinating an opt-in ask_user pathway with Backend rather than editing
shared harness code without ownership agreement.

Basket and split-store quote semantics remain Product's next larger depth increment;
Website will own eventual basket presentation. Accurate joint shipping/stock allocation
needs a separate contract and does not block this first single-line baseline. Lookup,
complete-list and review-count tasks can already be manually assessed without new
answer contracts or graders.

Coordination: `.local/coordination/qwen-depth-readiness/handoff.md` and
`host-contract.md`. The website agent confirmed the host boundary and requested the
private reply callable. Product delivered both callable and bank via accepted steering;
accepted delivery alone is not completion of the host implementation.

## Proposed bank

`.local/coordination/qwen-depth-readiness/manual-bank-v1/manifest.private.json` contains
14 proposed cases: the previous six plus eight authored controls on the unchanged
v7/example-v4 world. The manifest is preparation, not paid-cohort authorization.

| Added case | Purpose | Realized population |
|---|---|---|
| D01 | Direct item price and warehouse-stock lookup | One exact offer |
| D02 | Compare two laptop configurations and weight | Two offered SKUs; equal weight |
| D03 | Mean of each shop's cheapest shoes in remembered size | Four available offers; two retailer minima |
| D04 | Delivered beer price per litre under total budget | Seven eligible offers; two retailers |
| D05 | Complete list of qualifying laptop options | Two SKUs at one retailer; limited search depth |
| D06 | Heel-rubbing claims with context and attribution | Twelve reports, eleven firsthand, one hearsay |
| D07 | Cycling, collection readiness and stock transfer | Nine branch offers; one qualifies |
| D08 | Ask the user's omitted size before selecting a SKU | Three equally priced available sizes; one after reply |

Difficulty is a hypothesis for trace review, not measured performance. The old wine
no-match and empty laptop mean remain; the new controls add nonempty arithmetic without
replacing inconvenient outcomes. Controls are deliberately authored and must not be
used as estimates of natural sampled-world outcome frequencies.

Public files contain exactly schema_version, task_id, user_message, memories,
environment_context and start_url. Task IDs are opaque. No grading envelope, expected
outcome, hidden specification or reference facts are delivered to the model. Private
attachments bind the public hash, source hashes, factual reference and optional reply
specification. Public and private directories are separate; never mount the bank root
as a browser-accessible directory.

## Clarification boundary

`environments.product_world.manual_clarification.FrozenClarificationResponder(spec)`
is a host callback. Its result includes reply, audit_id and matched status; only reply
is policy-visible. Input specification is private_packet['clarification']. The host
records the exact question/reply and private matching metadata in the same episode.

For D08 the request specifies Aster Stride 0001, black and standard width. Size is absent
from both request and memories. Real available sizes38/40/42 all cost970SEK delivered.
Thus the initial cheapest price does not determine a unique SKU. A personal-size
question returns “EU 40, please.”, leaving one eligible exact option. A guessed correct
SKU is distinguishable from the intended clarification behavior in manual trace review.

The responder handles common English personal shoe-size questions and wrong suggested
sizes. It does not infer answers to inventory, price, budget or unrelated questions.
Unsupported questions return a fixed unavailable response. Unsupported paraphrases are
a simulator limitation for reviewers to identify, not an automatic agent failure.
It is not a general natural-language user simulator and does not perform unit conversion.

## Local checks and next dependency

Eighteen callback unit tests pass. Fourteen independent artifact/reference/privacy
checks pass with bounded concurrency3. They verify frozen sources, exact public/private
hash binding, arithmetic populations, review attribution, branch readiness and actual
ambiguity before the hidden reply. No model answer was scored by these checks.

Scripts and evidence live under `.local/coordination/qwen-depth-readiness/`; the bank
has its own pins.json and artifact-check.private.json. Existing six-case inputs and
published sites were not mutated. Website/Curation is integrating fake-provider host
acceptance and preparing the finite Qwen run profile. Readiness still requires that
host path; a frozen task bank alone is not a completed model evaluation pipeline.
