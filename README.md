# Intent-preserving browser agent

Our Uppsala University group project explores **how a browser agent can complete a user's task without making unwanted changes**. For example: buy the requested laptop and remove an automatically added warranty. If the user explicitly requests a warranty, keeping it is correct.

We are building the agent's runtime, reproducible test websites, and checks of what actually happened. Current browser experiments use existing models. The training infrastructure has passed small SFT and RL learning tests; training on our browser tasks remains future work.

## How the agent works

**User goal → read page → choose one action → execute → read updated page → repeat → check outcome.**

1. Our **harness** (the code coordinating an experiment) opens a fresh browser session with a task and starting page.
2. The model receives the goal, a text description of the page's buttons, fields and states, and recent actions/errors. This description is called an **[accessibility tree](docs/accessibility-tree.md)**. Screenshots are saved for human review; the research model currently reads text.
3. The model proposes one action, such as clicking or filling a field. Our code checks that it is allowed, then BrowserGym executes it in Chromium through [Playwright](https://playwright.dev/).
4. The loop ends when the agent finishes, the task ends, or a limit/error stops it. We save a **trace**: observations, model replies, actions and results.
5. A separate task checker evaluates completion and unwanted effects. “Done” from the model is not proof of success; missing evidence stays unknown.

## What each system contributes

| Part | How we use it |
|---|---|
| **Our custom harness** | Coordinates the loop, allowed actions, model calls, limits, traces and task-specific checks. Lives in `intent_browser/`. |
| **BrowserGym** | Connects our Python agent to a real browser, providing page observations and actions. Playwright controls Chromium underneath it. |
| **OpenRouter** | Connects the harness to a hosted language model that chooses actions. Our experiments use Qwen; model/provider settings are configurable, and calls are recorded. |
| **Parallel** | Optional public-web search: `web_search(...)` returns titles, links and excerpts to the model. It is off in controlled local evaluations and the team harness. Searching within a test website uses ordinary browser actions. |
| **Vercel / Daylight** | Hosts the private team interface for submitting tasks, watching runs and reviewing results. The research browser runs on a separate worker. |

### Tasks and datasets

These sources supply tasks, websites and misleading interface patterns. They are not all ready-made training datasets.

| Source | Its role in this project |
|---|---|
| **MiniWoB** | Tiny clicking, typing and selection tasks. Its BrowserGym integration lets us check basic interaction and model-to-browser plumbing. |
| **Chaos** | Synthetic workflows with tempting unsafe actions. We run selected tasks locally, with versioned environment repairs and our own completion/authorization checks. |
| **TrickyArena** | Source for local shopping, privacy/cancellation and membership scenarios. We adapt selected UI components, add persistent records and task checkers, and compare clean/deceptive versions with the same goal. These are scoped local adaptations. |
| **SusBench** | Source of tasks and injected dark patterns. We have inspected its tasks and reproduced an IKEA warranty-selection injection locally to examine its scoring. Full live-site benchmark integration is still outstanding. |

We check **task completion**, **whether changes were authorized**, and **whether a misleading element actually reached the model**. Scripted tests validate the environment/checker; model runs measure agent behavior. A few successes do not establish a benchmark-wide success rate.

## Contribute a task definition

You can propose a task without implementing a website or writing grader code. Start with the [example definitions](data/curation/task_templates/) and the [task-writing guide](docs/task-definitions.md). The examples use YAML, a readable text format with named fields.

Describe the agent's instruction, the starting situation, and **separate requirements** for the desired result and changes that must not happen. Give each requirement a stable ID and say whether it concerns the final state, the entire run, or each event such as a checkout. For precise conditions, include a structured comparison: “at most 900 SEK” uses `lte` and an amount of `90000` öre. A plain-language draft is fine when the check still needs discussion.

Requirements grade **outcomes**. Optional [procedure observations](docs/task-definitions.md#optional-procedure-observations) summarize the approach—for example, whether delivery information or misleading text reached the agent before checkout—without affecting pass/fail. Add them only where useful; receiving text does not prove the agent understood or used it.

The folder includes shopping, appointment, preferences and authorized-warranty templates, plus [three converted TrickyArena tasks](data/curation/task_templates/external/) with their original prompts and our clarifications. [Read the conversion examples](docs/external-task-examples.md) to see how requirements map to checks and where coverage is still limited.

**The definition says what should happen; a separate implementation sets up the page and verifies it.** Only the agent instruction is passed to the browser agent. Expected results stay in the reviewer/grader data. These draft definitions do not automatically become runnable Vercel tasks; setup and checks must be connected and validated first.

## The team website and Vercel

[Open the research interface](https://browseragent.vercel.app/harness) with your invitation code. Vercel queues the task; a Python/Chromium worker on the project PC picks it up and uploads screenshots, traces and results. The PC must be awake and the worker running. Available tasks depend on the deployed worker; local additions may arrive later.

The site's `/` page also offers a simpler demo that acts inside the visitor's browser. Its results do not carry the research harness's independent verification.

**Deployment directory: [`deploy/daylight/`](deploy/daylight/).** Vercel builds this Node.js application with `npm run build`. The build also reads `environments/demo/`, so access to files outside the deployment root must be enabled. Login/API requests go through a server function; application assets stay private, and Vercel Blob stores private run data. The worker has its own Docker deployment in [`deploy/worker/`](deploy/worker/). Updating the website does not update the worker.

## Explore the repository

| Start here | What to look for |
|---|---|
| [Agent loop](intent_browser/runner.py) | In `intent_browser/`, follow `observation.py` → `backend.py` → `actions.py`; `trace.py` records the run. |
| [Test environments](environments/) | Websites, demo pages and adaptations of upstream environments. |
| [Evaluation](intent_browser/evaluation.py) | Shared result definitions; `tricky*.py` and `chaos_verifier.py` contain task-specific checks. |
| [Data curation](data/curation/) / [configuration](config/) | Task inventories, source evidence, experiment definitions and validation records. |
| [Scripts](scripts/) / [tests](tests/) | Setup helpers, reproducible checks and automated tests. |
| `runs/` | Local recordings and evidence; not included in a fresh clone. |
| [Training](training/README.md#how-we-plan-to-train-our-browser-agent) | How teacher traces feed SFT and verified task outcomes feed RLVR; [tested results and next steps](docs/training-findings.md). |

**Next reading:** [Group guide: contributions and a real trace](data/curation/GROUP_MEETING_HANDOUT.md) · [Local setup](LAPTOP_SETUP.md) · [Vercel setup](deploy/VERCEL_SETUP.md) · [Worker setup](deploy/worker/README.md).

New technical handoffs belong in [`docs/agents/`](docs/agents/). Existing technical documents remain in place while other agents are working.
