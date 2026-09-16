# WebArena-Verified local control integration

This increment runs complete upstream shopping (Magento) and Reddit (Postmill)
applications. It does not publish them through Vercel, change the current worker,
or claim model benchmark scores. Site containers are pinned by digest in
`deploy/webarena-verified/compose.yaml`; no application routes are removed.

Upstream documentation/data inspected at revision
`6473f72db5dcefc97b5725b59e734504edc28a21`:
<https://github.com/ServiceNow/webarena-verified>.
The images are upstream's *Verified* versions, including documented authentication,
vote-count and URL-handling fixes, not pristine original WebArena images.

## Start and stop

```bash
docker compose -f deploy/webarena-verified/compose.yaml pull
docker compose -f deploy/webarena-verified/compose.yaml up -d
docker compose -f deploy/webarena-verified/compose.yaml ps
docker compose -f deploy/webarena-verified/compose.yaml exec -T reddit env-ctrl init --base-url http://localhost:9999
curl http://localhost:7771/status
curl http://localhost:9998/status
```

Initial downloads are approximately 10 GB compressed combined. Applications bind
only to localhost; the control ports must not be published through the public
tunnel. Shopping needs time to initialize MySQL, Elasticsearch and Magento.
The pinned Reddit image's automatic initializer exits with `base_url is required`;
the explicit command above supplies it. Service health alone does not catch this.

- Shopping: <http://localhost:7770>
- Forum: <http://localhost:9999>

Upstream seeded credentials (synthetic benchmark accounts, not private secrets):

- Shopping: `emma.lopez@gmail.com` / `Password.123`
- Forum: `MarvelsGrantMan136` / `test1234`

The smoke script uses upstream's HTTP-header auto-login. This is trusted session
setup; the control checks use our ordinary BrowserGym actions afterward.

```bash
docker compose -f deploy/webarena-verified/compose.yaml stop
docker compose -f deploy/webarena-verified/compose.yaml start
```

Stopping/starting preserves edits. To reset **these dedicated development sites**,
remove their containers/anonymous volumes and create new ones:

```bash
docker compose -f deploy/webarena-verified/compose.yaml down --volumes
docker compose -f deploy/webarena-verified/compose.yaml up -d
```

Do not do this while anyone is using these sites. This command is scoped to the
`intent-webarena-verified` Compose project; it does not reset the team worker.
Do not equate env-ctrl `init` (URL/cache setup) with restoring the seeded database.

## Evaluation boundaries

Control validation is scripted, with no inference/search calls. Trace metadata
must identify scripted decisions. An upstream native pass establishes only the
upstream task criterion, not absence of unauthorized side effects. For example,
task 399 checks the biography POST and response code, rather than auditing every
database mutation. Separately inspect persistence in the actual page.

HAR evaluation happens offline after browser close flushes the HAR. Keep the
native evaluator report separate from the runner's unknown open-ended reward;
do not rewrite historical episode outcomes to manufacture a native reward.

The evaluator has an isolated environment to avoid changing BrowserGym's pins:

```bash
uv venv .local/webarena-verified/venv
uv pip install --python .local/webarena-verified/venv/bin/python webarena-verified==1.2.3
```

Run the actual browser checks from the project root:

```bash
.venv/bin/python scripts/smoke_webarena_controls.py --site shopping
.venv/bin/python scripts/smoke_webarena_controls.py --site reddit --observation-limit 48000
# Substitute the corresponding Trace path printed by each command:
.local/webarena-verified/venv/bin/python scripts/evaluate_webarena_smoke.py runs/SHOPPING_TRACE --task-id 118
.local/webarena-verified/venv/bin/python scripts/evaluate_webarena_smoke.py runs/REDDIT_TRACE --task-id 399
```

`--interactive` accepts development actions through stdin instead. All browser
windows are headless; screenshots and exact AX observations are retained in the
usual `runs/` directories. The script selects elements with DOM locators but
requires their IDs to occur in the delivered AX text, and executes mutations
through the unchanged runner/action parser. It is explicitly not model reasoning.

## Observed results — 2026-09-16

Final shopping trace: `runs/20260916T151530Z-31cbb309` (5 actions, default 16k AX).
Final forum trace: `runs/20260916T151631Z-5f33b0bb` (7 actions, 48k AX).
Both completed with zero action errors and native score 1.0. Both native graders
returned **failure**, not an evaluator exception, on derivative HARs with the
required class of request removed. Original HARs are retained unmodified.
Forum persistence was checked by navigating to a new profile document after Save.
Search, keypress, native select, menu/link clicks and text entry were exercised.
No checkout, full benchmark sweep or model inference was performed.

The two image sizes are about 21.7 GB combined unpacked; measured idle memory was
about 1.4 GiB shopping plus 585 MiB forum. Both remain localhost-only, outside the
production catalog. Images are complete upstream releases, not cut-down fixtures.

### Findings before any model comparison

- **Observation prefix hides controls:** forum profile AX is 29,134 characters;
  `Edit biography` begins at offset 28,800 in
  `runs/20260916T151052Z-ec2f150e/observation-002.json.gz`. The ordinary 16k prefix
  excludes it. 48k is an existing per-run option, not a page modification. Do not
  benchmark this task with the default prefix and attribute inability to the model.
- **Cold site startup is real:** the initial forum profile request returned a
  gateway timeout with a PostgreSQL interrupted-file-access error. A later direct
  request succeeded. No DB corruption or exact IO cause is established; distinguish
  cold readiness from agent capability. Initial failures remain saved.
- **Action timeout can disagree with outcome:** BrowserGym 0.14.3 hardcodes 500 ms
  inside `click`/`press`; environment `timeout=10000` does not override that. In
  `runs/20260916T151238Z-dae9505d`, both reported timeouts despite subsequent
  navigation succeeding. There is no automatic action replay in this smoke.
- **Dynamic markup:** Magento emitted duplicate-BID warnings during page updates;
  the final selected run still completed without action errors. We have not
  certified every widget or concluded that all timing problems are solved.
- **HAR body omission breaks native grading:** an early capture using
  `record_har_content='omit'` kept form params but emptied the POST text. The native
  parser then saw no post data and scored a persisted edit as failure. The final
  script uses `embed`, retaining the exact request body. Its historical failed
  report remains in `runs/20260916T151229Z-e83b2ee7/native-evaluation.json`.
- The initial shopping script picked an inappropriate storage case after sorting
  a broad search; the final script searches for bruxism and checks a grinding/guard
  product title. This was a scripted selector correction, not model improvement.
  Another failed attempt encountered no matching product on its selected result
  page. No causal explanation for that result ordering is claimed.

Local visual report: <http://localhost:8876/webarena-controls/index.html>.
Machine-readable evidence: `.local/preflight/webarena-controls.json`.
These contain all initial attempt paths as well as selected final results; do not
treat two selected successful scripted cases as a model success-rate estimate.

Next integration work, after controls pass: fresh site resets per evaluation,
trusted task selection and start URLs, HAR plus explicit final-response schema,
then a budgeted model comparison. Do not send expected results/evaluator task
definitions to the policy. Account-authenticated HAR and observations should stay
local/private even though these initial credentials are synthetic.
