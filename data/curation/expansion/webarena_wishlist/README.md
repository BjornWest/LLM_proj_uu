# Original wishlist tasks, isolated full shopping site

Scope: original WebArena Verified **465–469** (template186: find a named product and add to wishlist) and **516–520** (template196: add the current product). Ten source instances, two templates, one complete shopping website; not ten different sites. Original rows, prompts, start URLs and native evaluator specifications are preserved in `contracts.json`. Expected product IDs are private grader inputs. No dark patterns or alternate goals are added.

The dedicated full cached shopping image runs on **17770/17771**, container `curation-webarena-wishlist-v1`, owner `curation-wishlist`, with no shared mounts. The original shared7770 store is untouched. Exact original product start URLs are mapped to the local origin for deictic tasks516–520. A database `type_id=simple` does not establish absence of custom product options: the actual original pages are preserved and checked. The driver must not invent an unspecified choice.

`run.py` uses the copied frozen core-tools-v3 native-tool runtime, fresh contexts and current delivered AX BIDs. Scripted lookup terms for465–469 are short pieces of the original requested product name, followed by exact visible product-name selection. Wrong-product controls deliberately use a different visible search result. These are privileged reachability tests with mock model transport, not teacher/model trajectories.

`WishlistTask` separately captures initial/final database wishlist items/options and, before close, authenticated wishlist and account pages. Completion means the requested product persists in the user's final wishlist with positive quantity, with exact rendered row identity/name/quantity agreement. Missing evidence or account mismatch stays unknown. Wrong new products and removal of preexisting wishlist entries are scoped authorization violations; other cart/account/site changes remain unchecked, so clean authorization and safe success remain null.

Original goals specify no exact wishlist quantity. The leading “2” in task466 is part of its product name, not an instruction to add two line items. A duplicate-add control records its resulting quantity without inventing an exact-one requirement. Native request-history scores are retained independently, including any mismatch caused by their exact expected POST quantities or a correct add later removed.

## Validation and reproduction

```bash
.venv/bin/python -m unittest data.curation.expansion.webarena_wishlist.test_grader -v
.venv/bin/python data/curation/expansion/webarena_wishlist/suite.py \
  --tasks 516 --variants positive \
  --output .local/curation-expansion/wishlist-NEW
```

Output must be a new directory. The existing owned container and saved original empty-wishlist baseline are prerequisites. Cases are sequential because they share that dedicated account. Between controlled cases the suite removes only that account's wishlist items/options and proves the initial empty membership restored. This is **not** a whole-database reset and does not certify reset readiness for arbitrary model actions. No other service is reset or mutated. Each child has a240-second process-group bound; failures and partial artifacts are retained. A warning-bearing case remains separate from a clean one.

Per-process closures include copied runtime, driver/grader/contract sources, original dataset and native evaluator. Exact raw requests, HARs, observations, screenshots, selected targets, final private evidence and original native scores remain available. No model calls, paid calls, downloads or core changes are used. Acceptance and training eligibility require independent review and remain false in the source contracts during staging.

## Session setup revision

The first unmodified fresh-context probe, `.local/curation-expansion/wishlist-probe-v1/516-positive/report.json`, exposes a native false positive: POST302/native1 despite “Invalid Form Key. Please refresh the page.” and an empty final wishlist. Its initial cached product response does not establish PHPSESSID. This is infrastructure evidence, not a model failure.

`run_v2.py` and `suite_v2.py` establish the benchmark fixture's authenticated session with an ordinary GET of the original `/customer/account/` before navigating to the original task start. The setup response and cookie **names** are recorded privately. No application source, CSRF validation, form keys, manually inserted cookies or original task goals change. Policy begins on the exact original source URL. A fresh task516 probe at `.local/curation-expansion/wishlist-session-probe-v2/516-positive/report.json` then persisted the correct product, matched the independently rendered wishlist and had zero action errors. The v1 evidence remains historical. Use `suite_v2.py` for this staged revision; original `suite.py` remains the demonstrated unbootstrapped protocol.

## Saved cohort and limitations

`validation-index.json` indexes **23** session-bootstrapped cases: ten positive/wrong-product pairs, plus task516 add-then-remove, duplicate and missing-read controls. All ten positives persist the requested product and all ten wrong-product controls reject it. Six pairs are clean candidates for independent review: **467, 516, 517, 518, 519, 520**. Positives465/466/468/469 and the465 wrong-product case retain browser action warnings, so these four task pairs are not presented as clean.

- Original native grading rejects correct467/468/469 additions because the real original UI sends `qty=1` while the checker expects absent/null quantity. Raw native scores remain0.
- Add-then-remove receives native1 but derived final completionfalse.
- Duplicate add produces one item with quantity2; completiontrue, quantity diagnostictrue, authorizationnull.
- Missing independent read preserves completionnull despite native1.
- Custom-option products were saved without selecting options; persisted `info_buyRequest` confirms no invented custom option values.

The control runner `run_controls_v3.py` uses the actual AX removal name `Remove item`; the element's HTML title has capitalized `Remove Item`. This correction was made from saved AX **before** executing that control, in a new file; pair drivers and their traces remain unchanged. Control output directory `.local/curation-expansion/wishlist-controls-v2` is historical naming; its report schema and executed entrypoint explicitly identify control runner v3.

The producer audit checked **1,488** exact artifact hashes, **71** selected current-AX targets, **94** exact native mock request/message pairs, all36 copied runtime modules per episode, and evaluation-before-close. Audit source/evidence: `.local/curation-expansion/wishlist-audit-v1/`. Unit tests:8 pass. Original unbootstrapped CSRF failure adds one separately retained historical case; it is excluded from the23-case staged cohort. All acceptance and training flags remain false pending independent review; no model capability claim is made.
