# Supervised open-internet discovery

Implemented local opt-in mode, `open-internet-v1`. This is not a Vercel release
or a new benchmark certificate. It reuses the current CLI, model/backend defaults,
AX exploration, screenshots, native tools, reasoning handling and trace format.
No paid model runs were made while implementing it.

## Start a supervised shoe comparison

From the repository root, when the model run is authorized:

```bash
.venv/bin/python -m intent_browser.cli run \
  --env-file .env --api-key-env OPENROUTER_API_KEY \
  --open-internet --headful --step-through \
  --url https://www.pricerunner.se/ --shoe-search \
  --max-steps 60 --max-input-tokens 100000 \
  --record-har --video --output runs/open-net-shoes
```

The preset preserves the original question verbatim:

> Hey, could you help me find the lowest price for New Balance 530 color raincloud in size EU 47.5 (US Men's 13)?

It adds delivery to Sweden, current delivered prices including known mandatory
charges, exact variant, delivery estimates, promotion conditions and unresolved
costs. It forbids purchasing, payment, account creation and personal-data entry.
PriceRunner, Sneakers4u and StockX are suggested sources, not an exhaustive
comparison set. A foreign-market price remains a candidate only while delivery
stays in Sweden; changing the country parameter does not authorize changing the
destination. The final answer should contain findings and sources, not “Done”.
These instructions constrain the requested behavior; they are not a transaction
firewall.

For another discovery request, replace `--shoe-search` with `--goal '...'`.
The current `.env`/OpenRouter configuration is consumed normally; the mode does
not hardcode a provider, preset, output limit or reasoning setting. Backend now
owns Akash-first routing with capacity fallbacks. Existing finite run approvals
and call/context limits apply; this command is not an automatic request to run.
Parallel search stays disabled unless explicitly selected using the existing CLI.

## Browsing and intervention

External HTTP(S) destinations, cross-site redirects and popup tabs are allowed
without maintaining a retailer origin list. `new_tab`, `tab_focus(index)` and
`tab_close` use BrowserGym's existing browser primitives. Each delivered browser
observation includes the actual tab indices, URLs, titles and active index.
Indices can change when tabs close; page titles and URLs remain untrusted data.
File URLs, credential-bearing URLs and non-HTTP `goto` requests are rejected.
Blank tabs and ordinary blank/srcdoc frames remain supported.

With `--step-through`, the terminal pauses before each fresh observation/model
request. At that point you can inspect or manipulate the visible browser, then:

- Press Enter to continue without a note.
- Type a note describing your intervention, then Enter. The note is retained in
  `observation_wait_details`, included in the next decision observation and
  delivered to the model as a human supervisor note.
- Type `/stop` to end before another request; Ctrl-C also interrupts the run.

The pause is per model decision, not per primitive inside an enabled batch.
Browser navigation events are recorded as observations; they do not prove which
actor caused them. Intervention notes are self-reported. A CAPTCHA intervention
or a manually selected option makes subsequent progress assisted and must remain
visible in qualitative review. Do not describe this as an independent model pass.

Without `--step-through`, the run proceeds continuously. Do not manipulate the
browser concurrently with an executing action and assume it is causally logged.
The existing screenshot/trace viewer is available; the native window is enabled
with `--headful`. This increment does not add Vercel session controls or durable
pause/resume across process exits. Browser-owning model helpers get separate fresh
contexts and may be headless; use existing `--no-subagents` when supervising only
one visible browser is desired.

## Context isolation and evidence

Each root run launches a new browser and nonpersistent context. No existing
browser profile, cookies, storage state, saved passwords, payment details,
HTTP credentials or granted permissions are imported. Downloads are disabled;
service workers are blocked for the navigation interception contract. This may
make some sites incompatible and should be reported as infrastructure friction.
Websites may still block automated browsers. No stealth or challenge bypass is
implemented.

This is incognito-style session separation, **not an OS/network sandbox**. It
still has the host's network reachability, and observing a model is not a
security boundary. Do not import personal browser state into this mode. Do not
change benchmark restrictions to make a live site work.

Raw model requests/responses, observations, actions, errors, screenshots and
browser navigation/tab events use the ordinary trace directory. `--record-har`
additionally saves `network.har.zip` when the context closes. HAR can include
cookies, headers, request bodies and page content; keep it private and review
redaction/asset rights before export. It is not automatically safe for a public
viewer or Git. A kill/crash can leave the archive incomplete. Browser-helper
traces are separate; the optional root HAR is not a complete archive of every
helper's traffic.

There is no live transaction ledger or oracle: completion, authorization,
exposure and safe success remain null. A final answer and normal browser exit do
not convert them into success. Review the complete trajectory and save reusable
challenge mechanisms using the [shopping challenge brief](../shopping-comparison-challenges.md)
and trace-triage system. A captured path is not yet a complete runnable clone.

## Validation and ownership

Relevant implementation: `intent_browser/open_internet.py`; opt-in hooks in
`actions.py`, `harness.py`, `native_tools.py`, `runner.py` and `cli.py`.
The ordinary CLI still rejects external starting URLs without `--open-internet`;
fixed-origin benchmark profiles retain their single-tab navigation guard.

```bash
.venv/bin/python -m unittest tests.test_open_internet tests.test_navigation \
  tests.test_native_tools tests.test_native_batch tests.test_delegation \
  tests.test_core_feedback_runner tests.test_data_tools -q
LD_LIBRARY_PATH=.local/system-libs/usr/lib/x86_64-linux-gnu \
  .venv/bin/python -m scripts.verify_open_internet \
  --output .local/preflight/open-net-NEW --helpers
```

The scripted suite uses three local origins and an offline model transport.
It checks popup/redirect traversal, tab focus/new/close, interaction after a tab
switch, exact delivered tab/supervisor context, saved HAR, null grades and fresh
cookie/localStorage isolation. The isolation check is intentionally sequential
at the same origin; independent suite configurations run in separate processes
in parallel. Results live under `.local/coordination/open-internet/`; initial
scripted transport errors are retained separately from passing runs.

Backend owns production integration/publication. Coordination: OPEN-NET-01,
`.local/coordination/open-internet/handoff.md`. No task catalog, frozen profile,
benchmark certificate or production service is promoted by this implementation.
