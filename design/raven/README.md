# Raven chat

The full-page v42 Raven chat now sends questions to the Raven backend API, shows visited websites while the raven flies, and renders Markdown answers with captured citation cards. Conversations are saved locally in the browser. The compact v40 entry remains the original visual demo.

For an offline demo with scripted website visits and illustrative evidence:

```sh
python3 scripts/run_bounded_job.py --memory-mib 1024 -- python3 design/raven/tools/mock_backend.py --port 8767 --delay 4
```

Open <http://localhost:8767/chat-fullpage-v42.html>. Send a question, stop research midway, or include `[error]` to exercise failure. No model API, external website access, npm install or Blender is needed. For live research, serve `outputs/raven/` from WEB-A's `apps/raven/backend.py` after integration.

- [Backend integration, commands and acceptance](../../docs/agents/raven-backend-chat-handoff.md)
- [Asset inventory](../../docs/agents/raven-assets.md)
- [Original integration notes and evidence schema](../../docs/agents/raven-integration.md)
- [Native Blender sources and regeneration](../../docs/agents/raven-authoring.md)
- [Verify asset integrity](tools/verify_bundle.py): `python3 design/raven/tools/verify_bundle.py`

`outputs/raven/` preserves the relative asset layout; `work/` contains the native exporter tools. `manifest.json` records current hashes and original source hashes. `validation.json` preserves historical import checks; current acceptance evidence is separate. Manual helper ravens demonstrate visuals and do not start agents.

Third-party licenses are retained beside Marked, DOMPurify and Three.js. Those licenses cover their respective libraries; this package does not assign a new license to the custom raven artwork, reference image or project code.
