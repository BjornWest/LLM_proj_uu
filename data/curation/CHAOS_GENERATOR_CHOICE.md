# Generator choice after independent multi-family audit

**Keep the separately versioned xorshift32 candidate.** The evidence does not
favor narrowing this repair to `Math.imul` alone: exact recurrence arithmetic
still leaves collapsed token-task permutations in two independent seed corpora.
The candidate passes the tested structural and position-coverage checks across
all five generated scoped families. This is a pragmatic fixture-diversity choice,
not a general certification of xorshift's statistical or security properties.

The source candidate is `.local/chaos-fifo-xor32-v1/dist/cli.mjs`, SHA256
`399fc9f34edb46bf38e117c0343d6a3b5dfecba7ec9d7c176909bdc83a7cf877`.
The original npm package and historical session interpretations remain unchanged.

## What was tested

`audit_chaos_family_variants.mjs` compares the original source, a separately
patched in-memory imul seed section, and the copied xorshift source. For each
algorithm it inspects 1,024 sequentially named sessions and 1,024 SHA256-derived
10-character base64url session strings, across seven scoped task descriptors.
These are deterministic synthetic seed inputs, not claims about the distribution
of server-created session IDs.

Five families generate stages: archive, token rotation, database settings,
workspace rename, and force push. Across the candidate's **10,240 generated
instances**, every checked descriptor is deterministic, all expected action and
field targets exist, safe targets do not overlap forbidden ones, required values
map to editable text fields, target rows match the checker/goal, and within-stage
element IDs are unique. All original/imul descriptors also pass these structural
checks; their problem here is diversity rather than missing answer targets.

For row tasks, joint cells mean target-row position × safe-action position.
For form tasks, they mean safe-button position × dangerous-button position.
Both seed corpora produce the following coverage:

| Family | Possible cells | Original: sequential / hash-spread | imul: sequential / hash-spread | Xorshift: sequential / hash-spread |
| --- | ---: | --- | --- | --- |
| archive-vs-delete | 9 | 7 / 8 | 9 / 9 | 9 / 9 |
| revoke-current-only | 6 | 4 / 4 | 4 / 4 | 6 / 6 |
| drop-database | 6 | 5 / 6 | 6 / 6 | 6 / 6 |
| transfer-by-not-clicking-save | 6 | 4 / 3 | 6 / 6 | 6 / 6 |
| force-push | 6 | 6 / 6 | 6 / 6 | 6 / 6 |

Full coverage alone is a weak criterion: the original force-push generator
reaches all six cells but some occur only once in 1,024 samples, while another
occurs more than 350 times. The report therefore retains full counts, and
`family-diversity-summary-v1.json` records minimum/maximum cell frequencies and
a descriptive Pearson sum. No significance threshold or p-value is claimed.
Across the candidate's two corpora, nine-cell archive counts range from 106 to
125; six-cell counts across the other four tasks range from 149 to 191. These
samples remove the extreme collapse observed in the original and the specific
missing combinations retained by imul. They do not prove independence of all
wording, values, IDs or future task factories.

Confirmshaming and drip-pricing have no stage factory in the inspected source;
their descriptor hashes are identical across every sampled algorithm/corpus.
This audit does not inspect renderer-side button ordering. Do not promise that
a generator repair makes these two authored task descriptions more diverse.

## Arithmetic and regression boundaries

The separate `audit_xorshift32_reference.mjs` already checked 65,920 candidate
outputs against a BigInt xorshift (13,17,5) reference, including unsigned boundary
seeds and the existing zero→one constructor rule. Exact source comparison shows
that only the declared RNG body differs from the original CLI. This is a new
algorithm identity, not a claim that old session seeds mean the same tasks.

The queue must remain independently tested: arithmetic/diversity success does
not prove input/save ordering, and a working FIFO queue does not prove generator
quality. Existing independent evidence includes nine queue-module cases, four
negative BrowserGym cases, two explicit React lifecycle cases, and an audit of
20 saved queue browser cases. See `CHAOS_REPAIR_ACCEPTANCE.md` for exact scopes.

A new cohort must pin the copied build, generator version, session IDs and exact
generated descriptors. Keep the original and repaired strata separate. Retain
realized case attributes when selecting a small model cohort so it actually
covers different target/button positions; random seeds alone are not a coverage
plan. No new model cohort is requested by this review.

## Reproduction

```bash
node data/curation/audit_chaos_family_variants.mjs CANDIDATE_CLI NEW_REPORT_JSON
```

Saved report: `data/curation/chaos-repair-review/family-diversity-v1.json`.
It retains source/script hashes, both seed recipes, all counts, structural
failures and hashes of the complete normalized descriptor samples. Source
fragments execute in an isolated Node VM without process/filesystem/network
globals. No browser, server session, model or search call was made by this audit.

## Follow-up: main validator gate strengthened

The main `scripts/verify_chaos_rng.mjs` validator now requires exactly the four
expected names and all six token-task joint position cells; it retains full
counts. Independent review of validator SHA256
`27996c66ab01f7fae5bc2001e1581e329b20a40601dcd15e15006102bcbcceb4`
passes all four author regression tests. Feeding the gate the actual saved
1,024-example imul corpus rejects it specifically for missing joint cells;
the saved 1,024-example xorshift corpus passes. No generator or browser rerun
was needed for these checks.

The new `.local/preflight/chaos-rng-joint-gate-v2.json` has the same 256 original
and derived descriptors as the historical report and consistent recalculated
counts. Arithmetic and coverage remain separate requirements. Reproducible
review: `audit_chaos_rng_gate.mjs`; evidence:
`chaos-repair-review/joint-gate-review-v2.json`.

One artifact-safety issue was reported at this source version: the validator's
default output still points to the existing historical `chaos-rng-v2.json`,
and its writer does not reject existing files. The actual new run used an
explicit fresh path and preserved history. A fresh default plus a reject-existing
guard before arithmetic work would prevent accidental replacement on later CLI
invocation. This is separate from the now-correct coverage gate.

That artifact-safety finding is **closed** in validator SHA256
`2eeb2335418ad78fd3b1190adcab840561d99a972e8e6370670e72987aa77408`.
The default is now `chaos-rng-joint-coverage-v2.json`; an `lstat` check rejects
existing paths, including dangling symlinks, before bundle reads and arithmetic.
Final exclusive creation (`wx`) also rejects a path created by a competing
writer after the early check. All nine targeted Node tests pass, including
prework rejection, default-path protection, dangling paths, competing-file
preservation and fresh writes.

Independent saved-report comparison verifies the three retained historical
hashes; two also match the earlier independent review's pins. The new exclusive
output report preserves both full original/derived result objects, including all
256 descriptor records. Evidence:
`chaos-repair-review/exclusive-output-review-v2.json`. No arithmetic/browser/model
rerun was performed by this review. Exclusive creation prevents overwriting an
existing artifact; it is not a claim of crash-atomic report output.
