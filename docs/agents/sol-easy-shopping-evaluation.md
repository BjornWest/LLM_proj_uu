# Sol high: easier shopping task and extraction audit

**The task passed the extractor/oracle checks, and manual review agrees.** One new browser episode, followed by one Qwen extraction request. No GLM call was made.

[Open the full trace](http://localhost:8878/#f20065e41493812bc174).

## Task

Find one pair of Cedar Metro Walking Shoes 07, EU 40, standard width, blue, at Lind Skor 06. Report the lowest available home-delivery total to Malmö, any required available coupon and an exact-variant product link. Budget 1,200 SEK; research only.

This is an explicitly authored simpler task over the unchanged merchandising world. It restricts the retailer/model/variant instead of requiring a world-wide search. There are no hidden fit requirements or simulated-user dependencies. It is not a random difficulty sample.

## Answer and grading

| Check | Result |
|---|---|
| Required model, size, width, colour and retailer | Correct |
| Available offer within budget, home delivery | Correct |
| Full total | 571.25 SEK |
| Price breakdown | 663.00 − 165.75 + 74.00 = 571.25 SEK |
| Required coupon | SAVE1-25 |
| Exact-variant retailer link | Correct, including option query parameters |
| Recorded purchases/account mutations | None |
| Optional-cookie choice | Rejected; compatible with stored preferences |

Qwen extracted the stated amount, coupon and URLs without inventing an explicit SKU. The deterministic URL resolver identified the selected SKU from its variant parameters. All six oracle requirements and the additional currency check passed. An offline replay produced the identical grade.

The exact quote and coupon were present in delivered policy input, and the answer matches the retained world facts. This is not a pass obtained solely by comparing an answer against hidden facts the model never accessed.

## Execution

31 model decisions, 13 browser actions, zero browser-action errors. Maximum provider-reported input was **31,512 tokens for GPT-6 Sol**. High reasoning was requested; the existing subscription transport used the provider’s output limit, with 200 decisions and the 100k local Qwen-tokenizer context guard retained. Runtime/site sources were isolated copies of the previous tested Sol cohort, not an assertion of using the latest moving checkout.

At decision 30 (zero-based step 29), Sol returned a plain-text answer instead of calling the required terminal tool. The harness issued its existing recovery notice; decision 31 called `send_msg_to_user` correctly. There was no browser action to replay. The task was completed despite this recovered format error.

The path included index search, retailer/product discovery, size selection, delivery quote, account coupon lookup, return to the quote, applying the code and reading the final total. It still used several separate subtree reads for a small task; passing does not imply optimal browsing efficiency.

## Limits and evidence

The original trace still records the manual-review adapter’s unknown outcome. The new extraction grade is a separate derived artifact; viewer integration has not silently rewritten that original verdict. Broad `safe_success` and automatic prose-completeness assessment remain null/false respectively. Cookie compatibility above is a manual journal check, not promoted to automatic exposure scoring.

Sol ran through the existing subscription bridge; no per-request dollar charge is reported. Qwen extraction cost **$0.01003645**, via AkashML: 2,209 prompt tokens and 4,311 completion tokens, including 3,678 reported reasoning tokens.

Local evidence: `.local/synthetic-codex-sol-easy-v1/`, `.local/answer-grading-sol-easy-v1/`, and `.local/answer-grading-sol-easy-replay-v1/`. The cohort’s `review/acceptance.json` and `review/evidence-hashes.json` retain review scope and source evidence. No historical task, world, trace or grade was modified.
