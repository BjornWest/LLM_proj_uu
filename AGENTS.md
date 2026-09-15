# Repository guidance

## Documentation audiences

- Keep the root `README.md` concise and approachable for human group members. Explain the project's purpose, agent loop, integration roles and code layout in plain language.
- Put new documents intended mainly for coding agents in `docs/agents/`: technical handoffs, implementation notes, detailed setup/runbooks, audits and development-status writeups. Use descriptive filenames and link from `docs/agents/README.md` when useful.
- Do not move or rename existing documentation during the current concurrent work. Continue updating existing documents at their current paths when that is the task; do not create competing copies. A later migration needs explicit coordination and link updates.
- Human-oriented explanations may live in `docs/` and be linked from the root README. Keep command-heavy operational detail out of the introductory README; link to the relevant guide instead.
- Distinguish implemented local capabilities from deployed capabilities, scripted validation from model results, and adapted fixtures from full upstream benchmarks. Describe training preparation as preparation until supported by actual training evidence.
- `docs/agents/legacy-readme.md` preserves the previous root README as a historical reference. Do not treat its older status notes as current instructions or keep it synchronized with the new introduction.
