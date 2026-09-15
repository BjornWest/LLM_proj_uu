# Running and comparing development sweeps

The reusable entrypoint is `data/curation/run_sweep.py`. It uses the existing
runner, task adapters and graders; it changes no policy prompt or termination
rule. This is a selected development suite, not a complete published benchmark.

## First suite

```bash
.venv/bin/python data/curation/run_sweep.py template > /tmp/sweep-config.json
# Edit task subset, repeats, model, provider subset or supported limits as needed.
.venv/bin/python data/curation/run_sweep.py init --suite external-baseline-v1 --config /tmp/sweep-config.json
.venv/bin/python data/curation/run_sweep.py run --suite external-baseline-v1
.venv/bin/python data/curation/run_sweep.py run --suite external-baseline-v1 --live --limit 1
.venv/bin/python data/curation/run_sweep.py report --suite external-baseline-v1
```

`init` preflights local environments and freezes a new profile. `run` without
`--live` only rechecks readiness. `--limit` counts new episodes, skipping completed
cases. The default profile schedules 14 conditions in each of three rounds:
seven Chaos tasks, P07/P10/P11 clean and injected, and synthetic DEV-W01.
Start with one episode, inspect it, then run the remaining 13 first-round cases.
Inspect the first round before the additional 28. Repetitions are new sessions,
not retries of failed requests.

## Regression use

Create a NEW suite after changing the model or harness, with the same task
selection and limits where possible. Changed core verifiers must first have
matching validation evidence; a changed source cannot resume a frozen suite.

```bash
.venv/bin/python data/curation/run_sweep.py init --suite candidate-v2 --config /tmp/candidate-config.json
.venv/bin/python data/curation/run_sweep.py run --suite candidate-v2 --live --limit 1
.venv/bin/python data/curation/run_sweep.py compare --suite external-baseline-v1 --other candidate-v2 > /tmp/comparison.json
```

Comparison matches task/condition/repeat, retains separate completion,
authorization and technical outcomes, and lists changed configuration/source
fields. It is a diagnostic comparison, not a significance test. Chaos session
IDs generate the actual page variants independently of the BrowserGym seed;
each case saves its full privileged descriptor. Match realized variants and
providers before attributing differences solely to a harness/model change.
Strict identical-variant replay is not implemented by this wrapper. Tricky pairs
use identical goals and BrowserGym seeds with their clean/injected conditions.

## Evidence and budget

- Each suite has an immutable `profile.json`, one retained case file per attempt,
  and regenerable `report.json` / `REPORT.md` summaries under `data/curation/sweeps/`.
- Full raw traces stay under `runs/`. Each case retains trace artifact hashes,
  requested-vs-resolved provider evidence, costs and separate evaluation fields.
- A single `data/curation/sweeps/budget.json` serves ALL new suites. It carries
  $0.64922375 of historical reservations into the same cumulative $3 allowance.
  Daylight/team-worker budgets are separate. No refunds or recycled reservations.
- Per-request reservations use UTF-8 serialized message bytes + 2,048 as a
  conservative input token bound, multiplied by the $0.50/M input price cap,
  plus the configured output limit at $4/M. Only plain-text requests are allowed;
  reported input tokens must fit that bound. This is a conservative bound, not
  an exact tokenizer count. Maximum input bound 24,000; output at most 512.
- Before starting each episode, sufficient capacity for its full worst-case
  request count is required. The actual request reservations remain in the ledger.
- At least 10 seconds elapse after each completed attempt before the next fresh
  decision observation. The backend never waits on a constructed prompt.
- No client retries. HTTP, transport, cost/provenance errors and interrupted
  reservations block further dispatch. Parser/episode errors pause the command;
  an explicit resumed invocation can skip an audited completed episode after
  human/agent review. Interrupted/unaudited case files require investigation.
- Max 12 decisions by default, temperature 0, reasoning off, session routing,
  headless browser and video; Parallel disabled. Actual provider affinity is not
  guaranteed. No padded prompts or special task hints.
- Existing module/build/manifest/certificate sources are pinned. The complete
  runtime module inventory at freeze is separately recorded, including additive
  demo/team files; only the relevant execution closure gates each request.

Unknown outcomes remain null. Scripted environment tests are not model results.
Every case remains development-only, training-ineligible and curation-not-ready.
Do not edit or delete a budget/profile to gain more capacity or bypass a failure.

Offline verification:

```bash
.venv/bin/python -m unittest discover -s data/curation -p test_sweep.py -v
```
