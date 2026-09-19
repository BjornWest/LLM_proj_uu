# Maps preparation v2: independent safety review

**The three prior execution-safety blockers are resolved in the reviewed v2 source.** Eleven offline tests pass (including four bad-plan subcases), with Docker and extraction processes mocked. No downloads, volumes, services or browser/model calls were made.

- Token-scoped volume names and ownership reinspection reject a simulated foreign-volume race before mounting.
- The report is exclusively reserved and fsynced before volume mutation; failure records preserve partial state.
- Held source descriptors, identity checks and actual streamed hashes reject replacement, in-place changes and incorrect transferred bytes.
- Duplicate plans, unsafe source paths and invalid strip counts now fail before Docker commands. Existing/dangling output paths and a held extraction lock also fail safely.

Current header-prefix selection remains supported by `map-preparation-review-v1.json`. This review is not a real extraction, capacity check, or runtime Maps acceptance. The downloader was untouched.

Two nonblocking provenance details remain: hash captured ledger bytes rather than rereading a concurrently updated path, and include imported v1 helper hashes in the final integration closure. This review pins both source files. Neither permits changed streamed data to count as successful extraction under the tested guards.

Exact source hashes and tests: `map-preparation-review-v2.json` and `test_map_preparation_v2.py`.
