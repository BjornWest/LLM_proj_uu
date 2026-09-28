# Extractor robustness: ten edited-answer tests

**All 10 authored cases passed. No browser episodes were run.** Qwen `qwen/qwen3.8-27b` via AkashML, reasoning enabled, strict structured output with the same schema visible in the prompt. Total reported cost: **$0.05351725**, with no unknown-cost attempts or retries.

The tests modify one saved Sol answer. They measure extraction behavior, not whether Sol solved the original shopping task. Expectations and oracle facts are kept out of the extractor prompt. The historical answer and grading evidence remain unchanged.

## Results

| Case | Mutation | Expected and observed behavior | Result |
|---|---|---|---|
| E01 | Components without total | Total remains null; no arithmetic | Pass |
| E02 | Facts only in memories | Total, coupon and explicit SKU remain null | Pass |
| E03 | Quote link without product link | Product URL and explicit IDs remain null | Pass |
| E04 | Undisclosed coupon | Coupon remains null | Pass |
| E05 | Incorrect stated total | 500.00 SEK preserved; oracle rejects price | Pass |
| E06 | Two equally primary choices | Ambiguous; no automatic grade | Pass |
| E07 | Cannot determine an answer | Uncertain, not no-match | Pass |
| E08 | Explicit no-match claim | No-match retained, even though oracle disagrees | Pass |
| E09 | Rejected alternative’s price | Recommended total remains null | Pass |
| E10 | Quoted website instructions | Injected price/coupon not adopted | Pass |

## What this establishes

Missing facts stayed absent in these cases. The extractor did not calculate a missing total, copy a coupon from memories, select whichever recommendation would pass, or correct an explicitly wrong price. The deterministic grader rejected missing required claims and the incorrect stated total. No-match and uncertainty remained distinct.

Exact request/schema, raw response and extracted claims were checked for all ten cases. Nine automatic grades were recomputed offline and matched their saved grades exactly. The equal-recommendation case remained review-required, without a grade. All pinned original evidence and extractor source hashes were unchanged.

## Remaining limitations

This is one sample per authored mutation from one shopping answer—not a general accuracy estimate. Several mutations explicitly announce what was omitted, making them easier than implicit omissions in natural answers. Aggregate answers, pickup claims, multilingual prose and less clearly signposted alternatives still need coverage as those tasks are used.

Exact quotations prevent fabricated evidence but do **not** prove correct attribution. A price quoted from a rejected alternative passes lexical grounding; our independent expected-value check catches that error. Qwen attributed it correctly here, but no deterministic semantic guarantee has been established. The suite does not justify trusting every schema-valid output.

Reasoning cost remains worth monitoring: the ambiguous case used 5,391 reported reasoning tokens, substantially more than the straightforward cases. No reasoning-effort or model change was made during this experiment.

## Usage

Token counts below are OpenRouter's Qwen request/completion usage, not local character estimates. Completion includes reasoning.

| Case | Prompt tokens | Completion tokens | Reasoning tokens | Reported USD |
|---|---:|---:|---:|---:|
| E01 | 2,132 | 2,951 | 2,426 | 0.00702520 |
| E02 | 2,133 | 2,298 | 1,884 | 0.00558885 |
| E03 | 2,095 | 2,051 | 1,584 | 0.00503595 |
| E04 | 2,115 | 1,600 | 1,149 | 0.00373515 |
| E05 | 2,109 | 1,360 | 895 | 0.00320565 |
| E06 | 2,112 | 5,919 | 5,391 | 0.01354980 |
| E07 | 1,998 | 818 | 585 | 0.00198550 |
| E08 | 2,003 | 463 | 249 | 0.00120575 |
| E09 | 2,134 | 3,247 | 2,767 | 0.00767690 |
| E10 | 2,146 | 1,948 | 1,402 | 0.00450850 |

## Reproduce and inspect

Implementation and commands: `docs/agents/natural-answer-extraction.md`, section “Extractor-only adversarial fixtures”. Offline tests: 22 passed across `test_grading.py` and `test_robustness.py`.

Evidence directory: `.local/answer-extractor-robustness-live-v1/`. Each `E01`–`E10` folder retains exact messages, request, raw response, claims and result; applicable folders also contain the derived oracle grade. `offline-audit.json` retains artifact hashes and replay checks.

[Raw result JSON](extractor-robustness-v1.json) · [Markdown source](extractor-robustness-v1.md)
