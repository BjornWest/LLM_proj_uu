This runner serves exactly one B06 browser episode on Modal. The default is a
source-only dry run; `--execute` requires the separately reviewed Evaluation
caller/spec, its frozen task/world/assets, and its automatic grade/viewer release.
It never retries an allocation, model request, or episode. It reuses cached weights.

Launch the controller through the project bounded launcher (2 GiB/256 tasks)
using `training/.venv/bin/python -B`; run `controller.py --help` for exact pin
arguments, including `--source-commit` for this reviewed Training tree. The browser
caller gets its own 4 GiB/512-task bounded job, so detached Chromium descendants
are stopped by the cgroup launcher. Supply the current project
root separately from this committed source tree. The controller validates inputs,
checks every owned image/controller file against the named Git commit and uses
only that tree’s locked image (seven code files), then runs the cached
processor/compiler/parser checks on CPU before allocating
one RTX PRO 6000. The worker installs the SHA-guarded vLLM 0.28.0 parser correction
before launching the server; installed-source CPU regressions are saved under the
actual serving session. That is not a model behavior proof.

The corrected ordered counter/parser stack needs its first qualification: three
image count probes, retained tool/reasoning/image history, and an exactly
100,000-input-token boundary. Three generation calls produce at most five output
tokens to verify prompt-ID and usage parity, including changed output/parallel
controls. This is separate from the one browser episode and is not a throughput
benchmark. Invalid old sorted-wire receipts are never relabeled. Reuse on later
launches requires the separately reviewed capability-composition path; this
runner does not implement or claim it.

The actual Modal function maximum is 86,400 seconds. There is no aggregate episode
alarm. Startup, individual requests, qualification, controller loss, and actual
platform expiry still have watchdogs. The controller heartbeats every 15 seconds;
the worker stops after 180 seconds without it. After the attached automatic grade
and HTTP viewer projection complete, or any failure, the controller stops and
cancels the worker. Its child processes use process groups and are reaped.
Caller failure stops serving immediately. The controller reads durable Events and
re-verifies canonical/native/HTTP grade evidence before retaining any task
verdict; an interrupted completion notification does not erase a verified
result. Exit124 after verified completion retains that result; other errors
retain any valid verdict alongside infrastructure failure. SQLite may recover a
crashed notification transaction, but no Events records are created or updated
by this read. An interruption before durable completion remains a system failure.

`pilot_relay.py` preserves the earlier reviewed Training pilot source byte for
byte. `pilot_probe.py` retains its processor/cache checks but now imports the
committed compiler helper; none of the mutable shared Training modules are
uploaded. The released Evaluation counter is an external pinned
Git artifact, not a copied implementation. All model-visible JSON uses insertion
order; sorting is reserved for implementation fingerprints and saved receipts.

CPU controls: `python -B -m unittest discover -s training/tests -p
test_modal_b06_lifecycle.py -v`. The tests never access Modal. Integration controls
use the workstation's separately preserved B06 source/asset releases and are
skipped if those are absent. CPU mock qualification must not be called live parity.
