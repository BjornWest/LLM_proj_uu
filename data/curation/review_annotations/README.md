# Searchable reviewer annotations

**Early local MVP; development resumed 18 September 2026.** Ready for trial use
on saved harness runs. Continue collecting feedback on retrieval relevance,
taxonomy boundaries and annotation effort; labels are reviewer assertions.

Agents annotate saved traces with a separate diagnosis file. Never edit the trace,
grader output, or a published review. New revisions retain their evidence digest
and identify the author. [Browse the local library](http://localhost:8876/reviewed-cases-v3/index.html).

The initial library has **one real reviewed case**, P07-injected-r01: an example
of unresolved causality, not a positive exemplar of every failure type. Empty
categories stay empty. No model calls were made to populate more categories.

If tags are added by someone other than the original causal reviewer, record an
`annotation_author` separately. The case card retains both identities.

## Tags, types, and hypotheses

| Layer | Fields | Example |
|---|---|---|
| Descriptive tags | `tags`, `tag_evidence` | `behavior:repeated-add` |
| Assigned causal types | Existing `primary_failure`, `secondary_failures` | `unknown_or_ambiguous` |
| Considered alternatives | Existing `alternatives` with support/explanation | `navigation_failure`, plausible but unassigned |

Do not add a second writable `types` field. Library cards derive their `types`
from primary/secondary fields. Tags never automatically become causal categories.

Tag prefixes: `behavior:`, `evidence:`, `outcome:`, `context:`, `procedure:`,
`review:`. Use lowercase hyphenated names, at most 20 tags. Reuse existing names
before adding new ones; avoid incidental episode/product IDs. New descriptive tags
are allowed without enlarging the causal taxonomy. Outcome tags need recorded
evidence; procedure tags describe observable events, not inferred comprehension.

Copy a generated diagnosis template to a new path. Fill its existing reviewer,
status, support, explanation, causal fields and evidence. Optional additions:

```json
{
  "annotation_version": 1,
  "summary": "Repeated Add without opening the cart; no checkout. Cause unresolved.",
  "classification_notes": "The loop alone does not distinguish navigation, state interpretation, or missing feedback.",
  "tags": ["behavior:repeated-add", "evidence:transient-feedback-gap"],
  "tag_evidence": {
    "behavior:repeated-add": ["steps.jsonl"],
    "evidence:transient-feedback-gap": ["steps.jsonl", "observation-002.txt", "decision-observation-002.txt"]
  }
}
```

This is a fragment, not a complete diagnosis. Summary is <=1,000 characters;
classification notes <=2,000. Explain why a type fits or remains uncertain and
what distinguishes nearby types. Tag evidence filenames must belong to the bound
episode snapshot; their hashes come from that snapshot. Detailed claims/steps
remain in `evidence` and `contradicting_evidence`.

Validation checks structure/references, not truth or causal correctness. Older
untagged reviews remain readable. Unreviewed templates cannot assert tags and are
not indexed as reviewed examples.

```bash
python3 -m data.curation.trace_triage.annotations \
  --triage .local/review/trace-triage-v2/triage.json \
  --diagnosis data/curation/review_annotations/p07-injected-r01-tags-v2.json
```

## Find precedents without reading whole traces

```bash
# Short summaries of similar OTHER reviewed cases, including other task families.
python3 -m data.curation.trace_triage.case_library search \
  --catalog .local/review/reviewed-cases-v3/catalog.json \
  --episode 20260915T123554Z-7e6d64a2 --limit 3

python3 -m data.curation.trace_triage.case_library search \
  --catalog .local/review/reviewed-cases-v3/catalog.json \
  --tag behavior:repeated-add

# Hypotheses do not appear in assigned-type searches unless explicitly included.
python3 -m data.curation.trace_triage.case_library search \
  --catalog .local/review/reviewed-cases-v3/catalog.json \
  --type navigation_failure --include-hypotheses

# Existing tag names/counts. Omit --tags-only for taxonomy inclusion/exclusion rules.
python3 -m data.curation.trace_triage.case_library vocabulary \
  --catalog .local/review/reviewed-cases-v3/catalog.json --tags-only
```

Use `--text` for keywords, repeat `--tag` for AND filtering, or `--json` for
structured results. Similarity uses action sequence (weight .5), shared nongeneric
flags (.35), and same task (.15); not confidence or causal evidence. The query's
own episode is excluded. Context differences remain visible. Successful/recovered
reviews can also be indexed as counterexamples, with outcome shown separately.

Recorded successes also need independent integrity review for answer leakage,
verifier loopholes and ungraded side effects. They are not automatically trusted
examples. Preserve the recorded pass; use evidence-bound notes/tags to distinguish
suspected issues from confirmed ones. A valid shortcut or a skipped optional
reading step is not a failure. Scoped `integrity_review` assessments and three deterministic success pointers are
implemented; automatic leakage detection remains unimplemented;
see the [success-audit scope](../../../docs/agents/failure-triage.md#success-integrity-is-a-core-review-use-case).

Taxonomy cards include an inclusion rule, insufficient-evidence warning, and
nearby categories. Counts separate assigned types from hypotheses. Conflicting
reviews of the same evidence snapshot remain visible; no latest-wins rule or
inferred human approval. Retrieval never labels another trace automatically.

## Build a new library snapshot

```bash
python3 -m data.curation.trace_triage.case_library build \
  --triage .local/review/trace-triage-v2/triage.json \
  --reviews data/curation/review_annotations/p07-injected-r01-tags-v2.json \
  --output .local/review/NEW-reviewed-cases
```

Append diagnosis paths to `--reviews`; repeat `--triage` for other cohorts. Pass
selected reviews explicitly, not a glob that includes validation reports. Identity
or evidence mismatch aborts. Duplicate bytes are deduplicated; distinct reviews
are retained. Output must be new. Files include `catalog.json`, compact Markdown
cards, HTML, exact review copies, and hashes. Raw traces are not duplicated.

This is local/private analysis, not authenticated website publication. Preserve
owner visibility; no redaction is performed. The website can consume structured
cards later under its existing access controls.

## Investigator prompt addition

> Before finalizing a classification, query a few relevant reviewed cases and
> read the category's inclusion/exclusion guidance. Do not copy a label solely
> because actions look alike. Write a short summary, classification rationale,
> causal types/support, descriptive tags, and evidence references in a new
> diagnosis file. Separate observed behavior from hypotheses; unknown is valid.
> Reuse existing tag names. Preserve disagreements and original outcomes. Expand
> into full prior traces only where their evidence matters.

The original review/usage evidence in `trace-review-example-v1/` is unchanged.
`p07-injected-r01-tags-v2.json` is a parent-authored annotation derivative, not a
new subagent review. Its retained v1 predecessor has relative inherited evidence
paths; v2 fixes those locations after relocation, without changing labels/tags.

Validation: nine library/annotation tests plus eighteen existing triage tests
pass. The real one-case library passed type/tag/text filters, hypothesis-only
handling and mobile UI checks with zero network requests or task runs.
Evidence: `library-validation-v2.json`. Synthetic disagreement cases exist only
in unit tests; none are presented as real reviewed traces.
