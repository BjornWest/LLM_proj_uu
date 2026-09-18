# Review without rewriting outcomes

Use the selected packet and exact evidence to answer a specific question. A flag
is a pointer; a similar reviewed trace is a precedent, not an automatic label.
For the causal rubric and examples, use the library commands below rather than
inventing another taxonomy.

```bash
python3 -m data.curation.trace_triage.case_library vocabulary --catalog PATH/catalog.json
python3 -m data.curation.trace_triage.case_library search \
  --catalog PATH/catalog.json --episode EPISODE_ID --limit 3
python3 -m data.curation.trace_triage.case_library search \
  --catalog PATH/catalog.json --tag behavior:repeated-add --limit 3
```

An episode-based library search requires that episode in the library's triage
inputs. For a new cohort, build a new snapshot using both the prior and new triage
paths plus existing review files; or search existing tags/type/text directly.
Default type searches exclude speculative alternatives; add `--include-hypotheses`
only when intentionally looking for competing explanations. Empty categories do
not justify inventing an example. The existing P07 review is unresolved causality.

Copy `diagnoses/KEY.json` to a new `.local/reviews/NAME.json` before editing. Record:

- Reviewer identity, reviewed/needs-more-evidence status and concise explanation.
- Supported primary/secondary causes, or null/`unknown_or_ambiguous`.
- Exact artifact names and SHA256 from this episode's `source_artifacts`; optional
  step IDs and a specific claim for each evidence item. Preserve counterevidence.
- First suspicious decision, first verified violation and irreversible step
  separately. A missed reading opportunity is not automatically irreversible.
- Namespaced tags and their bound artifact references. Reuse established tags;
  do not put speculative causal conclusions into apparently descriptive tags.
- For an integrity audit: a scoped `integrity_review` with findings and cited
  evidence. Status is `no_issue_found_in_scope`, `suspected_issue`,
  `confirmed_issue`, or `inconclusive`. A limited clean review is not a guarantee
  that every possible side effect or information channel was checked.

Allowed tag namespaces are `behavior:`, `evidence:`, `outcome:`, `context:`,
`procedure:`, `review:`. For example, observed repeated clicks can support
`behavior:repeated-add`; an unconfirmed answer-leak hypothesis should be qualified
as `review:suspected-answer-leak` and explained with both support and uncertainty.
Task completion, authorization, procedure, exposure and technical failure remain
separate. Do not invent a mandatory navigation sequence after observing a shortcut.

```bash
python3 -m data.curation.trace_triage.annotations \
  --triage PATH/triage.json --diagnosis .local/reviews/NAME.json

python3 -m data.curation.trace_triage.case_library build \
  --triage PATH/triage.json \
  --reviews .local/reviews/NAME.json \
  --output .local/review/NEW-reviewed-library
```

Validation establishes structure and evidence identity, not truth. If a conclusion
depends on evidence outside the bound snapshot, identify that limitation and add
the evidence through a separately versioned export before citing it as bound.
Do not fabricate a hash reference or substitute another run's journal. Keep prior
reviews and conflicts visible. Do not propagate a representative's labels to
uninspected group members, change reward, or mark training eligibility from review.

Summarize inspected vs total members, supported mechanisms vs alternatives, and
what missing evidence would resolve uncertainty. If a deeper reproduction or new
model run is needed, record it as proposed work rather than silently executing it.
