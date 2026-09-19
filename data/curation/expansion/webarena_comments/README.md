# Original forum post/comment tasks: structural diagnostics

Original WebArena Verified tasks **610–614**, template **9**, are retained verbatim in `contracts.json`. None is accepted or training eligible. They ask to “post a review of my recent reading” but provide neither the review text nor the user's opinion. A title, an arbitrary body and a linked comment cannot establish fulfillment of that request. `review_semantics` is always null; successful structural verification leaves whole-goal `task_completed` null. A missing required structural outcome can establish false.

The original native checker is separately preserved: root's synthetic audit at `.local/curation-expansion/forum-comments-native-audit-v1/report.json` found that 610 does not bind the comment to the newly created post, while 611–614 contain literal `{{post_id}}` placeholders which reject actual numeric IDs. Those synthetic examples are not browser results.

## Bounded implementation

`run.py` uses the copied frozen core-tools-v3 runtime and full cached original forum on **19079/19078** (`curation-webarena-comments-v1`, owner `curation-comments`). All actions use the native tool transport and BIDs from exact current delivered AX. The source website, original goal, surrounding content and navigation remain intact. No model inference is performed. The scripted body is explicitly diagnostic text supplied by the privileged driver; it is not a hidden expected answer or a proposed authentic opinion of the user.

`CommentTask` captures baseline submission/comment IDs privately, and before browser close reads new database rows plus the corresponding authenticated rendered post pages. The derived checker verifies:

- A new visible, unmoderated post by the authenticated user, exact requested title and books forum.
- A new visible, unmoderated, top-level comment by that user with exact requested body, linked to the newly created matching post.
- Independent rendered page identity, post title/author/forum, and comment body/author agreement.
- Additional posts/comments and comments on unrelated posts as scoped unauthorized effects; general account/site authorization remains unknown.

A missing or inconsistent evidence set stays unknown. Duplicate comments do not erase the existence of the required comment; they independently violate authorization. The whole-goal result is still null when review semantics are unknown. Existing-record mutation, transient/deleted side effects, and arbitrary account changes are not comprehensively covered.

The browser suite is intentionally limited to task610 structural positive, wrong-parent and missing-comment controls. They execute sequentially on the dedicated database, each capturing a fresh baseline. Previous diagnostic rows remain part of the full site; these are not independently reset training episodes. Offline tests additionally cover duplicate comments, nested replies, wrong body/author and missing/conflicting evidence. No readiness for arbitrary model rollouts is claimed.

## Reproduction

```bash
.venv/bin/python -m unittest data.curation.expansion.webarena_comments.test_grader -v
.venv/bin/python data/curation/expansion/webarena_comments/suite.py \
  --output .local/curation-expansion/forum-comments-structural-NEW
```

The suite requires the explicitly owned existing original container; it does not start/reset services. Output must be new. A failed or timed-out case stops the suite, and its partial evidence remains. Each case records per-process source closure, full HAR, exact native mock requests, selected AX targets, original native grade, private final verification, container identity and artifact hashes. The CLI permits only task610 because the four additional ambiguous instances do not justify repeated browser runs before a contract decision.

## Saved result

`validation-index.json` indexes all three saved cases. Structural positive is true, wrong-parent and missing-comment are false. Only wrong-parent is action-error-free. Positive and missing-comment each retain one 500ms `Create submission` press timeout despite persistence; neither is promoted to clean validation. The real wrong-parent case receives original native score **1**: it comments on the prior diagnostic same-titled post, selected through ordinary visible forum links, while the new requested post is a different database record. All 376 recorded artifacts and 27 exact current AX targets were checked. Nine offline tests pass. All five tasks remain held from accepted counts.
