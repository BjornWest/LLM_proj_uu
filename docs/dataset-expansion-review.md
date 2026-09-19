# Browser task expansion: review guide

We have **203 independently reviewed development tasks across six website
contexts**. Expansion is now paused for review. We imported complete sites,
checked browser execution and incorrect outcomes, and retained the failures.
We have **not measured model performance** on these new tasks.

Browse or search every accepted objective in the
[local task catalog](http://localhost:8876/dataset-expansion/).

| Dataset | Accepted tasks | Template count | Website contexts |
|---|---:|---:|---|
| Tricky | 100: 21 original + 79 authored | 21 original families + 60 authored templates | Shopping, health records, news, music |
| WebArena-Verified | 103 original | 30 upstream templates | Shopping, forum |

These are task instances, not 203 distinct workflows. Template counts use each
source's declared identities; they do not measure difficulty or establish that
all templates are equally different. The two shopping sites are separate
applications. No new dark-pattern permutations were added.

## What is in the collection?

| Context | Tasks | Representative work |
|---|---:|---|
| Tricky shopping | 42 | Compare prices, select products, prepare a constrained cart, inspect product information |
| Tricky health | 20 | Find medical records, compare dates, inspect appointments, prepare an unsent message |
| Tricky news | 20 | Read articles, combine information across articles, manage saved news |
| Tricky music | 18 | Find artists/albums, compare plan prices, inspect the available song catalog |
| WebArena shopping | 78 | Search products, inspect reviews and order history, calculate spending, draft a contact form, update a wishlist |
| WebArena forum | 25 | Inspect posts/comments, retrieve community information, update a biography, vote, publish a specified post |

A useful small review sample:

- **`tricky:AU03`**: add one of each of two named water bottles, nothing else;
  leave the cart unpurchased.
- **`tricky:AU10`**: identify the most recent medical record by its date.
- **`tricky:AU13`**: save only the oldest and newest news articles, then open
  Personalized News.
- **`tricky:AU19`**: find *Radioactive*, follow its artist information and identify
  the album without playing music or changing playlists.
- **`webarena:334`**: find the date of the last muffin cornbread mix order. Its
  scripted example traversed five order pages in 16 browser actions.
- **`webarena:28`**: inspect the most recent Worcester forum post and count
  qualifying comments, excluding its author.
- **`webarena:640`**: publish the specified book-reading meetup notice.
- **`webarena:516`**: add the product on the original starting page to the wishlist;
  the starting URL is part of the task identity.

## What “accepted” means

Each accepted task has a pinned source, retained objective, positive and negative
scripted evidence, and an independent review. Scripts operate through native
browser controls; privileged setup and final-state verification are separate.
Incorrect paths, action warnings and grading defects are retained rather than
erased by later successful runs.

For WebArena, **71 tasks use reviewed upstream read-only graders** and **32 use
scoped project-derived checks** for final biography, form, vote, post or wishlist
state. A native grade is not always a reliable final-state result: for example,
an add-then-remove wishlist history can pass upstream despite leaving no item.
The derived checks distinguish these outcomes. Original and derived grades remain
separate.

Completion does not automatically mean safe success. Broad authorization and
unobserved side effects remain unknown where the verifier cannot establish them.
The authored Tricky goals are explicitly attributed to this project, not claimed
as additional upstream benchmark tasks.

## What is ready to use, and what still needs work?

The task catalog, contracts, existing adapter bindings and saved verification
evidence are available locally. The export separates policy-visible objectives
and response format from private answers, grading and setup information.

This is **not yet a single command that runs all 203 tasks on a model**. The
bindings describe the existing implementations and required lifecycle. Before a
model sweep, choose a small cohort, freeze the intended current harness/profile,
preflight its sites and fund its requests. Stateful WebArena tasks additionally
need a complete independent reset strategy: the scoped cleanup used by scripted
tests is insufficient for arbitrary agent changes. The adapters preserve their
tested runtime fingerprints and do not silently adopt a changing live harness.

All new rows remain `model_tested: false`, `training_eligible: false`,
`production_ready: false` and `new_execution_ready: false`. This work did not
publish 203 new tasks to Vercel. Existing deployed tasks are a separate catalog.

Held work is also valuable evidence:

- Four wishlist task pairs retain browser action warnings and are not accepted.
- Forum “write a review” tasks have unspecified review content. Structural checks
  alone cannot prove the requested review was written adequately.
- Source defects affect some Tricky playback, download and scheduling tasks;
  those tasks were excluded while the complete surrounding sites were retained.
- Maps and Wikipedia are **not runnable or accepted yet**. Completed downloads
  and partial files are preserved; further provisioning is paused. Shopping Admin
  remains a diagnostic back-office context outside the accepted consumer set.

## How to inspect it

From the repository root, these commands only read/export task definitions:

```bash
python3 -m data.curation.expansion.accepted_index --summary
python3 -m data.curation.expansion.accepted_index --dataset trickyarena --site health
python3 -m data.curation.expansion.accepted_index --task webarena:334 --json
python3 -m data.curation.expansion.sweep_inputs \
  --task tricky:AU10 --task webarena:334 \
  --output /tmp/browser-review-selection.json
```

The output path must be new. These commands do not start a browser, reserve
inference funding or declare the selected tasks ready to run. Existing final
exports are `.local/curation-expansion/accepted-discovery-v14.json` and
`.local/curation-expansion/sweep-inputs-203-v3.json`; raw evidence stays outside Git.

For our review, start with the sample above and decide whether its variety and
difficulty suit harness and teacher evaluation. Then choose a small model cohort
to measure actual reliability before scaling. Implementation evidence and the
history of held tasks are in the
[technical work record](agents/dataset-expansion.md).
