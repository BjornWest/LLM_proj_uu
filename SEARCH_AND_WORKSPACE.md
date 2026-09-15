# Search and agent workspace design notes

Research checked September 14, 2026. Parallel Fast search is now implemented as
an optional tool; workspace tools remain planned. See the
[retained search setup](docs/agents/legacy-readme.md#optional-parallel-web-search)
for API-key setup and commands. Offline integration tests use simulated responses;
one live Fast request has now verified authentication and logging. Its top results
were mainly general accessibility documentation, so result quality needs a
separate representative-query comparison.

The adapter uses our existing HTTP client directly against Parallel's Search API.
This avoids adding an MCP runtime for one tool. Search is independent of model
inference, explicitly budgeted, and recorded in versioned traces with raw response
artifacts and the exact text shown to the agent.

## Search recommendation

Start by testing Parallel Fast for cost; compare with Brave on representative
queries before claiming a quality winner. Keep the search provider independent
of the model backend. Do not buy a subscription or start paid calls implicitly.

| Provider/mode | Listed price per 1,000 requests, before credits | Relevant allowance |
| --- | --- | --- |
| Parallel Fast/Turbo | $1, up to 10 results per request | $5 monthly credit advertised |
| Brave Search | $5 | $5 monthly credit advertised |
| Exa Search | $7 | $20 signup / $10 monthly credits advertised |
| Tavily Basic | $8 pay as you go | 1,000 credits/month; basic search uses one credit |

Parallel Basic/Advanced cost $5/1,000; Tavily Advanced uses two credits and costs
$16/1,000 at the pay-as-you-go rate. Extraction, extra results, and model tokens
can add to these figures. For example, 1,000 episodes using three searches each
would cost $3 with Parallel Fast or $15 with Brave before credits. This does not
establish how search cost compares with our still-unspecified inference budget.

Sources: [Parallel pricing](https://parallel.ai/pricing),
[Brave pricing](https://brave.com/search/api/), [Exa pricing](https://exa.ai/pricing),
[Tavily credit rules](https://docs.tavily.com/documentation/api-credits).

Exa also documents a free MCP plan for casual use, with an own-key path when
limits are reached. That is useful for an initial development hookup, but should
not be assumed to cover training-scale traffic.
[Exa MCP](https://exa.ai/docs/reference/exa-mcp).

## Reference implementations

- OpenCode's source at `a74c472f` supports Exa and Parallel through remote MCP.
  Provider selection can depend on flags/session; a study should pin it explicitly.
  [Tool implementation](https://github.com/anomalyco/opencode/blob/a74c472ffb941e6b027e5348be50cfe2225c6c56/packages/core/src/tool/websearch.ts).
- Pi's default tools are read/write/edit/bash. Search is an extension rather than
  a mandatory built-in service. Its sessions are JSONL with branch relationships.
  [Pi README](https://github.com/earendil-works/pi/blob/53816d7dcc5ebe3a0eedec3cd07196c3a66d83fd/packages/coding-agent/README.md).
  Parallel publishes a Pi extension with search and page extraction, currently
  documented as using Basic mode.
  [Extension](https://docs.parallel.ai/integrations/pi-extension).
- Codex documents an OpenAI-maintained cached search index and custom model
  providers. Switching providers does not imply portable built-in search or
  arbitrary consumer-subscription compatibility. Standalone search for custom
  providers requires a compatible endpoint, model, and runtime and remains under
  development/off by default.
  [Search](https://learn.chatgpt.com/docs/web-search),
  [Providers](https://learn.chatgpt.com/docs/config-file/config-advanced).

## Small workspace contract

Expose an episode-owned directory using explicit tools:

```text
list_files(path)
read_file(path, offset, limit)
write_file(path, text)
delete_file(path)
download_file(url, path)     # separate network capability
```

Nested paths support notes, comparison tables, and downloaded artifacts. Writes
replace/update files; deletion supports correction and cleanup. Start each episode
fresh and archive its workspace at the end. Cross-episode user preferences remain
a separate future feature. Text files are external working memory only when the
agent deliberately reads them; creating a file does not put its contents in context.

Keep verifier code/state, other episodes, credentials, and authoritative logs
outside the exposed directory. Resolve paths and reject traversal and symlink
escapes. Enforce file/total byte limits and bounded reads/downloads. File tools
do not require a general shell. PDF extraction or image inspection needs an
explicit reader later; merely downloading a file does not make it understood.

## Trace requirements for the extension

The runner now dispatches browser and search calls. Search consumes decision
budget but does not call BrowserGym step or manufacture an environment reward.
Future workspace calls should follow the same convention.

Append a start event before execution and a result/error event afterward, linked
by call ID. Capture the exact model input and output; raw search response and
the bounded representation actually shown to the model; provider, mode, timestamp,
latency, usage/cost where available; and references to immutable artifacts.

For files, preserve read content and versions before/after writes/deletions.
For downloads, save source URL, bytes, media type, and content hash. A final
workspace snapshot alone cannot reconstruct what the policy knew earlier.
Version tool schemas and observation adapters. Record which tools are enabled.
For repeatable search experiments, retain returned results and support explicit
record/replay later; a random seed cannot freeze an external search index.
