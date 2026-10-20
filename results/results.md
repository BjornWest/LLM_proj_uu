# Results data: Qwen3.8-27B browser agent on the 34-task capability suite

Read-only extraction from saved run artifacts, compiled 2026-10-19. No model, browser or cloud runs were made for this file. Machine-readable per-task data is in `per_task.csv` (same directory). Section 9 lists the evidence paths.

## 1. Headline (primary run)

| | Value |
|---|---|
| Model under test | `Qwen/Qwen3.8-27B-FP8` (HF revision `017b9c7a…`), self-hosted with vLLM 0.28.0 |
| Hardware | 1× RTX PRO 6000 S (Vast.ai offer 52618749, France), $1.578/h |
| Run window (episodes) | 2026-10-15 22:57 UTC to 2026-10-16 00:07 UTC (suite 1: 22:57–23:34; suite 2: 23:41–00:07) |
| Tasks | 34 (A01–A04, B01–B20, H01–H10) |
| **Pass** | **17 / 34 (50.0 %)**; 17 / 31 automatically graded (54.8 %) |
| Fail (graded) | 14 |
| Error (no grade) | 3 (B07, B10, H03): the 16,384-token output limit was reached inside a repetitive reasoning loop, with no tool call |
| By category | A: 3/4 pass · B: 9/20 pass (9 fail, 2 error) · H: 5/10 pass (4 fail, 1 error) |
| Median model turns per episode | 24.5 (mean 50.9, range 4–219) |
| Median episode wall time | 263 s (mean 574 s, range 39–2,051 s) |
| Total policy tokens (34 counted episodes) | 119.18 M prompt tokens (94.8 % served from prefix cache) + 0.479 M completion tokens (70.7 % of them reasoning) |
| Requests finishing with `length` | 3 of 1,732 policy requests (0.17 %): exactly the 3 errors |
| Rental | 1.632 h (22:31:19 to 00:09:15 UTC) × $1.578/h ≈ **$2.58**. Account credit went from $9.733 to $7.111, so $2.62 was charged. |

**Correction to the prior belief:** the outcome is **17 pass / 14 graded fail / 3 errors**, not 14 pass / 17 fail. Per run: suite 1 had 10 pass and 5 fail; suite 2 had 7 pass and 9 fail. I checked this two ways: `suite-outcomes.json` (`task_pass`/`task_fail` counts) and the `task_completed` field of every counted `evaluation.json`. The three errors match the prior belief (H03, B07, B10).

Tokens are counted with the served model's own tokenizer. The numbers are vLLM `usage` fields from every policy response in `http-attempts.jsonl`. "Prompt tokens" is the full request input, summed over turns, so each turn re-counts the history. The answer-extraction ("formatter") requests are excluded: 25 requests, 47 k prompt and 92 k completion tokens.

## 2. Which attempt counts (suite 1 vs suite 2)

- **Suite 1** started 2026-10-15 22:57 with up to 7 concurrent episodes. It was stopped at 23:34:39 (`job-stop.json`: cause `shared_service_unhealthy`, problem `chromium_pool_service_exited`). At the stop:
  - 15 episodes were completed and graded (10 pass, 5 fail).
  - 3 had execution failures:
    - B07 and H03: length/no-tool-call errors, genuine model-side errors.
    - B18: `tool: Child lifecycle exited 1`, a browser-pool infrastructure failure.
  - 7 were cancelled by the job stop. B10, B16, B17, B20, H01 and H02 were in flight (6 episodes, no grade). H04 was cancelled before dispatch.
  - 9 had not started (A01–A04, H06–H10).
- **Suite 2** started 23:41 with up to 5 concurrent episodes. It ran the 17 remaining tasks: the 8 quarantined cases from suite 1 (B10, B16, B17, B18, B20, H01, H02, H04) plus the 9 unstarted ones. Result: 16 completed (7 pass, 9 fail) and 1 execution failure (B10, length error).
- **Rule used:** a task's counted attempt is its only graded or model-error attempt. The 8 tasks that appear in both suites had no grade in suite 1 because of infrastructure (6 in-flight cancellations, 1 pre-dispatch cancellation, B18's browser-pool failure), so suite 2 counts for them. No task was graded twice, and the harness ran no task retry (`no_failed_case_retry: true`).
- So there were 8 reruns, not 6: the 6 in-flight losses, H04 (cancelled before dispatch) and B18 (failed when the Chromium pool died).
- Compute spent on lost attempts (not counted above): 8 extra episodes, 390 policy requests, 68.6 k completion tokens. All attempts together: 2,122 requests and 0.548 M completion tokens.

## 3. Task suite (what the 34 tasks ask)

The suite comes from the capability-sweep design (`qwen-capability-sweep-20261010/suite-design-v2.{md,json}`). Its objective is a *"breadth-first diagnosis of Qwen weaknesses, not a benchmark score"*. It has 34 probes covering all 19 catalog task kinds "plus atomic actions and focused hindrances". The design never spells out the letters. From the `group` field and the v1 header they appear to mean:

- **A** = atomic micro-actions (group "Micro-actions"; graded by the `atomic-product` contracts)
- **B** = base probes, one per catalog task kind (groups Shopping and scope, Reading and reasoning, Memory and interaction, Review interpretation, State and checkout)
- **H** = hindrance/trap probes (Variant hindrances, Interface variation, Review interpretation, State and checkout)

"Basic/Hard/Action" is not the scheme. Treat this decoding as inferred, not stated.

Every task runs on a procedurally generated web world: fictional shops (`*.test`), comparison sites, review sites and carriers in SEK, scenario date 2026-09-30. A run starts on a relevant page. The model must browse, act and finish with a natural-language answer, or with a cart or order state. Prompts below are the actual `policy-task.json` user messages from the Vast run.

| Task | Group | What the task asks (actual prompt, abridged) |
|---|---|---|
| A01 | Micro-actions | What is the listed price of the navy Solvik duvet-cover set with a 150 by 200 cm cover? Include the currency. |
| A02 | Micro-actions | How much does the Dalen Tula tablet weigh? Include the unit and the reference configuration the measurement applies to. |
| A03 | Micro-actions | Set these Hedmark Ylva sandals to brown, EU38. Leave that variant selected. |
| A04 | Micro-actions | Add exactly two navy Solvik duvet-cover sets with a 150 by 200 cm cover to my cart. |
| B01 | Shopping and scope | Which available walking shoes shown on Prisradar 1 are cheapest? Any model and size is fine. Use the retailer's listed price for one pair, before shipping or discounts;… |
| B02 | Reading and reasoning | How many different casual-trainer models have a listed price on Prislyktan? Include a link to the comparison page. |
| B03 | Reading and reasoning | What is the average of the lowest listed price for each casual-trainer model on Prislyktan? Tell me how many models you counted and include a link to the comparison page. |
| B04 | Shopping and scope | On Prislyktan, find the lowest listed price for Hedmark Eira in navy, EU43, standard width. At one cheapest listed retailer, check whether that variant is in stock and t… |
| B05 | Shopping and scope | Find the cheapest in-stock walking shoes in EU42 with moderate cushioning and a published reference weight of at most 340 g. Compare listed item prices across the shops,… |
| B06 | Shopping and scope | Find the cheapest in-stock pair of walking shoes in EU size 42 that can be delivered to my home by 9 October 2026. My address is Alex Lind, Björkvägen 12, apartment 24,… |
| B07 | Memory and interaction | I want one T-shirt for myself. Find the in-stock option with the lowest listed price across these shops and give me the model, colour, size, shop, listed price in SEK an… |
| B08 | Memory and interaction | Find the in-stock pair of walking shoes with the lowest listed price for me across these shops. Give me the model, selected variant, shop, listed price in SEK and produc… |
| B09 | Review interpretation | What do reviewers on Model Review say about Vallheden Strand’s grip on wet paving when walking? Summarize the balance of opinion and give the counts of positive, negativ… |
| B10 | Shopping and scope | Find the lowest combined checkout total for one sale unit of walking shoes in EU size 42 and one sale unit of a men’s or unisex T-shirt in size M, with home delivery. Sa… |
| B11 | Reading and reasoning | List the three cheapest distinct models of in-stock walking shoes available in EU size 42, using each model’s cheapest matching offer. Include any models tied at the las… |
| B12 | Shopping and scope | Find the in-stock walking shoes in EU size 42 with the lowest listed price and a stated reference mass of at most 220 g per shoe at EU size 40. If none qualify, try at m… |
| B13 | Reading and reasoning | Which available dry cat-food pack has the lowest listed price per kilogram? Give the model, retailer, pack size in grams, whole-pack price, price per kilogram and produc… |
| B14 | Reading and reasoning | Which in-stock walking shoes in EU size 42 have the lowest stated reference mass per shoe, measured at EU size 40? If the reference masses tie, choose the lowest listed… |
| B15 | Reading and reasoning | Compare Bergliden Sola and Almheden Vilo. Give one row for each model with its cushioning and reference mass in grams per shoe at EU size 40, citing a retailer product p… |
| B16 | Review interpretation | How have customers described the handoff for LumoParcel's regular service from 14 August 2026 onwards? Give counts of positive, negative, neutral, mixed and unrelated wr… |
| B17 | State and checkout | Add one pair of walking shoes in EU size 42 and two pairs of walking sandals in EU size 42 to my carts at eligible shops with the lowest combined listed item prices, kee… |
| B18 | Shopping and scope | What do Lind & Vireto’s advertised free-shipping terms mean for two navy Norr T-shirts in size M, single-shirt packs, delivered to Alex Lind at Björkvägen 12, apartment… |
| B19 | State and checkout | Get this cart ready for home delivery, with “Please use the side entrance” as the delivery note. |
| B20 | Shopping and scope | Find the walking shoes in EU42 with the lowest listed item price that I can collect from a branch in Uppsala, Sweden. Give the model, selected colour and width, retailer… |
| H01 | State and checkout | Please order the item in my Lumeri cart using the cheapest home delivery. |
| H02 | State and checkout | Please order the item in my Lumeri cart using the cheapest home delivery. |
| H03 | Variant hindrances | Set these Hedmark Ylva sandals to EU size 38, then choose black and add one pair to my cart. |
| H04 | Variant hindrances | Send me a link to these Hedmark Ylva sandals in brown, EU size 38. |
| H05 | Review interpretation | What do reviewers on Model Review say about Vallheden Strand’s grip on wet paving when walking? Summarize the balance of opinion and give the counts of positive, negativ… |
| H06 | Review interpretation | What do reviewers on Model Review say about Vallheden Strand’s grip on wet paving when walking? Summarize the balance of opinion and give the counts of positive, negativ… |
| H07 | Review interpretation | What do reviewers on Model Review say about Vallheden Strand’s grip on wet paving when walking? Summarize the balance of opinion and give the counts of positive, negativ… |
| H08 | Interface variation | How much does the Dalen Tula tablet weigh? Include the unit and the reference configuration the measurement applies to. |
| H09 | Interface variation | Which available walking shoes shown on Prisradar 1 are cheapest? Any model and size is fine. Use the retailer's listed price for one pair, before shipping or discounts;… |
| H10 | Review interpretation | What do customers say about Linddal Orla's grip when walking on wet paving? Summarize their own walking experiences, with counts of positive, negative, neutral, mixed an… |

**Paired tasks.** Three pairs share a task/oracle ID but differ in recipe setup (start URL, presentation or saved state):

- A02 and H08: same tablet-weight question; H08 hides the fact in a collapsed panel.
- B09 and H07: same review question; H07 starts on the reader-response page sorted by highest rating.
- H01 and H02: the same order-with-cheapest-home-delivery request, with different saved-state setups (stale autofill vs. missing apartment unit).

H05, H06 and H07 have identical prompts but different review corpora. So there are 31 distinct oracle IDs, not 34.

## 4. Per-task results (primary run)

- **Turns** = policy model requests. Each request returns 1–8 native tool calls; 1,953 tool calls were executed in total.
- **Wall** = `episode_started` to `episode_finished`. It includes browser actions and the automatic grading inside the episode; it excludes environment pre-warm and the separate answer-extraction call.
- **Max req. prompt** = the largest single request input in the episode. The harness input budget was 250,000.
- **†** = the graded fail looks like an answer-extraction or grader false negative (see §5). The official verdict is unchanged.

| Task | Probe (design title) | Outcome | Turns | Completion tok | Prompt tok | Max req. prompt | Wall (s) | Stop reason | Attempt |
|---|---|---|---:|---:|---:|---:|---:|---|---|
| A01 | Read a price | pass | 4 | 728 | 32,474 | 9,168 | 56 | agent_finished | suite-2 |
| A02 | Read a fact with its basis | fail † | 4 | 837 | 32,688 | 9,216 | 85 | agent_finished | suite-2 |
| A03 | Select the requested variant | pass | 5 | 810 | 43,881 | 10,525 | 39 | agent_finished | suite-2 |
| A04 | Add exactly two | pass | 8 | 1,250 | 82,599 | 14,545 | 80 | agent_finished | suite-2 |
| B01 | Cheapest shown here | pass | 25 | 7,553 | 668,100 | 43,953 | 198 | agent_finished | suite |
| B02 | Models versus listings | pass | 13 | 10,903 | 280,152 | 37,169 | 220 | agent_finished | suite |
| B03 | Mean of model minima | pass | 21 | 6,713 | 476,312 | 37,614 | 161 | agent_finished | suite |
| B04 | Advertised bargain, actual stock | fail † | 38 | 6,429 | 860,244 | 40,439 | 230 | agent_finished | suite |
| B05 | Two constraints at once | fail | 187 | 31,545 | 20,073,228 | 188,895 | 1805 | agent_finished | suite |
| B06 | Cheap item, expensive delivery | fail | 150 | 32,672 | 14,184,495 | 191,546 | 1568 | agent_finished | suite |
| B07 | Memory belongs to someone | **error** | 51 | 31,726 | 1,988,268 | 69,402 | 1101 | error | suite |
| B08 | One question is necessary | fail | 64 | 8,771 | 2,473,158 | 75,728 | 449 | agent_finished | suite |
| B09 | Ordinary review baseline | pass | 21 | 6,868 | 433,791 | 34,800 | 214 | agent_finished | suite |
| B10 | Shared delivery changes the basket | **error** | 184 | 55,471 | 18,063,088 | 193,232 | 1591 | error | suite-2 |
| B11 | A shortlist with a tie | pass | 60 | 13,329 | 2,464,111 | 79,305 | 888 | agent_finished | suite |
| B12 | Alternatives have an order | pass | 114 | 24,952 | 8,806,041 | 150,548 | 1361 | agent_finished | suite |
| B13 | Cheap pack versus cheap food | fail † | 49 | 10,613 | 1,633,085 | 61,895 | 1052 | agent_finished | suite |
| B14 | Priority is not a vague preference | pass | 219 | 43,866 | 22,811,755 | 208,914 | 2051 | agent_finished | suite |
| B15 | Compare facts without inventing them | pass | 41 | 5,208 | 999,369 | 46,999 | 461 | agent_finished | suite |
| B16 | Carrier versus service class | fail | 35 | 27,196 | 895,094 | 59,468 | 603 | agent_finished | suite-2 |
| B17 | The cart already has something | fail | 90 | 20,888 | 4,810,306 | 99,654 | 665 | agent_finished | suite-2 |
| B18 | Does free shipping really apply? | fail | 55 | 30,057 | 2,762,663 | 94,262 | 706 | agent_finished | suite-2 |
| B19 | Prepare delivery details | pass | 10 | 2,750 | 134,306 | 21,012 | 217 | agent_finished | suite |
| B20 | Local stock is not online availability | fail | 122 | 32,587 | 10,550,444 | 164,148 | 988 | agent_finished | suite-2 |
| H01 | Plausible stale autofill | pass | 38 | 11,107 | 1,418,508 | 63,746 | 1032 | agent_finished | suite-2 |
| H02 | An optional field that matters | fail | 24 | 6,503 | 605,989 | 40,575 | 404 | agent_finished | suite-2 |
| H03 | Changing colour changes size | **error** | 9 | 17,657 | 92,589 | 13,664 | 297 | error | suite |
| H04 | A link cannot carry the variant | fail | 4 | 2,265 | 34,710 | 10,468 | 189 | agent_finished | suite-2 |
| H05 | Opposite opinions in one comment | pass | 12 | 5,839 | 195,965 | 25,767 | 130 | agent_finished | suite |
| H06 | Same words, different circumstances | pass | 12 | 4,618 | 191,646 | 24,518 | 96 | agent_finished | suite-2 |
| H07 | The first page tells another story | pass | 19 | 5,894 | 331,697 | 28,859 | 153 | agent_finished | suite-2 |
| H08 | The needed fact is collapsed | fail † | 12 | 1,855 | 132,414 | 16,088 | 109 | agent_finished | suite-2 |
| H09 | No search box | pass | 22 | 5,571 | 489,157 | 36,291 | 185 | agent_finished | suite-2 |
| H10 | High stars, negative grip | fail † | 10 | 4,066 | 129,794 | 19,360 | 127 | agent_finished | suite-2 |

Pass vs fail medians:

| Outcome | Median turns | Median wall | Median completion tokens |
|---|---:|---:|---:|
| pass (17) | 21 | 198 s | 5,894 |
| fail (14) | 43.5 | 526 s | 9,692 |
| error (3) | 51 | 1,101 s | 31,726 |

## 5. Failure reasons

These come from each run's `automatic-grade.json` (failed requirement names) together with the saved natural answer and the extracted claims. Grading works in two steps:

1. The model's free-text answer is converted to structured claims by an extraction call to the **same model** (Qwen3.8-27B-FP8 acting as "formatter").
2. A deterministic native grader checks those claims, and for action tasks the browser or cart state, against the world's oracle.

| Task | Outcome | Failed grader checks | Reason (from automatic grade + answer) |
|---|---|---|---|
| A02 | fail † | answer | Answer "470 g" with the reference configuration is substantively right, but the extracted claims (unit "g (grams)", qualifier with extra dimensions text) failed the exact-match comparison with the expected {470, "g", qualifier}. Likely extraction/grader strictness; same failure for OpenRouter Qwen and MiMo. |
| B04 | fail † | public_selection_identity; exact_manufactured_sku; minimum_advertised_retailer; live_exact_sku_stock | All reported facts (Hedmark Eira, Veluma, 1,530 SEK, navy/EU43/standard, in stock, both links) match the task, but the extractor wrote size "EU 43" instead of "43", so the grader could not resolve a unique SKU; selection/SKU/winner/stock checks failed. Likely extraction false negative (OpenRouter Qwen passed with size "43"). |
| B05 | fail | extractor_unambiguous; public_selection_identity; retailer_reported; task_eligible; cheapest_listed_offer; reported_price | Answer reported a three-way price tie (Vallheden Sira, 1,540 SEK) without committing to one retailer/product link; extractor marked it ambiguous and eligibility/cheapest/price checks failed. |
| B06 | fail | optimal_objective | Chose Myrvik Runda at Koriva, total 599 SEK (item + home delivery); grader: not the optimal total (optimal_objective failed). |
| B07 | error | – | Error: final policy request hit the 16,384-token output limit inside a repetitive reasoning loop with no tool call ("Expected 1..8 native tool calls"). |
| B08 | fail | task_eligible; cheapest_listed_offer; known_applicable_features; clarification_delivery_and_ordering | Did not ask the required personal-size clarification before answering (clarification_delivery_and_ordering failed); picked EU38 Tallback Tova at Vireto, 790 SEK. |
| B10 | error | – | Error (suite-2 attempt): after 184 turns the reasoning looped ("Let me go back to Caluno's checkout." x124) to the 16,384-token output limit with no tool call. First-run attempt was cancelled by the Chromium-pool job stop. |
| B13 | fail † | public_selection_identity; task_eligible; reported_price; lowest_exact_unit_price; reported_net_food_grams; reported_unit_price | Named the right pack (Grove Ylva 1 kg at Foderboden, 120 SEK/kg, equal to the reference minimum) but the extracted product name carried the pack descriptor ("Grove Ylva - 1000 (dry cat food...)"), so identity resolution failed. Likely extraction false negative. |
| B16 | fail | directional_verdict; positive; not_assessed; assessed_count | Misclassified reviews: reported 4 positive / 2 unrelated and verdict "more positive"; reference 2 positive / 4 unrelated, "insufficient evidence". |
| B17 | fail | price_objective | Cart allocation valid and existing cart item preserved, but bought everything at one shop (2,580 SEK) instead of the optimal 1,980 SEK combination (price_objective failed). |
| B18 | fail | exact_public_offer; option_count; free_option_count; assessment; minimum_shipping | Free-shipping audit wrong: offer identity ambiguous (two listings 150/145 SEK), counted shop collection as a free option (min fee 0); reference: 9 options, none free. |
| B20 | fail | task_eligible; cheapest_listed_offer; physical_branch_and_locality; cheapest_branch_offer | Picked Vallheden Liva at Veska (720 SEK) at an Uppsala branch showing 0 branch stock (collection via warehouse transfer); reference requires positive physical branch stock (cheapest qualifying 1,460 SEK). |
| H02 | fail | address.unit | Order placed, but the submitted delivery address omitted the apartment/unit number (address unit check failed). |
| H03 | error | – | Error: reasoning looped ("Hmm, but wait - maybe the size list is different..." x247) to the 16,384-token output limit with no tool call. |
| H04 | fail | link_encodes_full_selection; recipient_must_select; manual_selection | Claimed the product link encodes the chosen size/colour; reference: the link cannot carry the variant and the recipient must select it manually. |
| H08 | fail † | answer | Same extraction/exact-match issue as A02 (unit "g (grams)", qualifier with extra text); value 470 g correct. |
| H10 | fail † | public_subject_and_review_link | Counts (0/1/0/0/0, 1 written, 1 assessing) and verdict "more negative" match the reference, but the extractor attached the quoted reviewer's variant (navy, EU40) as the review subject, failing the product-scope subject/link identity check. Likely extraction false negative. |

**Observations.**

- **5 of the 14 graded fails (A02, H08, B04, B13, H10) look like extraction or grader-strictness false negatives.** In each case the answer's substantive content matches the reference, but the extracted claim was formatted differently ("EU 43" vs "43"; "g (grams)" vs "g"; a product name with a pack suffix; a quoted reviewer's variant). If those 5 were counted as passes, the rate would be 22/34. That number is only a sensitivity bound, not an official result; it needs a manual check before being quoted. The OpenRouter run shows the same pattern: notes in its progress snapshot attribute the A02/H08/B13/B15 fails to extraction-contract handling.
- **All 3 errors are degenerate reasoning loops under greedy decoding.** In the truncated final responses, H03 repeats one line 247 times, B10 repeats "Let me go back to Caluno's checkout." 124 times, and B07 has 618 lines but only 117 unique. Each reached `max_tokens = 16,384` with no tool call, and the harness then rejected the turn ("Expected 1..8 native tool calls"). The run used temperature 0. Repetition loops in long thinking traces are a known risk of greedy decoding for reasoning models.
- **Substantive model errors:**
  - Ranking/optimisation: B06, B17, B20 (picked an offer without physical branch stock).
  - Review classification: B16.
  - Missing clarification question: B08.
  - Not entering the optional apartment unit: H02.
  - Wrong claim that a link carries the variant: H04.
  - Shipping-term audit: B18.
  - Committing to one offer under ties: B05.

## 6. Serving statistics (vLLM log)

Source: `returned/qwen-serving/cfc7e91f-…/vllm.log`. The local `live-vllm.log` is a near-identical tail copy. The engine logs metrics about every 5 s; 762 samples fall in the episode window.

**Configuration**
- `--max-model-len 262144`, `--max-num-seqs 8`, `--max-num-batched-tokens 8192`, `--kv-cache-dtype fp8_e4m3`, `--gpu-memory-utilization 0.9`.
- Prefix caching on. CPU KV offload connector with 20 GiB, LRU, prompt-only.
- MTP speculative decoding, `num_speculative_tokens = 3`.
- Reasoning parser `qwen3`, tool parser `qwen3_coder`, thinking enabled with preserved thinking.
- GPU KV cache: 1,497,099 tokens (53.4 GiB). Model weights: 28.95 GiB.

**Harness settings**
- Temperature 0, `max_tokens` 16,384 per request.
- 250,000-token complete-input budget per request; no step cap.
- Up to 7 concurrent episodes in suite 1 (observed 7) and 5 in suite 2.

**Metrics over the 762 samples**

| Metric | Value |
|---|---|
| Running requests per sample | median 4, mean 3.7, max 7; waiting queue ≤ 1 |
| Aggregate generation throughput (samples with ≥ 1 running request, n = 748) | median 162 tok/s, IQR 112–211, p90 279, max 434 tok/s |
| Generation throughput by concurrency (median aggregate / per request) | 1 running: 114 / 114 · 2: 175 / 87 · 3: 178 / 59 · 4: 178 / 45 · 5: 167 / 33 · 6: 159 / 26 · 7: 58 / 8 tok/s (n = 61) |
| Prompt (prefill) throughput | median 1,925 tok/s, p90 3,560, max 6,498 tok/s |
| Prefix-cache hit rate (as logged) | median 94.6 %, 94.3 % at the end. Matches the client-side `cached_tokens` share of 94.8 %. |
| GPU KV-cache usage | median 16.6 %, p90 37.4 %, max 61.1 % |
| Speculative decoding (MTP, 3 draft tokens) | overall mean acceptance length **3.53** tokens per step: 462,173 accepted of 548,807 drafted, 84.2 % draft acceptance. Per-position acceptance 0.93 / 0.84 / 0.76. Per-sample median 3.56 (p10 3.29, p90 3.80). |

Aggregate decode throughput plateaus at about 175 tok/s from 2 to 4 concurrent requests and collapses at 7 (median 58 tok/s). The collapse at 7 probably reflects long-context prefill competing with decode, but the log does not show that directly.

## 7. Cost and time

- Rental: 2026-10-15 22:31:19 to 2026-10-16 00:09:15 UTC = 5,876 s = 1.632 h. That includes about 26 min of model download, startup and qualification before the first episode, plus the 6.5-min gap between the two suites. At $1.578/h this is **$2.58** (the credit difference was $2.62). The instance was destroyed and termination confirmed (`deletion-receipt.json`).
- Per task: $2.58 / 34 ≈ **$0.076**.
- Episode time: 63.4 min for all 34 tasks with 5–7 concurrent episodes, counting suite 1 up to the job stop and all of suite 2.
- For comparison, OpenRouter `qwen/qwen3.8-27b` on the same tasks reported **$6.99** in provider charges for the counted attempts. That run's snapshot gives $7.40 across its three attempts plus the H10 recovery. Its median episode wall time was 915 s, versus 263 s self-hosted. Different concurrency and provider latency make this an observational, not a controlled, comparison.

## 8. Baselines on the same task IDs

### 8.1 Runs found and actual model IDs

Only runs with automatic grades are reported. Codenames resolve as follows:

| Codename | Real model id (requests and responses) | Endpoint |
|---|---|---|
| Qwen (OpenRouter) | `qwen/qwen3.8-27b` | OpenRouter; served by `AkashML` (26/27 responses in B01) and `Chutes` |
| MiMo | `xiaomi/mimo-v2.6-pro` | OpenRouter; served by `GMICloud` |
| Luna | `gpt-6-luna` | Subscription bridge (`provider: openai-codex`, Responses API) |
| Sol | `gpt-6.1-sol` | Same subscription bridge |

| Run | Model | Date (UTC) | Tasks with a grade on the same task IDs | Limits |
|---|---|---|---|---|
| **This run** | `Qwen/Qwen3.8-27B-FP8` (self-hosted vLLM) | 2026-10-15/16 | 31 graded (17 pass), 3 errors | 250k input/request, no step cap, 16,384 out, temperature 0 |
| `openrouter-qwen-suite-20261013-v1` (attempts model-v1/v2/v3) | `qwen/qwen3.8-27b` | 2026-10-13 | 33 graded: 18 pass, 1 pass only after a saved extractor retry (H10), 14 fail (8 completed + 6 stopped at the 150k input limit); H04 ungraded (interrupted by a local watchdog) | 150k input, no step cap, 16,384 out, temperature 0 |
| `mimo-atomic4-20261011-v1`, `mimo-queue8-20261012-v1`, `mimo-luna-remaining-20261012-v1` (wave 1) | `xiaomi/mimo-v2.6-pro` | 2026-10-11 to 10-12 | 17 graded on the same task IDs: 5 pass (A01, A04, B01, H03, H09). Also: H01/H02 graded fail but on *different* task instances; 4 grading system failures (B04, B07, B12, B18); A03 error; B09 interrupted | 120k input (atomic4/queue8) or 1,032,192 (wave 1); 200-step cap |
| `luna-rerun-20261013-v1` | `gpt-6-luna` | 2026-10-12 22:16 | 1 graded: A04 pass. All 23 wave-1 Luna cases in `mimo-luna-remaining` failed before any inference (harness `asyncio.run` bug in the quota check), and wave 2 was interrupted by the operator before dispatch. | – |
| `qwen-capability-sweep-20261010/sol-random4-v1` | `gpt-6.1-sol` | 2026-10-10 18:28 | 2 on the same task IDs: B13 fail (24-step cap) and B20 fail (32k input stop). H02 passed, but on a different task instance. | 32k input, 24 steps |
| Earlier self-hosted canary (`openrouter-qwen-suite-…/Verda-private-canary-preparation-v1/vast-switch-v1/florida-live-v1`) | `Qwen/Qwen3.8-27B-FP8` | 2026-10-14 | 7 graded, all pass: A01, A03, A04, B02, H03, H05, H09 | small canary |

Runs with no usable baseline:

- `luna34-parallel-20261011`, `inspect-luna34-wiring-20261011` and `trace-suite-*` hold only scripted (non-model) episodes, tagged `scripted`.
- `episode-suites` holds only viewer and import metadata.
- `qwen-capability-sweep-20261010` holds mostly scripted grader-enablement runs. It also has one Qwen B06 GPU attempt, graded fail at the input limit, from an earlier harness version.
- `qwen-shared-harness-20261012-v1` has an overnight Verda canary (2026-10-13): B02 and H05 pass; B14 and H03 ungraded.
- `gwl-openrouter-timing-20261015-v1` has 4 OpenRouter Qwen A04 timing runs, all pass.

### 8.2 Per-task comparison

| Task | Qwen3.8-27B-FP8 self-hosted (Vast, 10-15/16) | qwen/qwen3.8-27b OpenRouter (10-13) | xiaomi/mimo-v2.6-pro OpenRouter (10-11/12) | gpt-6-luna (10-12) | gpt-6.1-sol (10-10) |
|---|---|---|---|---|---|
| A01 | pass | pass | pass | no valid run | not run |
| A02 | fail | fail | fail | no valid run | not run |
| A03 | pass | pass | error (no tool call) | no valid run | not run |
| A04 | pass | pass | pass | pass | not run |
| B01 | pass | pass | pass | no valid run | not run |
| B02 | pass | fail | not run | no valid run | not run |
| B03 | pass | pass | not run | no valid run | not run |
| B04 | fail | pass | no grade (grading system failure) | no valid run | not run |
| B05 | fail | fail (150k input stop) | fail (120k input stop) | no valid run | not run |
| B06 | fail | fail (150k input stop) | fail (200-step cap) | no valid run | not run |
| B07 | error | fail (150k input stop) | no grade (grading system failure) | no valid run | not run |
| B08 | fail | fail | fail | no valid run | not run |
| B09 | pass | pass | no grade (interrupted) | no valid run | not run |
| B10 | error | fail (150k input stop) | fail (120k input stop) | no valid run | not run |
| B11 | pass | pass | fail | no valid run | not run |
| B12 | pass | pass | no grade (grading system failure) | no valid run | not run |
| B13 | fail | fail | fail | no valid run | fail (24-step cap) |
| B14 | pass | fail (150k input stop) | fail (120k input stop) | no valid run | not run |
| B15 | pass | fail | fail | no valid run | not run |
| B16 | fail | fail (150k input stop) | not run | no valid run | not run |
| B17 | fail | pass | not run | no valid run | not run |
| B18 | fail | fail | no grade (grading system failure) | no valid run | not run |
| B19 | pass | pass | not run | no valid run | not run |
| B20 | fail | pass | fail | no valid run | fail (32k input stop) |
| H01 | pass | pass | fail (different task instance) | no valid run | not run |
| H02 | fail | pass | fail (different task instance) | no valid run | pass (different task instance) |
| H03 | error | pass | pass | no valid run | not run |
| H04 | fail | no grade (interrupted) | fail | no valid run | not run |
| H05 | pass | pass | not run | no valid run | not run |
| H06 | pass | fail | not run | no valid run | not run |
| H07 | pass | pass | not run | no valid run | not run |
| H08 | fail | fail | fail | no valid run | not run |
| H09 | pass | pass | pass | no valid run | not run |
| H10 | fail | pass after saved extractor retry (original grading failed) | not run | no valid run | not run |

### 8.3 Head-to-head

- **Self-hosted vs OpenRouter Qwen, 33 tasks where both have an outcome (H04 excluded):**
  - Both pass: 13 (A01, A03, A04, B01, B03, B09, B11, B12, B19, H01, H05, H07, H09).
  - Both not pass: 10 (A02, B05, B06, B07, B08, B10, B13, B16, B18, H08).
  - Only self-hosted passes: 4 (B02, B14, B15, H06).
  - Only OpenRouter passes: 6 (B04, B17, B20, H02, H03, H10; H10 only after the saved extractor retry).
  - Totals on these 33: self-hosted 17 pass; OpenRouter 19 pass (18 strict).
  - With 4 vs 6 discordant pairs and one run per task, there is no evidence of a difference. B14 passed self-hosted only after its context grew to 209k tokens, beyond OpenRouter's 150k budget.
- **MiMo's 17 graded same-ID tasks:** MiMo 5/17, self-hosted Qwen 7/17, OpenRouter Qwen 7/16 (H04 ungraded there).
- **Luna and Sol:** too few graded same-instance episodes (1 and 2) to compare.

### 8.4 Comparability caveats

- **Same tasks, different grader versions.** All baselines bind the same task IDs and identical prompts; the self-hosted run reuses the OpenRouter run's `recipes-v1`. But OpenRouter and MiMo were graded from frozen per-run source roots (`source-v1/roots/a58f1ad4`, `roots/77c1f27b`, `roots-v3/77c1f27b`). The self-hosted run grades from the current single-version checkout (worktree `claude-qwen-continuous-fixes-20261015`, caller commit `0c426510`). Grader versions differ on about 20 of 34 tasks. Examples: atomic-product consumer v2 vs v1; listed-offer grading v5 vs v3 (OpenRouter) vs v2 (MiMo); catalog statistics v6 vs v5; review grading v5 vs v4; comparison grading v5 vs v2; shipping-claim v3 vs v2. The `grader_contract` column in `per_task.csv` holds the self-hosted version.
- **Different budgets.** Input budgets were 250k (self-hosted), 150k (OpenRouter), 120k or about 1M plus a 200-step cap (MiMo), and 32k plus 24 steps (Sol). Most "input stop" fails in the baselines are budget artefacts.
- **Different extractor.** Each run used its own model as answer extractor (Qwen for the Qwen runs, MiMo for MiMo), so extraction quality is confounded with policy quality.
- **Not exactly the same weights or serving.** Self-hosted is the FP8 checkpoint at temperature 0 with MTP. The OpenRouter run also requested temperature 0, with a provider allow-list and AkashML first; but its providers (mostly AkashML, some Chutes) serve unknown quantisations and may run different engine or template versions.
- **Single run per task.** There are no repeats. The self-hosted episodes ran concurrently with batching, so temperature 0 does not guarantee reproducibility.

## 9. Evidence paths

All paths are relative to `/home/bjorn/code/LLM_proj_uu/.local/coordination/`.

- Primary run: `qwen-vast-run-20261016-v1/rental-52618749-b/returned/qwen-episodes/suite/` and `…/suite-2/`
  - Suite records: `suite-result.json`, `suite-outcomes.json`, `job-stop.json`, `chromium-pool-shutdown.json`
  - Per-task records: `qwen-<ID>/result.json` or `failure.json`, `qwen-<ID>/http-attempts.jsonl`, `qwen-<ID>/live/runs/<episode>/{events.jsonl, automatic-grade.json, evaluation.json, natural-answer.json, policy-task.json}`
- Serving: `qwen-vast-run-20261016-v1/rental-52618749-b/returned/qwen-serving/cfc7e91f-580b-4269-90fe-3383a727100a/{vllm.log, startup-vllm.log}`, `qwen-vast-run-20261016-v1/live-vllm.log`
- Rental and cost: `qwen-vast-run-20261016-v1/rental-52618749-b/{rental.json, host-rental.json, destroyed.json, deletion-receipt.json}`
- Task design: `qwen-capability-sweep-20261010/suite-design-v2.{md,json}`; recipes in `openrouter-qwen-suite-20261013-v1/recipes-v1/<ID>/recipe/`
- OpenRouter Qwen: `openrouter-qwen-suite-20261013-v1/analysis/progress-snapshot-v2.json`, `…/model-v{1,2,3}/qwen-<ID>/`
- MiMo:
  - `mimo-atomic4-20261011-v1/model/<ID>/`
  - `mimo-queue8-20261012-v1/analysis/suite-analysis-v3.json`, `…/model/<ID>/`
  - `mimo-luna-remaining-20261012-v1/model/wave1/mimo-<ID>/`, `…/suite-pause-terminal-v1.json`, `…/quota-loop-failure-consumption-v1.json` (Luna failure cause)
- Luna: `luna-rerun-20261013-v1/model/luna-A04/`
- Sol: `qwen-capability-sweep-20261010/sol-random4-v1/{B13,B20,H02}/`
- Grader source for the likely false negatives: `environments/website_world/{comparison_stock_grading.py, atomic_product_grading.py, catalog_review_grading.py}` in the repository.
