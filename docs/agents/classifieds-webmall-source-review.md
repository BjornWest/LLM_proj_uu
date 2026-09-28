# Classifieds and multi-shop source review

Read-only research, 2026-09-20. No deployment, browser/model calls, container pulls,
or full site-backup downloads. Small task/source files, HTTP HEAD checks, ZIP
range inspection and Docker manifest/config inspection only. Not readiness evidence.

## VisualWebArena

Inspected repository revision: `89f5af29305c3d1e9f97ce4421462060a70c9a03`.
[Setup](https://github.com/web-arena-x/visualwebarena/blob/89f5af29305c3d1e9f97ce4421462060a70c9a03/environment_docker/README.md)
provides self-hosted environments, not a remote proprietary instance dependency.
Shopping uses the original WebArena Magento/OneStopShop environment; it should
not count as a new storefront family for this project. Matching our exact current
fixture to visual tasks/images remains a validation step.

Direct JSON inventory: classifieds234 tasks/75 distinct intent_template_id values;
shopping466/152. Template IDs are upstream labels, not verified independent skills.
Classifieds68 tasks and shopping169 include an explicit input image. Other tasks
can still require viewing website images. No text-only feasibility inferred.

[Classifieds tasks](https://github.com/web-arena-x/visualwebarena/blob/89f5af29305c3d1e9f97ce4421462060a70c9a03/config_files/vwa/test_classifieds.raw.json):
0 cheapest blue kayak;4 edit own car's price in field and description;5 delete own
car listing;8 create an image-based listing priced below a comparable offer;
38 report mileage for recent silver/grey sedans;57 post specified inquiries on
matching bicycles;209 compare bulk pallet pricing. These span retrieval, visual
identification, calculations and persistent account/listing changes.

[Shopping tasks](https://github.com/web-arena-x/visualwebarena/blob/89f5af29305c3d1e9f97ce4421462060a70c9a03/config_files/vwa/test_shopping.raw.json):
0 buy cheapest red blanket;38 wishlist pink products;152 locate prior order from
an image;190 compare expensive white projectors;304 read per-serving calories;
342 buy a motherboard with the socket shown in a reference image.

Native evaluators mix URL, answer, HTML predicates and image queries. Classifieds
5 checks deletion through page text containing404; this alone does not establish
that only the authorized listing was removed. New derivatives need scoped state
checks and unknown labels for uncovered effects. Keep visual scoring dependence
separate from deterministic outcome facts.

### Where the application lives

The Internet Archive classifieds ZIP is25,366,023 bytes. Its central directory
contains six entries: directories, Compose, database dump/reset SQL and init shell.
It contains NO application PHP. Compose references `jykoh/classifieds:latest`
and MySQL8.1. The published image manifest was reachable:
`sha256:a2a794da92f62a8d7ffd02314e4fab40ba6c7fc08f568371608f88f0ef605e43`.
Layer sizes sum76,861,304,894 bytes (~76.9GB decimal compressed), excluding database
image and unpacked space. Build history copies `osclass-v8.1.2` into `/usr/src/myapp`
and starts PHP's web server. This supports packaged PHP source availability, but
we have NOT extracted the image or verified every custom source/assets file.
No standalone reproducible build source for that custom image was established.
The benchmark repository MIT license is not blanket permission for every bundled
image/photo/theme. Inspect component notices when materializing the environment.

## WebMall

Inspected repository revision: `2697d35cdfcfedcf1ade89b7ad86722db8daa8a7`.
[Task examples](https://github.com/wbsg-uni-mannheim/WebMall/blob/2697d35cdfcfedcf1ade89b7ad86722db8daa8a7/examples/task_strings.txt)
include cross-shop exact-model search, cheapest offers including ties, compatible
accessories/components, feature/price constraints, vague suitability, carts and
checkout. Four WooCommerce shops,91 benchmark tasks. Examples include lowest-price
Bose headphones, cheapest Samsung870Evo offer per capacity, and compatible watch
straps. Prefer explicit constraints before subjective style/suitability contracts.

[Restore script](https://github.com/wbsg-uni-mannheim/WebMall/blob/2697d35cdfcfedcf1ade89b7ad86722db8daa8a7/docker_all/restore_all_and_deploy_local.sh)
uses four WordPress-volume and four MariaDB-volume backups from the university
server. All eight HEAD requests returned200; advertised lengths total3,630,464,328
bytes (~3.63GB compressed), excluding runtime images/unpacking. Backups not fetched;
HEAD does not validate archive contents/integrity or successful restoration.
Repo includes Compose/config/scripts and product CSVs; the installed website
files/themes/data are distributed through those backups. No top-level license
was found in this repository's inspected tree/API metadata; reuse terms need closure.

Compose uses mutable latest WordPress/MariaDB tags, so a reproducible integration
must choose and test compatible pinned images. Do not replace our existing
BrowserGym with its fork: inspect/port the task boundary in isolation. The upstream
fork's current evaluator inspected separately uses expected offer URLs/checkpoints
and cart/checkout HTML; that is not an independently audited transaction ledger.

## Recommended next increment

Prioritize classifieds for a new consumer context and WebMall for cross-retailer
shopping. Site availability/fidelity/reset first; then a small explicit-task pilot.
No100-task target or assumed inherited readiness. Old products do not prevent
useful browser tests; newer/custom goals should have distinct contracts and grounded
answers. Keep complete surrounding sites. Shared product additions and an original
aggregator are later derived environments, not original benchmark task results.

Raw research evidence (ignored): `.local/curation-research/vwa-webmall/`, including
JSON task inventories, ZIP index/Compose and Docker manifest/build history. No
secrets or downloaded full website images are required to reproduce this note.
