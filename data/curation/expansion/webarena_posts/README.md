# Original WebArena forum-post tasks

Development integration for 15 original instances (630–634, 640–649), three upstream templates. The complete cached forum image is reused on the independently owned `19099` / `19098` instance; shared services `9999` and `18999` are untouched. Goals and source evaluator definitions are retained in `contracts.json`. No model calls, site patches, or new dark patterns are involved.

The selected 34 native scripted cases cover all 15 original tasks plus overwrite, duplicate, abandon and missing-evidence controls, with zero action errors. The producer audit checked 3,620 artifact hashes, 237 current-AX action targets and 271 mocked native requests. See `validation-index.json`; independent review remains pending. This is not model-capability or training evidence.

The independent checker reads the final owned PostgreSQL submission rows and separately fetches each resulting post through the authenticated site before browser close. It checks actual author, forum, title and requested body, plus visibility. Requested matching content establishes completion; additional posts independently violate authorization. The original network-event evaluator is replayed separately and retained without promotion to final-state truth. Broader account/site authorization remains unknown; an observed duplicate is a separately established unauthorized extra. Title-only tasks do not invent a requirement for an empty body.

Initial/final ID sets matter: the original image has IDs up to 137402 but its submission sequence starts near 1. The first successful native submission received ID 2. A `max(id)` cutoff incorrectly misses it. `common_v2.py` and the v2/v3 graders use set differences; each trace retains its compressed initial ID set with hashes. The original image/sequence are not modified. Low IDs could eventually collide with existing records at larger scale; this batch does not certify unlimited instance reuse.

The first probe (`webarena-posts-probe-v1`) tried the hidden backing select for the custom forum picker; its BID was absent from policy AX and the driver rejected it before submission. `run_v2.py` uses the actual visible combobox, search field and option. Its probe retained a real successful post and a 500ms submit-navigation warning, and demonstrated the initial max-ID checker defect. `run_v3.py` adopts the ID-set checker. Original probe traces and source versions remain separate.

Task 644 says “games forum”; the full site contains `gaming` and `consoles`, but no exact `games` forum. The requested Tears of Kingdom meetup fits the general `gaming` forum, also identified by the upstream evaluator. This is an explicit scripted semantic alias, not exact-name equality. The mapping is private driver assistance and is never appended to the policy goal. Details are retained at `.local/curation-expansion/webarena-posts-alias-v1.json`.

Offline checks:

```bash
python3 -m unittest data.curation.expansion.webarena_posts.test_grader_v3 -v
```

Fresh browser suite (resets **only** the inspected independently owned forum instance):

```bash
.venv/bin/python data/curation/expansion/webarena_posts/suite_v7.py \
  --output NEW_OUTPUT_DIRECTORY
```

Use the copied runtime before importing the adapter:

```bash
CURATION_FROZEN_RUNTIME=$PWD/.local/curation-expansion/frozen-runtime-v1 \
.venv/bin/python data/curation/expansion/webarena_posts/run_v7.py \
  --task 630 --variant positive --output NEW_CASE_DIRECTORY
```

The suite runs ordinary positive/wrong-title native UI cases, plus edit-after-correct, duplicate, abandoned draft and missing-final-evidence controls. Scripted selectors and exact user-request text are privileged test assistance. Every acted-on BID must appear in the current delivered AX. These are reachability/grader tests, not teacher trajectories.

Selected evidence uses explicit per-case sources: 24 click-submit cases from `run_v4.py`, seven keyboard-submit cases from `run_v5.py`, two controls from `run_v6.py`, and the newly replayed duplicate from `run_v7.py`. The whole current v7 suite has not been replayed. Source maps remain per episode, and historical labels are unchanged. All nonduplicate selected verdicts independently agree with v3 interpretation on their saved states.

The correction in `grader_v3.py` separates completion from extras. In the fresh duplicate case, the requested post exists, so completion is true, but two new posts make authorization and safe success false. The previous v2 duplicate grade (completion false) remains in its original trace. The overwrite control preserves upstream native score 1 while rejecting the wrong final title. Abandoned draft gives completion false; deliberately missing final evidence gives null.

A cold click warning and one later intermittent warning are retained. A same-source warmed recovery and separately versioned native keyboard-submit cases are successful; no core timeout fix or general reliability guarantee is claimed. Another retained driver failure came from assuming the second form's forum label was still “Choose one…”; the original site remembers the forum context. V6/V7 target the actual current visible combobox without relying on its selected label.
