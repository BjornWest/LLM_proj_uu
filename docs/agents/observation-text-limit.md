# Optional observation text limit

`run_episode(..., observation_text_limit=48000)` opts into a larger flattened accessibility-tree prefix. The default is exactly 16000 Python string characters; the URL/action-error envelope and truncation marker are outside that cap. Only positive integers are accepted. `None`, booleans, and floats are rejected before creating a trace, browser, or model request.

The selected cap applies to initial observations, refreshed decision observations, unpaced decision text, and post-action text artifacts. Exact selected text remains in the request/decision provenance. Raw observations and screenshots retain their existing representation. Metadata and the final episode record contain:

```json
{
  "observation_text_limit": 48000,
  "observation_text_limit_scope": "flattened_axtree_characters_before_truncation_marker"
}
```

This is a trusted caller option, not a webpage instruction. It does not select a view, repair output, change parsing, or alter a verifier. The existing terminal-answer option can be used alongside it. A larger character limit is not a token or byte budget: reserve against the actual serialized UTF-8 request, including system instructions, history, and envelopes.

## Verification

Focused runner, pacing, exposure, request/error logging, search, session, terminal-answer, and curation-wrapper tests passed: 58 tests plus 46 subtests. Run:

```bash
.venv/bin/python -m pytest -q tests/test_observation_text_limit.py tests/test_terminal_response.py tests/test_runner_pacing.py tests/test_policy_exposure.py tests/test_evaluation.py tests/test_search.py tests/test_session_routing.py data/curation/test_fresh_pilot.py
```

Offline replay of the pinned artifact in `data/curation/workarena_exercise/observation-prefix-gap-v1.json` verified both original hashes and byte-identical default text. At 48000, the saved `[a1109]` combobox and `[a1446]` option are included. The expanded observation is 40097 UTF-8 bytes; this is not the complete model request. Local evidence: `.local/preflight/workarena-observation-limit-v1.json`.

No new browser/model calls were made, historical artifacts were not rewritten, and no certificate or frozen profile was refreshed. A new experiment must pin the changed runner and its chosen limit. The replay demonstrates that the controls are included; it does not establish improved model performance or prove truncation caused every historical loop.
