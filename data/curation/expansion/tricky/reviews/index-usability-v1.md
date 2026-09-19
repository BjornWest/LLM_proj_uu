# Accepted-index usability review

The discovery index correctly deduplicates **100 Tricky tasks (21 original +79
authored)**, keeps expected answers/setup out of its rows, and selects the strict
draft closure exactly once for AU46/AU47/AU51/AU52. All120 combined task goals
match their referenced contract rows; all pinned contract/review references
match current bytes. The current builder reproduces the saved v2 rows exactly.
Authored Tricky tasks use60 declared template IDs;81 across original and authored
rows is a naming count, not81 independent mechanisms.

Two concrete usability issues remain:

1. **authored03's primary command is stale.** README lines48–54 run the v1 tests
   and all20 tasks through `verify_native.py`, which imports `native.py` and its
   permissive draft grader. The four draft tasks were accepted only under v2.
   The later correction prose is accurate, but the runnable block should split
   the16 retained v1 tasks from `verify_native_v2.py --task AU46 --task AU47
   --task AU51 --task AU52`, with the v2 tests. No historical file needs changing.
2. **Seven original source pins need repository qualification.** TO15–TO21 expose
   environment revision `8201821fb64a5075f50b015f99653881ab09a030` as
   `source_revision`; their source inventory pins the task repository at
   `4ed5d744d8e9fb53abb7057ba7c5664feb2a67e4`, matching the other original tasks.
   Preserve these historical raw values, but add separate qualified task-source
   and environment-source references before consumers treat the field uniformly.

The other three authored batches' documented native adapter/profile selections
match their accepted versions. Batch01 still explicitly requires a new reviewed
window/deadline; its terminal-format instruction must be bound by the caller.
No leakage claim follows from private contract paths in this discovery index:
only the explicitly projected goal/instructions belong in policy input.

This was a read-only source/reference review. No new browser cases, inference,
source edits or Git operations were performed. Machine evidence and exact hashes
are in `index-usability-v1.json`. These findings do not invalidate the accepted
historical episodes or the100-task count.
