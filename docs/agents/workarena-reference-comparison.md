# WorkArena reference-field comparison

This is a scripted investigation of the incomplete warranty lookup in
`runs/20260915T165640Z-46fff017`. It makes no model or search calls and changes
no shared action/parser/runner implementation. The original model episodes,
profiles, verdicts and budget remain frozen.

## Question and protocol

The model typed the correct person's name, then submitted a filter that became
`Assigned to = (empty)`. A displayed name is not necessarily a resolved native
reference record. We compare four paths with one newly generated person and
laptop on the real research instance:

1. Ordinary BrowserGym `fill`, then Run.
2. `fill(..., enable_autocomplete_menu=True)`, then Run.
3. The same autocomplete fill, an explicit exact option click, then Run.
4. WorkArena's native privileged `fill_text` helper, then Run.

Each path starts with a fresh list document and blank Assigned to filter. The
driver focuses the native field before marking it: initialization on focus
replaces the initial input. All paths get a ten-second settling wait before
Run. Two rounds reverse the method order; they share a session and generated
target, so they are not independent population samples.

Preparation uses privileged Playwright locators. Tested BrowserGym fill/click
actions pass through the existing parser and action mapping. The upstream-helper
arm is explicitly a privileged control. Diagnostic reads retain the visible
name, hidden reference value, menu state, resulting native query, AX text and
screenshots. Hidden values never become model input.

An explicit option click is a non-scoring procedure observation, not a required
step: a different path that reaches the correct record must also pass.

Success here means that the resulting query is exactly `assigned_to=<target ID>`
and the expected person/date are present in the resulting AX. It is not a full
model task-success or broad authorization certificate. Final field/modification
counts are compared for the synthetic target records, and deletion is checked
for the temporary runner account, target person and laptop.

## Result

The completed eight-trial comparison at
`.local/workarena-exercise/reference-comparison-v3/report.json` reproduced the
same pattern in both orders:

| Path | Correct target filter | Reference stored before Run |
| --- | --- | --- |
| Plain fill | 0/2 | No |
| Autocomplete fill, no option click | 2/2 | No; the correct query appears on submission |
| Autocomplete fill plus exact option click | 2/2 | Yes |
| Upstream helper | 2/2 | Yes |

All eight paths displayed the correct name before Run. Waiting ten seconds did
not make plain fill equivalent to autocomplete. The six correct queries exposed
the expected date in the resulting AX. This reproduces the reference-resolution
mechanism behind the historical empty filter; it does not establish the cause of
every earlier action failure or the model's subsequent repeated clicks.

No new action implementation is needed for this field. The existing optional
parameter is sufficient in this exact-name scenario. Explicit selection is also
supported but is not an outcome requirement. Broader ambiguous-name, slow-network
and other reference widgets remain untested. A future opt-in prompt experiment
can explain reference/autocomplete handling and checking the resulting query;
it needs its own profile, evidence and budget review before model calls.

All eight trials had zero BrowserGym action errors. The independent saved-only
audit checked 77 artifact hashes and four source hashes; scoped target records
were unchanged, and all three temporary records were verified deleted.

The read-only result index is
`data/curation/workarena_exercise/reference-comparison-review-v1.json`.

## Reproduction and saved-evidence audit

From the repository root, with approved research access and the existing isolated
dependencies/credentials:

```bash
LD_LIBRARY_PATH="$PWD/.local/system-libs/usr/lib/x86_64-linux-gnu" \
  .venv/bin/python data/curation/workarena_exercise/inspect_reference.py \
  --output .local/workarena-exercise/reference-new-comparison
```

This creates and deletes synthetic records on the hosted instance. Choose a new
directory. It is not offline browser replay and does not invoke a model.

The separate audit does run offline:

```bash
.venv/bin/python data/curation/workarena_exercise/audit_reference.py \
  --report .local/workarena-exercise/reference-new-comparison/report.json \
  --output .local/preflight/reference-new-audit.json
```

It checks original artifact/source hashes, recorded action errors, query identity,
visible result evidence, scoped changes and cleanup. It does not import the
native verifier. Keep fresh outputs separate from historical evidence.

## Historical context and development failures

`data/curation/workarena_exercise/reference-model-context-v1.json` verifies the
saved model requests: the optional autocomplete parameter and a `True` example
were present. Before fill, the current field was labeled `textbox`; before Run,
it was labeled an autocomplete combobox. This establishes the information
available at each decision, not the model's understanding.

The first comparison driver targeted the field before native initialization and
encountered a BrowserGym fill timeout. The second completed plain-fill and
autocomplete-only trials, then its top-document frame lookup failed in the
explicit-selection arm. All three synthetic records were removed in both runs.
Their reports and exact source copies remain under `.local/workarena-exercise/`
as `reference-comparison-v1`, `reference-comparison-v2`, `reference-driver-v1.py`
and `reference-driver-v2.py`. These are incomplete development probes, not full
suite passes. The final driver waits inside the already-resolved native frame.
