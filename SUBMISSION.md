# 1RT730 submission guide

This repository grew over the course of the project and contains many earlier experiments.
**This page lists the code that the report and the demo are about.** Everything else is history.

## What the project is

An LLM browser agent that does shopping errands on websites and is evaluated on whether it
finishes the task **without making changes the user did not ask for** (e.g. a pre-ticked newsletter,
a paid add-on, a pricier delivery). Websites are procedurally generated, so every task has an
automatically computed correct answer and an automatic grader.

## Where to look

| Part | Code | Notes |
|---|---|---|
| **Agent loop** | [`intent_browser/runner.py`](intent_browser/runner.py), [`intent_browser/native_tools.py`](intent_browser/native_tools.py), [`intent_browser/backend.py`](intent_browser/backend.py) | Reads the page as a text accessibility tree, acts through native tool calls (click, fill, search the page, …), records a full trace. |
| **Real-web + shared-window browsing** | [`intent_browser/open_internet.py`](intent_browser/open_internet.py), [`intent_browser/human_browser.py`](intent_browser/human_browser.py) | Open-web mode; agent and human share one browser and can hand tabs to each other. |
| **Generated shopping worlds** | [`experiments/accepted_catalog_commerce/`](experiments/accepted_catalog_commerce), [`environments/website_world/`](environments/website_world), design in [`docs/procedural-commerce-design.md`](docs/procedural-commerce-design.md) | Products, retailers, offers, stock and delivery are sampled; the websites are rendered from the same world. |
| **Tasks + automatic grading** | [`environments/website_world/catalog_task_generation.py`](environments/website_world/catalog_task_generation.py), [`environments/website_world/simulated_order_grading.py`](environments/website_world/simulated_order_grading.py), [`intent_browser/automatic_grading.py`](intent_browser/automatic_grading.py) | The generator knows the hidden world, so an oracle computes the correct answer; an episode cannot start without a grader. |
| **Steered generation** (forcing rare situations) | [`experiments/steered_generation/`](experiments/steered_generation), [`docs/agents/steered-generation.md`](docs/agents/steered-generation.md) | Samples worlds conditioned on a requirement such as "the cheapest offer is sold out". |
| **Hindrances / dark patterns** | [`environments/commerce_scenarios/`](environments/commerce_scenarios), [`experiments/commerce_dark_patterns/`](experiments/commerce_dark_patterns), suite builder [`scripts/hindrance_suite.py`](scripts/hindrance_suite.py), docs [`docs/agents/hindrance-suite-tier1.md`](docs/agents/hindrance-suite-tier1.md) | Trap mechanisms mounted on the shop the agent should buy from (pre-ticked opt-ins, opt-ins coupled to "accept terms", required cover dropdowns, …), each with a clean twin and scripted correct/wrong controls. |
| **Hindrance build rounds 6–10** | [`scripts/hindrance_suite.py`](scripts/hindrance_suite.py), [`scripts/hindrance_answers.py`](scripts/hindrance_answers.py) (+ `.js`), [`scripts/hindrance_budget.py`](scripts/hindrance_budget.py) (+ `.js`); one section per round in [`docs/agents/hindrance-suite-tier1.md`](docs/agents/hindrance-suite-tier1.md) | Round 6: answer-corrupting traps (price step after size choice, postcode surcharge, stale comparison price). Round 7: the same on two named shops. Round 8: budget traps (a size price step, surcharge or late fee pushes the total over the budget in the user's memory; the agent should ask first) and variants of the coupled-tick and below-read-depth traps (age confirmation, privacy acknowledgement, paid add-on, collapsed fee/insurance/data sharing). Round 10: other categories (basket substitution, sponsored lookalike, subscribe-by-default, size choice that switches to a paid bundle). |
| **Running models on the suites** | [`scripts/hindrance_model_run.py`](scripts/hindrance_model_run.py) (hindrance suites), [`scripts/comparison_suite.py`](scripts/comparison_suite.py) (34-task capability suite) | OpenRouter (Qwen3.8-27B), any OpenAI-compatible endpoint such as a self-hosted vLLM (`--openai-base-url`), or a GPT model through a subscription bridge; token budgets, per-episode wall-clock alarm, request retries, parallel episodes with a shared live cap (`--concurrency-file`) and optional forkserver workers ([`scripts/hindrance_worker_preload.py`](scripts/hindrance_worker_preload.py)). |
| **Self-hosted serving + training stack** | [`training/scripts/serve_qwen_suite.py`](training/scripts/serve_qwen_suite.py), [`training/README.md`](training/README.md), findings in [`docs/training-findings.md`](docs/training-findings.md) | vLLM serving of Qwen3.8-27B-FP8 and QLoRA SFT. The GRPO pipeline was validated on a toy task only; no GRPO run on browser tasks. |
| **Rented-GPU (Vast) serving** | [`experiments/hindrance_sft/vast/`](experiments/hindrance_sft/vast) | Allocation with an on-host self-destroy deadline and a workstation watchdog, SSH tunnel to vLLM, a controller that sets the episode cap from vLLM KV-cache headroom, round launchers and the host setup/serving/training kit. Needs `VAST_API_KEY`; paths are those of the original workstation. |
| **SFT self-distillation pilot** | [`experiments/hindrance_sft/sft/`](experiments/hindrance_sft/sft) | Dataset builder from Qwen's own trap-avoiding hindrance episodes (held-out by trap type), Axolotl QLoRA configs, generic replay mixing, and a generic-capability regression (GSM8K, IFEval, MMLU-Pro; 400 frozen items in `regression/data/`). The LoRA adapters (~220 MB each) are not in the repository; available on request. |
| **Demo app ("Raven")** | [`apps/raven/`](apps/raven) (backend, browser extension, side panel), UI in [`design/raven/outputs/raven/`](design/raven/outputs/raven), runbook [`docs/agents/raven-demo-hardening.md`](docs/agents/raven-demo-hardening.md) | Full-page chat where the agent browses in the background, and a browser-extension side panel where it works in the user's own window. |
| **Results** | [`results/`](results) | 34-task suite (`results.md`), hindrance experiments (`hindrance-results.md` + CSVs), trace forensics (`hindrance-forensics.md`), final per-mechanism tallies for all suites (`hindrance-final-tallies.txt`), trap screenshots (`trap-review.html`), SFT pilot (`sft-final-comparison.md`, `sft-run1-heldout.md`) and its generic regression (`sft-generic-regression*.md`). |

## Running the demo

```bash
# from the repository root (Linux/WSL, Python venv with requirements installed)
apps/raven/start_demo.sh 8770        # starts the backend + a browser with the Raven extension
python -m apps.raven.smoke --url http://127.0.0.1:8770   # no-model smoke check
```
Open `http://localhost:8770/` for the full-page chat, or the side panel in the launched browser.
The demo needs a model key (OpenRouter) or the subscription bridge; see the runbook.

## Note on the rest of the repository

Directories such as `data/`, `deploy/`, `config/` and most of `scripts/` and `experiments/` are
earlier phases (benchmark adaptations, a team web interface, infrastructure probes). They are kept
for provenance but are not needed to understand the submitted work.
