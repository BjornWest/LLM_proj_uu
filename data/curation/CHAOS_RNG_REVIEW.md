# Chaos seeded variation: confirmed arithmetic defect, scoped diversity evidence

The installed `browser-agent-chaos@0.1.0` seeded random-number utility uses
JavaScript Number multiplication for a large integer recurrence. Precision loss
strongly biases its low bits, which directly drive variant selection and
shuffling. This is a source and offline execution finding. No environment was
modified, no new model trials were run, and existing checker outcomes are not
relabelled.

Pinned CLI SHA256:
`0271f4aba16401862247244be943194d96c2e5902529a8e3a9a7547b586352b1`.
The relevant source section is `packages/core/dist/seedutil.js` embedded in that
installed bundle. It computes:

```js
this.state = this.state * 1103515245 + 12345 & 2147483647;
// pick(arr): arr[this.next() % arr.length]
// shuffle: j = this.next() % (i + 1)
```

Typical products exceed the range in which Number preserves every integer.
Masking afterward cannot recover the discarded bits. Picks modulo small powers
of two and the final modulo-two shuffle choice are particularly exposed.

## Reproducible evidence

The token factory was first inspected using 24 synthetic seed strings,
`curation-token-static-review-00` through `-23`, through the existing sandboxed
installed-source inspector. These are not live sessions. All 24 targets were
MacBook Pro; target position was middle in 18 and last in six, never first. The
safe rotation action always appeared second, despite a source shuffle of both
rows and actions. Synonym labels still varied. Checker target identities were
consistent with the generated fixtures, so this finding concerns diversity
rather than a wrong-answer key for these instances.

The separate numeric diagnostic uses 1,024 well-spread reproducible integer
seeds: the first four bytes of SHA256(`token-rng-review:` + index), read unsigned
big-endian, for indices 0 through 1023. It executes only the installed seed
utility inside an isolated JavaScript VM, generating 32 values per seed.

| Diagnostic | Installed code | In-memory `Math.imul` comparison |
| --- | --- | --- |
| First four-way pick, index 0 | 1023 | 262 |
| First four-way pick, index 1 | 0 | 252 |
| First four-way pick, index 2 | 0 | 243 |
| First four-way pick, index 3 | 1 | 267 |
| First update differs from exact BigInt arithmetic | 1018 / 1024 | 0 / 1024 |
| Even outputs after the first update | 31620 / 31744 | 15879 / 31744 |

The comparison replaces only `this.state * 1103515245` with
`Math.imul(this.state, 1103515245)` in the isolated context. BigInt independently
checks the exact first recurrence update and mask. The changed arithmetic
restores those exact first updates and removes this extreme sample bias. It is
**not** a deployed repair or proof that the remaining linear-congruential
generator, modulo sampling, correlations or shuffling are adequate.

Reproduce with `node data/curation/inspect_chaos_rng.mjs`. It verifies the pinned
CLI hash before inspection and saves the source section, script hash, seed
recipe, examples and counts in
`data/curation/routed-pilot-token-v1/rng-review.json`.

## Implications and limits

- Multiple session seeds need not produce meaningfully different tasks. Audit
  realized target position, action order, labels and values before claiming
  diversity or allocating scarce model calls.
- Fixed positional shortcuts may exist in subsets of generated instances.
  T01 itself selected the correct middle row and second action, but one trace
  does not reveal whether it used semantics or position. No shortcut-exploitation
  claim follows from its success.
- The helper is shared by task factories, so other seeded families may also be
  affected. Only token variants and the helper's arithmetic were quantified in
  this review; per-family effects require their own inspection.
- These sample counts are neither an exhaustive analysis nor the exact
  distribution of live server session IDs. They are sufficient to reproduce
  the arithmetic mismatch and severe bias in the stated samples.
- Any repair changes generated fixtures for historical session seeds. Version
  the generator/build, retain original raw traces, regenerate descriptors, and
  obtain new browser/grader validation before running a repaired cohort. Do not
  silently reinterpret old sessions under new arithmetic.

This belongs in the joint environment/curation review after demo work. The
immediate curation response is to measure actual diversity; no source patch or
additional paid batch is requested by this document.
