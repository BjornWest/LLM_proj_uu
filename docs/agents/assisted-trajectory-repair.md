# Proposed assisted trajectory repair before teacher SFT collection

Status: user-requested follow-up after readiness/observation polishing; **not
implemented** by this note. Existing open-internet intervention notes are useful
provenance, but do not provide saved-episode state restoration or SFT export.

## Intended workflow

1. Select a saved episode and a boundary before a model decision or action.
2. Start an isolated branch of that episode. Restore an environment checkpoint,
   or reset the same pinned world/seed and replay the recorded actions through
   that boundary. Check restored state before continuing. Never replay irreversible
   actions against a shared live service to manufacture a checkpoint.
3. Operator chooses one intervention: a hint supplied to the teacher, a manually
   selected normal browser action, or a replacement final answer/action.
4. Continue normal model execution, or evaluate and close if that intervention
   finishes the task. Use the normal independent verifier; manual completion is
   assisted completion, not automatically success.
5. Retain both the original failure and new branch, with linked traces that can
   each be read independently. Export a separately labeled SFT derivative only
   after validating its conversation and evidence.

## Restoration boundaries

A screenshot/DOM/AX snapshot is an observation, not a website checkpoint. Browser
storage alone does not restore server transactions, inventory, sessions or RNG.
Generated worlds should supply snapshot/restore of their state alongside browser
session state where needed. Otherwise deterministic reset and action replay is
the first supported path. After reset, resolve current controls and verify state;
old BIDs are not stable selectors across fresh browser documents.

At minimum record parent episode ID, branch boundary, world/source revision,
restore mechanism, public-observation comparison and privileged state validation
as separate artifacts. Refuse continuation if the reconstructed state does not
match. New traces retain normal exact model requests/responses, timing and costs.

## Intervention and training provenance

Raw evidence is immutable. Record actor (`model`, `operator`, `teacher_repair`),
intervention text/action, parent linkage and outcome. The operator can use full
trace review, but any assistance based on hidden grader answers must be flagged
and cannot silently become ordinary browser evidence.

The training projection may omit a hint and related assistant discussion. That
does not make the resulting behavior unassisted: later reasoning or actions may
still depend on the deleted information. Retain the raw-to-derived mapping and
assisted provenance outside model input, distinguish synthetic demonstrations
from model-sampled trajectories, and do not pool their success into unassisted
evaluation or on-policy RL statistics.

Prefer a branch starting before the hint: let the assisted teacher propose the
correct action, execute it through normal tools, and construct a reviewed teacher
demonstration under the clean prefix. If retaining reasoning, regenerate/review it
from information available in that prefix, or omit/mask the affected reasoning;
do not leave references to an invisible hint. Regenerate subsequent model turns
under the exported history when practical. This reduces context mismatch but
does not erase the intervention's provenance or prove independent discoverability.

Validate that every surviving tool result has the correct preceding call/ID,
every observation is associated with its real action, no omitted message supplied
otherwise unavailable facts, and the recorded final state still passes grading.
Do not rewrite old provider logprobs as if generated under the cleaned history.

## First implementation boundary

The user expects surgical human editing: allow selecting exact spans of assistant
reasoning to remove, not just entire messages. Preserve untouched spans verbatim,
show a before/after preview, support undo, and retain an edit manifest identifying
source message IDs and exact removed spans. Keep reasoning, user-facing text,
tool calls and intervention messages separately selectable. Validate tool-call
linkage after edits and flag possible invisible-hint dependencies for review;
do not automatically rewrite reasoning or infer that a cleaned trace was unassisted.

One checkpointable/resettable generated world, one saved boundary, one manual
normal action or hint, linked continuation, final grading, and a reviewed SFT
export are enough. No general terminal, arbitrary browser-memory restoration,
automatic failure diagnosis or large repair-model orchestration is needed.

Acceptance: successful repair; wrong intervention remains failed; terminal manual
action graded once; divergent replay rejected; original trace unchanged; clean
export tool-message linkage valid; hidden-hint dependency flagged; independent
branches do not alter each other's state.
