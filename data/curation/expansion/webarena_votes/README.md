# Original forum upvote tasks: final-state validation and ordering ambiguity

This stages original WebArena Verified tasks404–408, five instances of template22. The complete cached Postmill website and original goals remain unchanged. No dark patterns or rewritten task prompts are introduced.

**Four tasks are held because “newest” is ambiguous in the imported source.** Original Postmill `SubmissionPage` sorts New by descending submission ID, whereas displayed timestamps are publication/creation timestamps, not edits. The entity constructor, separate `editedAt` field, HTML `published_time`, Atom published/updated fields and page template establish that distinction. Current source targets agree with UI-New, but tasks404/405/406/408 have another post with a later publication timestamp. Only task407 agrees on both criteria. `timestamp-source-evidence.json` retains the exact rows/source text; the goals are not silently redefined as “highest ID.”

The project-derived checker records **source_target_upvoted** separately from **task_completed**. An authenticated independent final forum GET must show the target vote, and a read-only database query must agree for the actual task account. Initial and final target/New-order agreement is checked. Publication-time disagreement holds original-task completion unknown even if the source-target vote is confirmed. Raw upstream request-based grades remain separate. In the observed undo control, the native evaluator selected the latest vote request and correctly rejected the undone upvote; no vote-history false positive is claimed.

## Isolation and native cases

The disposable owned container is `curation-webarena-biography-v1`, site19099/control19098. It may be recreated after ownership/mount checks; biography traces and source are preserved. Shared Reddit9999/18999 is never touched. The suite starts from the original cached image, records initial target vote/score state, and restores only that original target state before each sequential fresh browser session. Source queries and resets are privileged setup/checking, never policy actions or hidden API mutation shortcuts.

The driver reaches forums through their original directory, selects the original New sort, extracts the current first post from the page, and uses its native Upvote/Downvote button. It does not copy a private expected post ID into the action. Human/scripted semantic aliases (for example, “future technology” → Futurology) are declared assistance, not model evidence. Every BID must occur in the current delivered AX. The copied `core-tools-v3` runtime, MockTransport, `slow_mo=0`, 48,000-character observation cap and source hashes are retained.

Planned controls are positive/downvote for all five tasks, plus undo, neutral and missing privileged evidence for task407. Missing evidence is a verifier fault-injection case, not a model failure. Full account-side-effect authorization and training readiness remain unknown/false. Evaluation occurs before browser close.

```bash
.venv/bin/python -m unittest data.curation.expansion.webarena_votes.test_grader
CURATION_FROZEN_RUNTIME="$PWD/.local/curation-expansion/frozen-runtime-v1" \
.venv/bin/python data/curation/expansion/webarena_votes/suite_v2.py \
  --output .local/curation-expansion/webarena-votes-NEW
```

Use a new output directory. Each case is bounded to240 seconds. The suite uses cached images only and never invokes paid inference. Source grading runs in the existing separate WebArena Verified virtual environment. No source/site/core changes or model capability claims are implied by a passing scripted diagnostic.

## Saved result and remaining holds

`validation-index.json` selects13 error-free native cases: positive/downvote for all five source tasks, plus task407 undo, neutral and missing evidence. The producer audit rechecks1,140 artifact hashes,82 current-AX targets and95 mocked native decisions without importing the candidate checker. Only original task407 is an acceptance candidate;404/405/406/408 remain held and do not count toward accepted-task totals.

Task407 outcomes are true for an upvote, false for downvote/undo/neutral, and null when privileged final evidence is deliberately missing. The upstream native evaluator also correctly rejects the observed undo, using the final choice0 request; this is not a demonstrated native history loophole.

Two failed development cases remain separate: the first407 positive encountered the known500ms link timeout despite a confirmed saved vote; the first undo driver incorrectly searched for “Upvote” after the button had become “Retract upvote.” `run_v2.py` changes only that observed label and its introductory description. The fresh undo succeeds. No core/site/grader repair or timeout fix is claimed.

Selected positive/downvote proofs use original `run.py`; the three extra407 controls use corrected `run_v2.py`. Their exact manifests remain per case. `suite_v2.py` is the current reproduction command, changing only the invoked driver and suite schema; a uniform whole-suite v2 cohort has not been run. Existing v1 reports and biography artifacts remain untouched.
