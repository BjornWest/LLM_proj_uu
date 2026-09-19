# Remaining original shopping tasks

Seven original Tricky task families, TO15–TO21, on the complete unchanged site:
cart plus reported total; buying a named laptop; buying the highest-rated or
newest touchscreen laptop; and reporting the price of the cheapest,
highest-rated, or newest touchscreen laptop. “Newest” follows the site's
original date-added sort, not external product release dates.

The original prompt remains separate from grader inputs. Monetary replies have
an explicit terminal-response instruction. Purchase checks use the retained
checkout journal; a correct later purchase cannot hide earlier extra purchases.
Completion does not imply complete authorization coverage or training eligibility.

`tasks.py` extends the already validated batch02 adapter without changing it.
`verify.py` uses the existing native adoption wrapper in its own process with a
scripted MockTransport, source guards, current-observation target checks and
bounded child processes. It calls no model provider.

```bash
CURATION_FROZEN_RUNTIME="$PWD/.local/curation-expansion/frozen-runtime-v1" \
PYTHONPATH=. .venv/bin/python -m data.curation.expansion.tricky_original_remaining.verify \
  --output .local/curation-expansion/tricky-original-remaining-NEW
```

Optional `--task TO17` selects one positive/negative pair. Use a new output
path. The explicitly copied runtime is documented in `runtime_snapshot.py` and
`docs/agents/dataset-expansion.md`; it is not the evolving checkout runtime.

Evidence: `.local/curation-expansion/tricky-original-remaining-frozen-v1/report.json`
contains14passing cases with zero action errors. Parent compact index:
`data/curation/expansion/tricky-original-remaining-validation.json`.
Independent second-agent review:
`data/curation/expansion/tricky/reviews/remaining-originals-independent-v1.json`.
It checks1504artifact hashes,114current-AX action targets and all14outcomes.

Earlier probe failures remain retained: an initial child-dispatch configuration
error; clicking an Ant Design combobox intercepted by its label; attempting to
click an option BID absent from delivered AX; and later live-checkout source
drift. The accepted driver uses ordinary keyboard navigation of the combobox.
These are development diagnostics, not model failures. No site control was
removed or silently made easier.
