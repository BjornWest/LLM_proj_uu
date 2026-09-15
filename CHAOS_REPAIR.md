# Versioned Chaos event and generator repairs

The repaired local build fixes two upstream fixture defects: a blur request could swallow the following Save click, and imprecise integer arithmetic collapsed seeded task variation. The original npm package and historical episodes remain unchanged. These are environment repairs with scripted evidence, not improved model scores.

The active repaired build is `0.1.0-intent.fifo2.xor32`, under `.local/chaos-fifo-xor32-v2`. Its local agent origin is recorded in that directory's `server.json`. The build starts with a separate `XDG_STATE_HOME`, so its sessions do not share the original server's persisted state. Never edit a running build; choose a new output directory for a new version.

## Event delivery

`environments/chaos/stage-queue.mjs` serializes the original UI events. It captures values at emission, dispatches each event once, and keeps input-before-click ordering. It does not synthesize, replay or retry a click. A terminal response closes the queue before a pending duplicate can dispatch. Request failures and unmount discard pending events; an already dispatched request cannot be undone.

Callback errors are contained separately from transport failures, including rejected async callbacks. A successful response is never relabeled a failed HTTP request because a callback throws. The first close reason is retained. Privileged diagnostic snapshots include session, challenge, mount nonce and unmount time; these are not DOM content or policy observations.

Eight queue unit tests cover ordering, payload capture, duplicate prevention, unmount, request failure and callback failures. Eight fresh BrowserGym cases cover native direct fill/save, deliberately delayed input, readonly-field blur and failed input, each twice. Five additional native browser cases cover multiple edits without coalescing, a double-click queued behind a held terminal response, SPA unmount with pending Save, network failure and a successful separate session afterward. Held responses are forwarded once and released unchanged; this instrumentation is logged separately from policy actions.

The failure and unmount cases pass their diagnostic expectations while task success stays unknown. They are not successful task episodes. The ordinary 16-case verifier suite separately preserves positive and negative contract outcomes for all seven supported task families.

## Seeded variation

The original `Number` multiplication overflows exact integer precision before masking. Merely replacing it with `Math.imul` fixes arithmetic but retains low-bit correlations under the factory's modulo choices; independent review found two missing combinations of target-row and safe-action position.

This derived build explicitly switches to noncryptographic xorshift32 `(13,17,5)`, retaining the original zero-seed fallback to one. See [Marsaglia's original algorithm paper](https://www.jstatsoft.org/article/view/v008i14). The repair has a different generator identity and changes seed-to-task mappings. Historical sessions must continue to use their original bundle/descriptor.

The local arithmetic check compares 32,768 outputs with an independent BigInt implementation. Separate curation review checked 65,920 outputs including unsigned boundary cases, and all six target-row/action-position combinations occurred in its 1,024-token-task sample. A later independent audit also checked 10,240 generated instances across five families and two seed corpora, covering every declared row/action or safe/dangerous-button position combination. See `data/curation/CHAOS_GENERATOR_CHOICE.md`. This rejects the observed collapse; it is not a statistical certification, cryptographic guarantee, proof of uniformity or coverage of every future task factory. Modulo sampling and the original shuffle remain unchanged.

## Reproduce

Use a cached exact `browser-agent-chaos@0.1.0` installation. If necessary, first install/start that pinned package using the existing laptop guide. Setup checks the original CLI and frontend hashes and reuses cached Node dependencies; it downloads nothing.

```bash
python3 scripts/setup_chaos_repair.py \
  --source /absolute/path/to/node_modules/browser-agent-chaos \
  --output .local/chaos-fifo-xor32-v2 --rng xorshift32-v1
python3 scripts/start_chaos_repair.py --build .local/chaos-fifo-xor32-v2 --human-port 3145
node --test environments/chaos/test-stage-queue.mjs
# Substitute the agent port printed by the launcher:
.venv/bin/python -m scripts.verify_chaos --base-url http://localhost:AGENT_PORT --fresh-observation
.venv/bin/python -m scripts.verify_chaos_queue --base-url http://localhost:AGENT_PORT --report .local/preflight/queue-new.json
.venv/bin/python -m scripts.verify_chaos_queue_boundaries --base-url http://localhost:AGENT_PORT --report .local/preflight/boundaries-new.json
node scripts/verify_chaos_rng.mjs /absolute/path/to/original/dist/cli.mjs .local/chaos-fifo-xor32-v2/dist/cli.mjs .local/preflight/rng-new.json
```

`setup_chaos_repair.py` refuses to overwrite an existing output. The launcher waits beyond the last build-file write before starting: the conservative Linux process-start check uses integer boot time and could otherwise reject a same-second build/start. It does not weaken the provenance gate.

After reviewing all 16 fresh contract cases, write a separate candidate certificate:

```bash
.venv/bin/python -m scripts.certify_chaos runs/EPISODE/chaos-preflight-suite.json \
  --output .local/preflight/chaos-repaired-validation.json \
  --certificate-output config/chaos_fifo_xor32_v2.json
```

Only `config/chaos_verifier.json` is the active normal-runtime gate. It now matches the reviewed v2 build; the previous original-build certificate is retained at `config/chaos_original_f0e4ff0.json`. A separate candidate file alone does not enable grading. Old frozen model profiles will fail their old config hash check and must not be silently resumed against this environment. Build paths and recorded repair metadata vary across machines, so a laptop must generate its own evidence/certificate rather than assume this workstation's hashes apply. The certificate validates local scoped contracts only; it does not enable training or authorize paid calls.

## Evidence and retained development failures

- Full current-runtime contract suite: `runs/20260915T003310Z-9192d012/chaos-preflight-suite.json`.
- Independent replay: `.local/preflight/chaos-fifo-xor32-v2-validation.json` and `config/chaos_fifo_xor32_v2.json`.
- Eight interaction cases: `.local/preflight/chaos-fifo-xor32-v2-queue.json`.
- Five native boundary cases: `.local/preflight/chaos-queue-boundaries-v2-second.json`.
- Arithmetic/factory sample: `.local/preflight/chaos-fifo-xor32-v2-rng.json`.
- Independent reviews: `data/curation/CHAOS_REPAIR_ACCEPTANCE.md` and its referenced artifacts.

Earlier failed diagnostic runs remain retained: interception installed before reset, an assertion that incorrectly expected a determinate result after transport failure, an unsupported Playwright `max_retries` parameter, and the conservative same-second process-start rejection. They are excluded from passing suites. One initial FIFO development launch read the default upstream state before any test interaction; it was stopped and relaunched with isolated state. All reported repair suites use isolated storage.

These changes leave model behavior, model history/context strategy, upstream scoring formulas and original task goals untouched. Queue repair does not explain every duplicate action in W01, and no model rerun has been used to claim that it does.
