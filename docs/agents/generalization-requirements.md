# Generalization requirements

User-approved design constraints, 2026-09-15. Apply these to environment
packaging, observation tooling, training data and evaluation. These are
requirements, not a claim that current development runs establish generalization.

## Interface fidelity

Preserve original frontend behavior and navigation wherever feasible. Version
every repair or adaptation and retain upstream source hashes and historical
evidence. Reduced fixtures must say what is absent: current P10 is not the full
health application (scheduling/doctors are unavailable), P11 is not the full music
application, and the IKEA diagnostic does not establish a purchase outcome.
The Campus demo is a synthetic usability demonstration. Packaging a fixture
does not turn it into the full upstream benchmark.

Do not simplify labels, expose hidden state, select relevant controls using the
grader, or silently add task-specific navigation hints to make the agent pass.
Functional repairs need before/after evidence and a separately versioned cohort.

## Holdouts and honest claims

Hold out entire sites/codebases from our SFT/RL data and repeated development
tuning, rather than merely changing products or task wording on the same site.
Freeze split groups and track exposure through development, teacher traces and
model selection. Sites repeatedly debugged here, including current WorkArena
exercises, are development sites. "Unseen" means unseen by this project's
training/tuning; it does not establish absence from foundation-model pretraining.

Report held-out completion and authorization separately, together with failures,
abstentions and technical interruptions. Refusing every task is not success.

## Messy observations are part of the task

Test ordinary interface difficulty separately from deceptive intent: duplicate
labels, nested frames, asynchronously changing widgets, scrolling, clipped
controls, transient feedback and node IDs whose semantic meaning changes.
Do not pool these into one unsupported causal explanation for a failed run.

Prefer reusable observation navigation (paging, text search, focused subtrees)
that works from policy-visible data. Such tools are planned, not implemented by
this note. The optional 48,000-character AX prefix fixes one observed omission;
it is not a general solution to arbitrarily large or confusing pages. Keep raw
observations and the exact selected model input, including any truncation.

Current systematic policy input is AX text. Saved screenshots are review
artifacts, not proof the model saw pixels. Screenshot-based navigation and
visual-only difficulty require a separate multimodal input/model configuration
and explicit delivery evidence.

## Path to ordinary websites

Keep the agent runtime separate from site-specific reset/setup/verifier code.
Privileged contracts and environment state must not enter policy observations.
Preserve actual browser interaction rather than teaching private fixture APIs.

Later real-site transfer should start with read-only tasks in a separate browser
profile, then reversible actions in authorized test accounts. Do not attach the
agent to the user's everyday logged-in profile or infer authorization for real
purchases, signups or destructive changes. Where independent outcome verification
is unavailable, record that limitation; do not silently substitute an LLM judge.

## Deployment consequence

Use the same versioned environment assets/runtime locally and on rollout hosts;
Vercel is an access/review surface. Test lifecycle and verdict parity when moving
hosting. A local package should not require external network calls during its
advertised offline tasks. External-service benchmarks (notably WorkArena) remain
explicitly outside that offline claim. Preserve unknown upstream license status.
