**Difficulty evidence — checked 14 September 2026**

No published Qwen3.8-27B result was found for SusBench, TrickyArena, Browser Agent Chaos or DoomArena in targeted searches and the primary sources below. This records the scope of the search, not proof that no result exists.

Qwen's official card reports **64.8 on WebArena-Verified**, using its official grader under the OSWorld scaffold, and **84.3 on OSWorld-Verified**. These are vendor-reported results with a different agent setup from our AX-only harness, not dark-pattern scores. Card metadata revision at inspection: `1d4bf0f2ff6012fd82039f2fa52739d0dd7c60c0`. [Official card](https://huggingface.co/Qwen/Qwen3.8-27B#benchmark-results).

TrickyArena Table II averages BrowserUse, Skyvern and Agent-E:

| Backbone | Clean task success | One-pattern task success | Evaded completion |
|---|---:|---:|---:|
| GPT-4o | 68.5% | 48.7% | 17.0% |
| Claude 3.7 Sonnet | 65.2% | 56.8% | 23.6% |
| Gemini 2.5 Pro | 68.8% | 56.8% | 19.3% |

Evaded completion combines task completion with the upstream definition of avoiding deception. These historical figures do not validate our revised graders. [Paper, Table II](https://arxiv.org/html/2510.18113v1#S5.T2).

SusBench reports avoidance conditional on an injection response, not full task pass rates. Browser Use + GPT-5: overall **68.3%**; confirm shaming **93.9%**, trick wording **42.9%**, preselection **36.7%**, hidden information **8.6%**. Agent non-response exclusions range from 6.4% to 12.8%. Treat these as pattern-difficulty clues given our callback findings. [Paper, Tables 4–5](https://arxiv.org/html/2510.11035v2#S5.SS2).

DoomArena's WebArena-Reddit experiment reports GPT-4o task success **21.2% clean**, **11.4% with banners**, **0% with pop-ups**; corresponding attack success **80.7%** and **97.4%**, without defense. This illustrates floor risk for later attack experiments. [Project results](https://servicenow.github.io/DoomArena/).

The [Chaos repository](https://github.com/idovmamane/browser-agent-chaos) provides no model pass-rate table in the inspected README. Its sample dashboard is not a validated model leaderboard. Our recorded development confirmshaming score is likewise not a Qwen evaluation. The Qwen MiniWoB smoke reported in this conversation solved three basic tasks in four parsed actions; it is not an estimate for the whole MiniWoB suite.

**Proposed calibration, not an executed experiment:** use a development slice of 6–10 distinct tasks, each clean/deceptive with two runs (24–40 episodes), once graders are ready and a cost cap is authorized. Seek mostly reliable clean completion, approximately 70–90%, and a material spread of deceptive safe-success outcomes, approximately 30–70% as a working heuristic. Keep technical failures out of claims about deception. Our explicit authorization constraints may make the tasks easier than the original prompts, while stricter graders may lower measured success. Measure both effects locally.

Keep simple Chaos choices as controls; prioritize warranty/preselection and tricky wording for discrimination, with hidden-information tasks as a harder tier. Retain authorized extras to detect blanket refusal. Use a separate calibration slice and freeze held-out task selection before comparing training changes. No paid runs were made for this research.
