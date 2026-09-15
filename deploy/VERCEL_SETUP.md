# Deploy the private Daylight team demo

The additional `/harness` page connects to the PC's containerized BrowserGym worker. Follow [TEAM_HARNESS.md](../TEAM_HARNESS.md) for its extra `HARNESS_WORKER_TOKEN` configuration. The browser-side demo described below remains a separate mode at `/`.

This is a Vercel-only version of the Daylight pages and sidebar. Teammates sign in with individual invitation codes, then use the shared OpenRouter key. No local setup, model account or GPU is needed.

The agent operates the fictional page inside the teammate’s browser. **This is a separate demo runtime, not BrowserGym.** Browser-supplied state and action results are explicitly untrusted; all benchmark evaluation fields remain null. The local research harness and historical calibration runs are unchanged.

## 1. Import the repository after this folder is pushed

In [Vercel New Project](https://vercel.com/new), import `BjornWest/LLM_proj_uu` from GitHub.

| Setting | Value |
| --- | --- |
| Project name | `daylight-team-demo` (or your preferred name) |
| Framework preset | Other |
| Root Directory | `deploy/daylight` |
| Include source files outside Root Directory | **Enabled** — the build reuses `environments/demo` |
| Node.js | 24.x |
| Install command | `npm ci` |
| Build command | `npm run build` |
| Output directory | `public` |

`vercel.json` routes application requests through the authenticated function. The `public` directory contains only a non-sensitive `robots.txt`, because Vercel rejects an empty output directory. The application assets are bundled privately into the function. Do not copy the private assets into public or add a static-files bypass for application content.

## 2. Add the server environment variables

Private values have been generated locally in:

- `.local/vercel-demo/vercel-environment.env` — the variables below, including the dedicated demo OpenRouter key.
- `.local/vercel-demo/invitation-codes.json` — three individual codes, labelled `bjorn`, `teammate-1`, `teammate-2`.

Both files are ignored by Git and readable only by your Unix user. Open them locally in your editor; do not paste their contents into chat or commit them.

In the project’s **Settings → Environment Variables**, add these variables to **Production** (and Preview if you intend to use previews):

| Variable | Value / handling |
| --- | --- |
| `OPENROUTER_API_KEY` | Dedicated demo key copied from the generated file. **Sensitive.** This is the value you saved locally as `DAYLIGHT_OPENROUTER_API_KEY`, with its own $5 OpenRouter limit. |
| `DEMO_SESSION_SECRET` | Generated value. **Sensitive.** |
| `DEMO_INVITES_JSON` | Generated JSON mapping IDs to invitation hashes. **Sensitive.** Paste the JSON object as a single value. |
| `MODEL_NAME` | `qwen/qwen3.8-27b` |
| `OPENROUTER_PROVIDERS` | `chutes,dekallm,phala,parasail,akashml,ionstream,cloudflare` |
| `DEMO_DAILY_BUDGET_USD` | `1` initially, shared across the entire deployment’s users |
| `DEMO_DAILY_CALL_LIMIT` | `100` initially, shared across users |

Do not upload your entire repository `.env`. HF, Verda, Parallel and calibration credentials are not needed. No variable uses a public/frontend prefix. Missing access configuration denies all application access.

## 3. Connect private trace storage

From the Vercel project’s **Storage** tab, create/connect a **Vercel Blob** store with **Private** access. Prefer Stockholm (`arn1`) when available. Connect it to the same Production/Preview environments as above.

The connection can provide `BLOB_STORE_ID` with Vercel-managed OIDC authentication, or a `BLOB_READ_WRITE_TOKEN`. The application supports both: an explicit read-write token takes precedence; otherwise the SDK manages OIDC token refresh for the connected store. Keep credentials server-only and Sensitive where the dashboard permits. Every operation uses `access: private`; a public Blob store is not supported. No client-upload token or public trace URL is created.

If your first deployment happened before the store connection or secrets were added, **redeploy** so the function receives them. Neither a local `.env` edit nor adding variables updates already-built deployments automatically.

Hobby Blob storage has an included free allowance; it stops serving if the allowance is exceeded, rather than charging for excess usage. Each model step performs several durable storage writes, so this is for a small team, not large-scale experiments. See [current limits](https://vercel.com/docs/vercel-blob/usage-and-pricing).

## 4. Verify the deployment before sharing

Open the deployment’s production URL in an incognito window:

1. You should see **Daylight · Private demo** with an invitation-code field.
2. `/assets/site.js` should redirect to login; `/api/config` should return 401 while logged out.
3. Sign in using the `bjorn` code. Open Study rooms and ask “When are rooms in Ångström available on Tuesday for 3 people?”
4. In Tasks, run the built-in booking example. Review the reservation and download its activity record.
5. Sign in separately with a teammate code. Its world should be fresh and it must not be able to download your trace URL.

Send each teammate the production URL and **their own code** privately. These are bearer access codes, not verified email identities; anyone given a code can use it. The code is submitted by POST, never in a URL. Sessions expire after seven days.

You may retain Vercel’s default Preview protection, but it is not the privacy boundary for this application. Hobby’s production URL can be reachable publicly while the application content, inference API and traces remain behind our login. Do not rely on the GitHub repository’s private visibility to protect the website.

To revoke an invitation, remove its entry from `DEMO_INVITES_JSON` and redeploy. Existing sessions for that entry fail verification on the new deployment. Old deployments retain their old environment: delete obsolete deployments or protect their URLs too when revoking access. Rotate `DEMO_SESSION_SECRET` and redeploy to invalidate every session on the new deployment.

## Troubleshooting after login

If the invitation is accepted but `/` fails, this page load does not use OpenRouter or Blob. The handler resolves its private assets relative to its module, independent of the function working directory. Open the **latest deployment** after an update; a deployment-specific URL remains pinned to its old build.

Unexpected failures return a safe diagnostic code and a matching entry in Vercel Runtime Logs:

- `PRIVATE_ASSETS_UNAVAILABLE`: missing/unreadable built assets or provenance. Confirm the build ran and `private-assets/**` is included in the function. Never move those files into `public`.
- `ACCESS_CONFIGURATION`: check the invitation JSON and session secret in this deployment’s environment.
- `AGENT_STORAGE_UNAVAILABLE`: an unexpected agent/API operation failed. Open **project → Logs (Runtime Logs)**, not Build Logs, and reproduce it. The matching `daylight_request_failed` entry records the API operation.
- `BLOB_TOKEN_MISSING`: this deployment has no usable Blob configuration. Check `BLOB_READ_WRITE_TOKEN`, or the connected store’s `BLOB_STORE_ID` and Vercel-managed OIDC configuration.
- `BLOB_ACCESS_DENIED`, `BLOB_OIDC_ENVIRONMENT_DENIED`, or `BLOB_ACCESS_MODE_MISMATCH`: check the intended store, its Private access, and its project connection’s Production/Preview selection.
- `BLOB_WRITE_CONFLICT`, `BLOB_RATE_LIMITED`, or `BLOB_SERVICE_UNAVAILABLE`: a conditional write conflict or storage service issue. No automatic application retry is added.
- `BLOB_OPERATION_FAILED`: an unclassified storage error. The log identifies read/write and API start/step/event without exposing arbitrary SDK error messages.

For a repeatable conflict during a single-user run, sign in and open `/storage-check`, then click **Run storage check**. It creates one isolated `daylight/diagnostics/<owner>/<id>.json` object with a trace-sized payload (over 16 KB) and tests create → read → conditional write using the read ETag → conditional write using the put ETag → read. The report contains only stage names, equality/format flags and ETag hashes. It performs no model calls, touches no trace/budget objects, and does not remove concurrency checks or retry failed writes. A failed check is diagnostic evidence, not a repair. The original small-object check passed on the user’s deployment; that did not test representation changes that may occur for larger responses.

Blob reads request `Accept-Encoding: identity` so compression does not replace the stored object’s ETag with a representation validator. ETags are passed through unchanged, and `ifMatch` is still required for overwrites. An offline test runs the actual Blob SDK GET against an intercepted HTTP transport: a compressed large response with a weak ETag reproduces the conflict, while identity encoding lets the same simulated agent finish and persist its request/result/budget. This is a regression test for that mechanism, not proof that the production failure had the same cause.

An empty store is expected before the first successful `/api/start`: the app creates `daylight/traces/...` on demand, then `daylight/budgets/...` before inference. A dashboard sample such as “hello world” is not app data and does not prove the deployment can write. After connecting storage, **redeploy and open the new deployment**; an older deployment URL retains its earlier environment.

Logs contain only fixed stage/code/operation labels and a missing-file flag, not credentials or request bodies. Explicit application errors, such as a budget limit or invalid action, retain their own messages.

## Usage and trace behavior

- One model routing `session_id` per task/chat trace, all seven allowed providers, no preset or provider order, no automatic inference retry.
- Up to 12 calls per task, 512 output tokens each. Chat uses one call. A room task ends after the first accepted reservation, including a wrong reservation; this is an environment boundary, not proof the model learned when to stop.
- The daily budget uses conservative reservations against provider price caps. Failed or unknown-cost calls retain their reservation. Conditional storage writes prevent concurrent requests from silently overspending that ledger or sending the same step twice. A conflict stops the request; it does not silently retry inference.
- The $1 app allowance resets at UTC midnight. It is separate from the dedicated key’s $5 OpenRouter limit and from every calibration budget. It does not measure Vercel infrastructure charges.
- Model request bodies, raw response text/JSON, HTTP errors, usage, requested/resolved provider, cache counters and timestamps are persisted privately. A pending attempt after infrastructure interruption means the outcome is unknown.
- The browser sends visible page text and control metadata; actions use a small JSON action language. No arbitrary JavaScript execution or external URL navigation is available to the model. Chat cannot execute actions.
- Private downloads are JSON, owned by the signed-in invitation. The owner can inspect all stored traces via the Vercel Blob dashboard. There is no shared cloud trace-browser UI yet.
- Page state is per tab, in memory. Refresh or Start fresh resets it. Stored traces survive. Keep the tab open while a task runs; closing it may leave an awaiting-client/pending trace, which is not marked successful.
- Page freshness is checked again before execution. A disappearing control stops the task with a recorded error rather than clicking stale state. No silent retry or replacement observation.
- No screenshots/video or privileged verifier in this version. The existing local BrowserGym workflow remains available for those.

## Local development

From the repository root:

```bash
cd deploy/daylight
npm ci
npm run build
npm test
node --env-file=../../.local/vercel-demo/vercel-environment.env dev.mjs
```

Open `http://localhost:8880`. The development server binds to loopback and stores traces in ignored `.dev-data/`; Vercel uses private Blob instead.

Offline browser validation, from the repository root:

```bash
.venv/bin/python scripts/smoke_vercel_demo.py
```

It runs a scripted fake model on port 8881, exercises all three pages, read-only chat, stale-control rejection and private trace downloads. It makes no inference calls. Requires the existing local Playwright/Chromium installation.

To generate a fresh access configuration on a new workstation:

```bash
cd deploy/daylight
node scripts/create_invites.mjs bjorn teammate-1 teammate-2
```

It never overwrites existing files. The separate generated `access.env` contains the session secret and invitation hashes; add the dedicated inference settings when preparing your own environment file.

## Path to a team interface for the real harness

Keep Vercel as the entry point for login, run forms, status and trace review. Add an authenticated job service and persistent Python/Chromium worker that calls the existing `run_episode` implementation. The worker would own browser observations and actions, task lifecycle and independent terminal evaluation; private object storage would hold the original harness artifacts. Vercel functions should submit/poll jobs rather than hold a browser alive between requests.

The browser-side driver in this prototype would then become an explicitly labelled demo mode alongside the worker-backed BrowserGym mode. Do not translate the demo’s client-supplied outcomes into benchmark labels. Multi-user worker isolation, queueing and cross-runtime trace viewing will be separate, reviewed increments.

## References

- [Vercel project configuration](https://vercel.com/docs/project-configuration/vercel-json)
- [Deployment protection](https://vercel.com/docs/deployment-protection)
- [External access limits](https://vercel.com/docs/deployment-protection/methods-to-protect-deployments/vercel-authentication)
- [Sensitive environment variables](https://vercel.com/docs/environment-variables/sensitive-environment-variables)
- [Private Blob storage](https://vercel.com/docs/vercel-blob/private-storage)
- [OpenRouter API-key spending limits](https://openrouter.ai/docs/api/api-reference/api-keys/create-keys)
