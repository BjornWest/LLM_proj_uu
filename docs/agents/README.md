# Agent-facing documentation

- [Natural-answer extraction and oracle grading](natural-answer-extraction.md): Qwen structured claims, grounded citations, frozen-world grading and offline replay.

- [Opaque reasoning input sizing](opaque-reasoning-input-sizing.md): preserved Gemini reasoning/signature blocks, usage-backed next-input estimates and limitations.

- [Shopping interaction patterns](shopping-interaction-patterns.md): sampled AX search ambiguity, disclosures, destination forms and outcome-preserving acceptance.
- [Retailer home merchandising](retailer-merchandising.md): typed collections, sampled home sections, compact customer information and page acceptance.

- [Decision correction chains](decision-correction-chains.md): opt-in per-failure recovery and explicit scroll-axis defaults.

- [Public page data and isolated Python](page-data-and-python.md): extraction/script tools, local sandbox setup, limits and offline validation.

Put new technical handoffs, implementation notes, detailed setup/runbooks,
audits and development-status writeups here. Write for the next coding agent:
state the scope, relevant files, verified evidence and remaining work.

For the human overview, start with the [project README](../../README.md).
The [repository guidance](../../AGENTS.md) describes the documentation policy.

## Existing references

- [Episode capacity controller](episode-capacity-control.md): shared vLLM telemetry and turn-boundary parking; CPU-only qualification, prospective suite/RL caller integration.

- [Product-review evidence and templates](product-review-evidence.md): exact-SKU opinion generation, reusable prose, request/memory criteria, count grading and frozen-corpus binding.

- [Four comparison layouts and partial coverage](comparison-coverage-and-layouts.md): independent base designs, filter capabilities, sampled membership and retailer-only discovery.

- [Comparison-site designs](comparison-site-designs.md): model-level footwear listings, reference AX captures and reusable directory/specialist previews.

- [Connected shopping world](connected-shopping-world.md): pinned multi-site composition, public index, review generation and local browser acceptance.

- [Product-review family audit](product-review-family-audit.md): category-aware language, multiselect/range filters and live AX-scale comparison.
- [Generated product-review sites](product-review-sites.md): three AX structures, six product families, world-derived facts, synthetic reader opinions and proposed variation controls.

- [Product locations and merchant profiles](product-location-system.md): offline Western Europe sampling, physical branches, geographic delivery/pickup quotes and correlated retailer sizes; local authoring only.
- [Footwear assortment depth](footwear-depth-generation.md): opt-in model density, coherent shoe types, shared store listings and independent stock, prices and review coverage.
- [Retail interaction sampling](retail-interaction-sampling.md): opt-in search/disclosure obstacles, correlated site profiles and a frozen destination-postcode alias.
- [Shopping advertisements](shopping-advertising.md): configurable contextual ad sampling, canonical retailer targets and explicit sponsored-placement boundaries.
- [Three-world breadth audit](world-breadth-audit.md): fixed-seed data checks, retained no-match outcomes and current sampling limits.
- [World task coverage and next work](world-task-coverage.md): pickup/inspection, travel, retailer reviews, unit-price and cookie-memory sampling, deterministic reference checks and remaining integration boundaries.
- [Synthetic travel planner](synthetic-travel-planner.md): separate browser site for place search, walking/driving estimates and branch comparisons using cached geographic data.


- [Incremental AX context](incremental-ax-context.md): shared verbose/repeat controls, acknowledged visits, short stable refs and region deltas; local v7 profile.
- [Progressive AX exploration](progressive-ax.md): token-bounded overview, scoped search, location breadcrumbs and snapshot-bound traversal; local scripted validation.
- [Dataset production protocol](dataset-production-protocol.md): model tiers, temporary workers, reusable validation, escalation and batch work packets.
- [General-browsing dataset expansion](dataset-expansion.md): WebArena/Tricky ownership, task acceptance, site diversity, resource allowance and current evidence.
- [Saved-trace failure triage](failure-triage.md): deterministic pointers, trajectory neighborhoods, successful comparisons and evidence-bound reviewer annotations; local/offline only.
- [Codex trace-triage skill](trace-triage-skill.md): compact cohort queries, focused comparisons and reusable reviews through `$browser-trace-triage`.

- [WebArena-Verified local sites](webarena-verified.md): pinned complete shopping/forum containers, BrowserGym control smoke and separate native evaluation.
- [Independent startup and trace pagination](history-loading.md): local summary projection, lazy history and release evidence.
- [Screenshot storage](screenshot-storage.md): implemented exact-byte deduplication, reference counts, hourly usage monitoring and a 20 GB review threshold; no automatic deletion.
- [Future retention considerations](trace-retention-proposal.md): deferred rarity/coverage selection and protected evidence.

- [Stable PC backend address](tailscale-backend.md): Tailscale Funnel, persistent device identity, restart and Vercel cutover checks.

- [Shared browser Ask](shared-browser-ask.md): same-session human/agent handover, interruption, ungraded requests and trace evidence.

- [Complete hosted sites](full-site-restoration.md): full-source restoration, shared native/client versions, known upstream gaps and validation.

- [Generalization requirements](generalization-requirements.md): interface fidelity, site holdouts, messy observations and eventual real-site transfer.
- [Manual environment hosting](manual-environment-hosting.md): owner-scoped native browser controls, package boundaries and trace semantics.
- [Manual session recovery](manual-session-recovery.md): closed screenshots, status refresh, other-session controls and health route boundaries.
- [Client-rendered inspection feasibility](client-rendered-environment-feasibility.md): ordinary browser probes, per-site effort and hosting options; not a deployed capability.
- [Portable control service](../../deploy/control/README.md): SQLite, private tunnel, Blob migration and single-writer cutover.
- [Completed control-storage cutover](control-storage-cutover.md): exact migration evidence, production checks and current restart limitations.
- [Agent coordination](coordination.md): sparse notifications, delivery semantics, and current steering test status.
- [Observation text limits](observation-text-limit.md): optional larger AX prefixes, metadata, and WorkArena saved-evidence checks.
- [Previous technical README](legacy-readme.md): a historical copy retained when the root README was rewritten for the group. Its older status notes are not current instructions.
- [Team harness](../../TEAM_HARNESS.md) and [hosted worker extension](../../HOSTED_WORKER.md).
- [Vercel setup](../../deploy/VERCEL_SETUP.md) and [worker setup](../../deploy/worker/README.md).
- [Local installation and MiniWoB setup](../../LAPTOP_SETUP.md).
- [Hosted archive/error-boundary acceptance follow-up](hosted-acceptance-followup.md).
- [Daylight action-response format correction](daylight-action-format.md).
- [Dataset curation](../../data/curation/README.md).
- [Training validation and remote deployment](training-modal-preflight.md): bounded SFT/RL learning evidence, compatibility fixes and SSH reproduction commands. Start with the [consolidated findings](../training-findings.md) for the project overview.

Existing documents remain at their original paths while other agents are
working. Update them there when needed; do not move them or create parallel
maintained copies as part of this transition.

- [Browser navigation and proposed helper agents](browser-navigation-and-subagents.md): opt-in Back/Forward/Reload/URL controls, tested boundaries, and a helper-agent design for discussion.

- [Navigation timeout feedback and Books rerun](navigation-timeout-feedback.md): ambiguous effects, scripted checks and recorded model recovery.

- [On-demand screenshots and image retention](on-demand-vision.md): opt-in positioning, native image tool results, explicit release, and offline acceptance.

- [AX revisits and overview control](ax-reuse-and-overview-control.md): exact public-tree reuse, current handles and per-action automatic AX token budgets.


- [Generated-world browser performance](generated-browser-performance.md): frozen-source capture profiling, concurrent episode costs, current RL integration gaps and the BrowserGym/Playwright boundary.

- [Lazy observation experiment](lazy-observation-experiment.md): isolated partial-AX prototype, target freshness and feedback checks, measured speed, explicit search/frame fallbacks and adoption gaps.

- [Product-review reference structures](product-review-structure.md): denser AX layouts, functional archives and unresolved world contracts.

- [Review-site cookie popups](review-cookie-popups.md): independently sampled banner/modal/drawer, persisted choices and private diagnostics.

- [Background AX prefetch](background-ax-prefetch-experiment.md): shallow-first observations, browser-owner worker, measured overlap with simulated inference, snapshot guards and adoption limits.

- [Event-driven readiness](event-driven-readiness.md): opt-in public-condition and application-lifecycle waits, fixed-delay comparisons, timeout semantics and integration boundaries.

- [Qwen readiness comparison](readiness-llm-comparison.md): four real model episodes, exact busy-state/wait evidence, reported costs and the separate final-response protocol error.

- [Observation consistency and visual readiness](observation-consistency-and-visual-readiness.md): strict foreground AX comparison, stale-cache boundaries and scripted screenshot readiness checks.
- [Integrated observation pipeline](integrated-observation-pipeline.md): opt-in readiness, navigation, background AX and screenshots on generated storefronts; scoped cache qualification, foreground parity and new timing evidence.
- [Assisted trajectory repair](assisted-trajectory-repair.md): proposed restart, hint/manual-action and separate SFT-export workflow; not implemented.

- [Frozen product-review page binding](product-review-page-binding.md): public corpus, source links, discovery and task-boundary acceptance.

- [Connected-world conformance suite](connected-world-conformance.md): generated facts versus rendered pages, quotes, comparisons and reviews.

- [Teacher evaluation task ladder](../teacher-evaluation-task-ladder.md): 20 proposed cases, difficulty tiers and current grader gaps.

- [Connected-world Qwen host](connected-world-qwen-host.md): manual task/memory delivery, clarification, private fact attachments and scripted host readiness.

- [Opt-in user clarification](user-clarification.md): trusted replies within the same episode, batch boundaries and exact delivery evidence.

- [BrowserGym observation integration](browsergym-observation-integration.md): opt-in shallow/background capture, native BID compatibility, conservative full-capture mode and scripted acceptance.

- [Human tab handover controller and local panel](human-tab-handover.md)

- [Human tab handover](human-tab-handover.md): opt-in local human/agent tab custody, native capture, concurrency guards and validation.

- [Human controls inside BrowserGym chat](human-handover-chat-ui.md)

- [Three-world breadth audit](world-breadth-audit.md): fixed samples, renderer fixes, native journeys and remaining difficulty limits.

- [Synthetic comparator verification gates](synthetic-verification-gates.md): seeded offline gates, trusted user completion, browser/session acceptance; no Cloudflare or user-LLM integration claim.

- [Physical branch assortment tasks](branch-assortment-tasks.md): distinct matching models, local stock, per-pair price ranges and manual reference counts.
- [Product stock and account generation](product-location-accounts-generation.md): branch dispatch, retailer exclusions, coupon sampling and historical tracking/cancellation tasks.
- [Connected retailer stock and accounts](connected-location-accounts.md): branch-stock disclosure, account/coupon/order pages, cancellation boundaries and local validation.

- [Windows browser windows and layout](windows-browser-layout.md): close unused startup pages and place website/chat side by side on a selected display.

- [Open-web capture efficiency](open-web-capture-efficiency.md): verified capture counts, immutable-calculation guard fix and current overlap limitations.

- [Isolated dynamic-page overlap prototype](open-web-overlap-prototype.md): historical isolated concurrency, invalidation tests and loaded-page timing.

- [Opt-in open-web background capture](open-web-background-capture.md): runner integration, backend capability gates, exact policy provenance and adoption limits.

- [Completion and final-message limits](completion-output-limits.md): token ceilings, native answer bounds, evidence-only truncation classification and rollout boundary.

- [Iframe-owner navigation recovery](frame-owner-navigation-recovery.md): post-action document races, observation-only retry, transport-error boundaries and local acceptance.

- [Capture fetching CPU profile](capture-fetch-cpu-profile.md): measured Python conversion and recording costs, isolated parallel-fetch comparisons, and preload priorities.

- [Automatic screenshot configuration](automatic-screenshot-config.md): disable observation screenshot capture with a CLI/Python switch while preserving explicit vision tools and separate video settings.

- [External Codex model bridge](external-agent-bridge.md): use the unchanged harness through a local Pi/Codex model endpoint; exact policy mapping, offline acceptance and subscription-use limits.

- [Background observation recording](background-observation-recording.md): ordered bounded writer, immutable snapshots and live capture-overlap measurements.

- [AX search readiness profile](ax-search-readiness-profile.md): capture dependencies, live/synthetic measurements and index preparation scheduling.

- [Actionable preview BIDs](actionable-preview-bids.md): bounded viewport ID assignment, reuse and validation; browser tests and latency.
- [Combined Gemini capture benchmark](gemini-combined-capture-benchmark.md): live preview-click acceptance, schema compatibility limitation, overlapping and serial timings.
- [Longer Gemini real-web benchmark](gemini-real-web-capture-benchmark.md): 80-turn retail run, capture overlap, recoverable tool failures and remaining serial latency.
- [Targeted action capture](targeted-action-capture.md): opt-in element checks and deferred final-action observations, with offline browser acceptance and capture-cost comparison.
- [Gemini targeted-capture trial](gemini-targeted-capture-benchmark.md): 16-response live evidence, exclusive wall-time breakdown, feedback stall and unresolved post-click event-pump failure.

- [Nonblocking feedback and timing diagnostics](nonblocking-feedback-timings.md): delayed event delivery, bounded observer setup and opt-in buffered phase/frame timings.

- [Gemini nonblocking-feedback trial](gemini-nonblocking-feedback-benchmark.md): clean 20-turn real-web probe, feedback and debug timing measurements, and remaining serial identity checks.

- [Current runtime defaults](runtime-defaults.md): automatic capture selection, adapter/backend compatibility gates and explicit native/screenshot controls.

- [Required automatic episode grading](automatic-grading.md): prospective dispatch contract, explicit diagnostics and post-close native grading.

- [Opt-in AX fact provenance](ax-fact-provenance.md): unchanged policy requests, exact private source/output spans, retained delivery and synthetic-only adoption scope.

- [Optional suite inspection recording](inspection-suite-recording.md): pinned provider hook, task adapters and partial prefix coverage.

- [Canonical answer schemas](canonical-answer-schemas.md): declared finite product options, semantic extraction and native comparison boundaries.

- [Qwen serving status](qwen-serving-status.md): SSH engine logs, shared-scrape concurrency and throughput observations, counter limitations and future W&B/journal wiring.
