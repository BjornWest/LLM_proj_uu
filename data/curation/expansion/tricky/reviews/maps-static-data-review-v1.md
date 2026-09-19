# Maps static geocoding: independent cached-image review

**Source-level answer: yes, conditionally.** The pinned Nominatim 4.2.4 implementation can serve forward and reverse geocoding from its imported PostgreSQL data without the external flatnode update cache. This review did not restore an archive, launch a service, download data or promote Maps readiness.

The cached image was copied from an unstarted container, then the container was removed. Its digest is `am1n3e/webarena-verified-map@sha256:c769aa312c979d68e696dace7049d58eeeb016ce608f0f8779a181bf3714206f`. Machine-readable evidence and selected hashed source excerpts are in `maps-static-data-review-v1.json` and `maps-static-data-review-v1.source.json`; the larger raw extraction remains under `.local/curation-expansion/tricky/`.

## Why this is feasible

- Nominatim's `clicmd/freeze.py:20–41` explicitly describes keeping geocoding data while dropping update-only data, then calls the flatnode deletion routine. This directly establishes that the cache is unnecessary for static queries.
- `website/search.php` and `website/reverse.php` construct PostgreSQL-backed query objects. `DB.php` uses PDO; reverse queries use `placex` and geometry tables. No flatnode reference appeared in the 59 PHP files inspected. The positive source evidence is stronger than that absence scan.
- `/entrypoint.sh:175–216` requires the PostgreSQL cluster but handles the flatnode directory only if present. It refreshes website/functions; the inspected supervisor configuration contains no Nominatim replication/import worker.

**Do not run `freeze` merely to omit this file.** It also drops tables with CASCADE, changing the upstream database. Preserve the original archive and restore its PostgreSQL portion into a disposable writable runtime copy. Startup and function refresh can change that copy; “exact upstream archive” is provenance, not a claim that a running database stays byte-identical.

## Conditions and limits

- This is static code evidence, not a restored PostgreSQL archive or live geocoding validation. Archive completeness, database compatibility, indexes and task-specific coverage remain unverified.
- Preserve exact upstream PostgreSQL archive as the input. Do not run freeze: it drops update tables with CASCADE and changes the database. A running PostgreSQL copy is writable, and entrypoint refresh updates functions/project output; do not promise byte-identical runtime database files.
- Retain full database schema/query data, PostgreSQL 14 and compatible extensions, packaged PHP/Python and ICU tokenizer/project resources. Search becomes reverse-only when search_name is absent.
- No import/replication/update operation may assume an omitted flatnode file. Empty base .env is not sufficient if project or OS environment overrides it; inspect effective configuration before launch.
- Flatnode omission does not replace tiles, car/bike/foot routing, Rails website data or map UI assets. Full-site acceptance must test these independently.
- Existing volume setup script unconditionally extracts both database and flatnode trees from one archive. Omitting the flatnode extraction alone does not prove a download reduction; archive layout/transport must be handled separately.
- Startup refresh failure is only a warning. Require positive search/reverse/API and browser task checks, not just a healthy container process.

The next acceptance gate should record effective configuration, verify forward/structured/reverse/OSM-ID queries on the restored database, then exercise full-site search, results, routing and tiles through browser tasks. This code review supports that experiment; it does not substitute for it.

## Separate documentation correction

`authored03/README.md` now gives explicit commands for the 16 retained v1 non-draft tasks and four strict-draft v2 tasks. The older full cohort and v1 source remain historical and untouched.
