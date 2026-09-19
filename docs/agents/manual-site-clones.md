# Disposable WebArena clones for manual browsing

These are the complete cached WebArena Verified shopping and forum applications,
separate from shared benchmark services and expansion evidence clones. Backend
owns exclusive leasing, revocation, release/expiry reset and deployment. Curation
supplies the pinned reset recipe and native saved-write/reset rehearsal.

Both applications use canonical origin `http://172.23.129.52:8896`, the backend's
private lease proxy. This origin is configuration, not a public browsing URL.

| Site | Container | Direct upstream (WSL) | Private env-control port |
|---|---|---|---|
| Shopping | `daylight-manual-shopping-v1` | `http://127.0.0.1:17870` | `127.0.0.1:17871` |
| Forum | `daylight-manual-forum-v1` | `http://127.0.0.1:19170` | `127.0.0.1:19171` |

The browser/control container needs proxy access, not direct clone access or a
Docker socket. App/control ports bind loopback only. There are no data mounts.
Each image contains its own database; no shared persistent account database is
attached. The original shared services on 7770/9999/18999 are outside this recipe.

## Reproducible create and reset

The allowlist, exact image digests **and** expected local image IDs are in
[`clones.py`](../../data/curation/manual_sites/clones.py). Creation uses
`docker run --pull=never`; no download is permitted. Shopping has a 4 GiB memory
limit, forum 2 GiB, each two CPUs and 256 MiB shared memory. The helper retains
exact argv, ID, image, init log and readiness result in a new evidence directory.

From the repository root, for first creation only:

```bash
python3 -m data.curation.manual_sites.clones create --site shopping --output .local/manual-sites/NEW-shopping-create
python3 -m data.curation.manual_sites.clones create --site forum --output .local/manual-sites/NEW-forum-create
```

Initialization is the original image's command, run inside the new container:

```bash
docker exec daylight-manual-shopping-v1 env-ctrl init --base-url http://172.23.129.52:8896
docker exec daylight-manual-forum-v1 env-ctrl init --base-url http://172.23.129.52:8896
```

After **revoking the lease and draining in-flight requests**, the broker obtains
the current exact container ID, then calls the reset helper:

```bash
python3 /home/bjorn/code/LLM_proj_uu/data/curation/manual_sites/clones.py reset \
  --site shopping --expected-id EXACT_CURRENT_CONTAINER_ID \
  --output /home/bjorn/code/LLM_proj_uu/.local/manual-sites/NEW-shopping-reset
```

Use `--site forum` for the second slot. Reset validates the name, pinned image,
owner/site/reset labels, empty mounts, exact loopback port bindings and configured
canonical URL. It deletes **by exact checked ID**, then recreates and initializes
from the cached image. A per-site file lock rejects overlapping helper processes.
Wrong identity or configuration fails closed. Failure is not readiness; the broker
must quarantine the slot. Never substitute selective SQL cleanup for this reset:
manual visitors can change more than the two rehearsed fields.

`--canonical` supports an explicitly configured relocation; it must also match
the existing container's environment before reset. Relocation of an existing
pool needs a coordinated recreation, not silent reconfiguration under a lease.

## Fixture account setup

These are upstream benchmark fixture accounts, not production user identities.
After validating the lease, the backend proxy injects only the appropriate header:

- Shopping: `X-M2-Customer-Auto-Login: emma.lopez@gmail.com:Password.123`
- Forum: `X-Postmill-Auto-Login: MarvelsGrantMan136:test1234`

Preserve the canonical `Host` header while connecting to the loopback upstream;
Magento otherwise redirects back to its configured base URL. Forward cookies and
redirects without replaying POSTs. Shopping must visit authenticated
`/customer/account/` before its first ordinary page, establishing the unmodified
fixture session/form key. Do not inject CSRF values or bypass the original form.
The browser receives a revocable lease credential; administrative broker and
Docker credentials must never enter the browser context or exported evidence.

## Rehearsal and scope

```bash
python3 -m unittest data.curation.manual_sites.test_clones -v
.venv/bin/python -m data.curation.manual_sites.rehearse --site shopping --output .local/manual-sites/NEW-shopping-rehearsal
.venv/bin/python -m data.curation.manual_sites.rehearse --site forum --output .local/manual-sites/NEW-forum-rehearsal
```

Run rehearsals only while owning both clones and before production lifecycle
handoff. Independent sites may run concurrently; each site's saved mutation and
reset are necessarily sequential. The driver uses native Playwright clicks and
fills against the complete applications. Private database reads independently
establish the saved mutation and restored baseline. Shopping adds a wishlist item;
forum edits biography. A short-lived loopback forwarding helper preserves the
canonical browser URL and forwards only to its one clone. It is a test transport,
not an alternate lease service. Screenshots, text, Playwright trace, request
statuses, container IDs and hashes remain under ignored `.local/manual-sites/`.

This establishes a saved native change followed by complete container recreation
for each site. It does **not** establish production proxy revocation, two-user
isolation, deployed UI availability, comprehensive field grading or model ability.
Those remain separate backend acceptance checks. Failed development transport
rehearsals are retained separately rather than overwritten or promoted.

## Recorded acceptance

[`validation.json`](../../data/curation/manual_sites/validation.json) pins the
recipe and the final two passing reports: shopping rehearsal v4 and forum v3.
Both show a native saved change, a new container ID and restored initial value.
Four offline safety tests cover ownership/image/mount/port/origin restrictions.
Backend lifecycle ownership starts at the DATA-EXP-BROWSE-01 handoff; do not run
curation rehearsals on the now-managed slots without coordinating exclusivity.

The final traces retain nonfatal `Cannot set properties of undefined (setting
'register')` page errors. A separate synthetic HTML comparison reproduces that
exact error with Playwright `service_workers='block'` on an insecure HTTP IP
origin; `navigator.serviceWorker` is undefined. The same empty page with `allow`
has no error. Evidence: `.local/manual-sites/service-worker-probe.json`; no clone
requests or changes were needed for this diagnostic. We retain the original
warnings and do not claim error-free browsing or change the production policy.
