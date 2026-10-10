/** One completion, no agent loop. Pi supplies OAuth and provider transport only. */
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';
import crypto from 'node:crypto';
import { createRequire } from 'node:module';
import { homedir } from 'node:os';
import { zstdDecompressSync } from 'node:zlib';

export function installation(cliPath) {
  const cli = fs.realpathSync(cliPath);
  const root = path.dirname(path.dirname(cli));
  const require = createRequire(path.join(root, 'package.json'));
  const ai = require.resolve.paths('@earendil-works/pi-ai')
    .map(p => path.join(p, '@earendil-works/pi-ai'))
    .find(p => fs.existsSync(path.join(p, 'package.json')));
  if (!ai) throw new Error('Pi model transport package unavailable');
  const pkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json')));
  const aiPkg = JSON.parse(fs.readFileSync(path.join(ai, 'package.json')));
  // Imports are implementation-level on purpose: never load Pi's CLI, sessions,
  // agent loop, project settings, extensions, skills or model config commands.
  if (pkg.version !== '0.80.6' || aiPkg.version !== '0.80.6')
    throw new Error('Pi version changed; audit the new transport before use');
  return { root, ai, version: pkg.version };
}

const json = (file, data) => fs.writeFileSync(file, JSON.stringify(data, null, 2), { flag: 'wx', mode: 0o600 });
const sha = data => crypto.createHash('sha256').update(data).digest('hex');
const load = file => import(pathToFileURL(file).href);

// The inspected Pi catalog predates GPT-6. This explicit descriptor changes
// transport metadata, never substitutes another model slug. Availability is
// decided by the server. Context window corroborated by local Codex model cache;
// prices below are SDK placeholders, NEVER reported as subscription charges.
const extraModels = ['luna', 'sol'].map(tier => ({ id: `gpt-6-${tier}`, name: `GPT-6 ${tier}`, provider: 'openai-codex',
  api: 'openai-codex-responses', baseUrl: 'https://chatgpt.com/backend-api',
  reasoning: true, input: ['text', 'image'], contextWindow: 272000, maxTokens: 16384,
  cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } }));

// Explicit 6.1 descriptor: exact slug, Responses tool transport, no paid probe.
extraModels.push({ ...extraModels.find(m => m.id === 'gpt-6-sol'),
  id: 'gpt-6.1-sol', name: 'GPT-6.1 Sol', contextWindow: 1050000, maxTokens: 128000 });

export async function run(envelope, { fixture, fetchImpl = globalThis.fetch } = {}) {
  const { id, payload, artifact_dir: directory, pi_cli: cli, timeout_ms: timeout } = envelope;
  if (envelope.version !== 1 || !id || !Number.isInteger(timeout) || timeout <= 0)
    throw new Error('Invalid bridge envelope');
  const installed = installation(cli);
  const { getBuiltinModel, getBuiltinModels } = await load(path.join(installed.ai, 'dist/providers/all.js'));
  const models = [...getBuiltinModels('openai-codex'), ...extraModels];
  if (!payload) return { version: 1, id, pi_version: installed.version, models: models.map(m => m.id) };
  const model = getBuiltinModel('openai-codex', payload.model) ?? extraModels.find(m => m.id === payload.model);
  if (!model || model.api !== 'openai-codex-responses') throw new Error('Unknown Codex model; use inspect first');
  const sourceFiles = ['dist/api/openai-codex-responses.js', 'dist/api/openai-responses-shared.js']
    .map(p => path.join(installed.ai, p)).filter(p => fs.existsSync(p));
  sourceFiles.push(path.join(installed.root, 'dist/core/auth-storage.js'));
  json(path.join(directory, 'transport-provenance.json'), {
    pi_version: installed.version, node: process.version, provider: model.provider,
    model: model.id, fixture: Boolean(fixture), transport: 'sse', max_retries: 0,
    sources: Object.fromEntries(sourceFiles.map(p => [p, sha(fs.readFileSync(p))])),
  });
  // Validate/freeze input before touching stored credentials or refreshing OAuth.
  json(path.join(directory, 'responses-request.json'), payload);
  let apiKey;
  if (fixture) {
    apiKey = 'fixture.' + Buffer.from(JSON.stringify({
      'https://api.openai.com/auth': { chatgpt_account_id: 'offline-fixture' },
    })).toString('base64url') + '.not-a-credential';
  } else {
    const { AuthStorage } = await load(path.join(installed.root, 'dist/core/auth-storage.js'));
    const storage = AuthStorage.create(path.join(homedir(), '.pi/agent/auth.json'));
    if (storage.get('openai-codex')?.type !== 'oauth') throw new Error('Pi Codex OAuth login required');
    apiKey = await storage.getApiKey('openai-codex', { includeFallback: false });
    if (!apiKey) throw new Error('Pi Codex OAuth unavailable');
  }
  let sends = 0, raw = '', finalResponse = null, httpStatus = null, payloadSeen = false;
  const rawPath = path.join(directory, 'response.body');
  const fd = fs.openSync(rawPath, 'wx', 0o600);
  const originalFetch = globalThis.fetch;
  const decoder = new TextDecoder();
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  // Dedicated child process: wrapping fetch cannot affect another episode.
  globalThis.fetch = async (url, init) => {
    const target = new URL(url);
    if (target.origin !== 'https://chatgpt.com' || target.pathname !== '/backend-api/codex/responses')
      throw new Error('Unexpected model endpoint');
    if (++sends !== 1 || !payloadSeen) throw new Error('Unexpected second dispatch');
    const bodyBytes = new Headers(init.headers).get('content-encoding') === 'zstd'
      ? zstdDecompressSync(init.body) : Buffer.from(init.body);
    if (bodyBytes.toString('utf8') !== JSON.stringify(payload))
      throw new Error('Provider transport changed the audited payload');
    json(path.join(directory, 'dispatch.json'), { at: new Date().toISOString(), url: String(url),
      request_sha256: sha(bodyBytes), attempt: sends, exact_payload_verified: true });
    let response;
    if (fixture) {
      response = new Response(fixture.body ?? ('data: ' + JSON.stringify({
        type: fixture.response?.status === 'incomplete' ? 'response.incomplete' : 'response.completed',
        response: fixture.response,
      }) + '\n\n'), { status: fixture.status ?? 200,
        headers: { 'content-type': 'text/event-stream' } });
    } else response = await fetchImpl(url, { ...init, redirect: 'error' });
    httpStatus = response.status;
    json(path.join(directory, 'http.json'), { status: response.status,
      retry_after: response.headers.get('retry-after'), request_id: response.headers.get('x-request-id'),
      received_at: new Date().toISOString() });
    if (!response.body) return response;
    const retained = response.body.pipeThrough(new TransformStream({
      transform(chunk, output) {
        fs.writeSync(fd, chunk); raw += decoder.decode(chunk, { stream: true }); output.enqueue(chunk);
      },
      flush() { raw += decoder.decode(); },
    }));
    return new Response(retained, { status: response.status, headers: response.headers });
  };
  let providerError = false;
  try {
    const { stream } = await load(path.join(installed.ai, 'dist/api/openai-codex-responses.js'));
    const events = stream(model, { systemPrompt: '', messages: [] }, {
      apiKey, transport: 'sse', maxRetries: 0, signal: controller.signal,
      timeoutMs: timeout, sessionId: payload.prompt_cache_key,
      onPayload() { payloadSeen = true; return payload; },
    });
    for await (const event of events) {
      // Do not return SDK-generated error strings: they may include HTTP details.
      // Exact provider body is retained without authorization headers.
      if (event.type === 'error') providerError = true;
    }
    const completedItems = new Map();
    for (const frame of raw.split(/\r?\n\r?\n/)) {
      const data = frame.split(/\r?\n/).filter(l => l.startsWith('data:')).map(l => l.slice(5).trimStart()).join('\n');
      if (!data || data === '[DONE]') continue;
      let event;
      try { event = JSON.parse(data); } catch { throw new Error('Malformed provider SSE'); }
      if (event.type === 'response.output_item.done') {
        if (!Number.isInteger(event.output_index) || event.output_index < 0 ||
            completedItems.has(event.output_index) || !event.item)
          throw new Error('Invalid or duplicate completed output item');
        completedItems.set(event.output_index, event.item);
      }
      if (['response.completed', 'response.incomplete', 'response.failed'].includes(event.type)) {
        if (finalResponse) throw new Error('Multiple terminal responses');
        finalResponse = event.response;
      }
    }
    if (finalResponse) json(path.join(directory, 'responses-response.json'), finalResponse);
    // Codex may send authoritative completed items separately, leaving output:[]
    // in response.completed. Assemble only completed items, never partial deltas.
    let assembled = finalResponse;
    if (finalResponse && Array.isArray(finalResponse.output) && !finalResponse.output.length && completedItems.size) {
      const entries = [...completedItems.entries()].sort((a, b) => a[0] - b[0]);
      if (entries.some(([index], i) => index !== i)) throw new Error('Missing completed output item');
      assembled = { ...finalResponse, output: entries.map(([, item]) => item) };
      json(path.join(directory, 'responses-assembled.json'), {
        source: 'response.output_item.done in output_index order', response: assembled,
        raw_terminal_artifact: 'responses-response.json', stream_artifact: 'response.body',
      });
    }
    const result = { version: 1, id, sends, http_status: httpStatus,
      response: assembled, raw_terminal: finalResponse,
      output_source: assembled === finalResponse ? 'terminal_response' : 'completed_stream_items',
      ok: Boolean(finalResponse) && !providerError,
      error: providerError || !finalResponse ? 'Provider stream failed; inspect retained transport artifacts' : null };
    json(path.join(directory, 'transport-result.json'), result);
    return result;
  } finally {
    clearTimeout(timer); globalThis.fetch = originalFetch; fs.closeSync(fd);
  }
}

if (process.argv[1] && fs.existsSync(process.argv[1]) && pathToFileURL(fs.realpathSync(process.argv[1])).href === import.meta.url) {
  let envelope;
  try {
    let input = ''; for await (const chunk of process.stdin) input += chunk;
    envelope = JSON.parse(input);
    const i = process.argv.indexOf('--fixture');
    const fixture = i >= 0 ? JSON.parse(fs.readFileSync(process.argv[i + 1])) : undefined;
    const result = await run(envelope, { fixture });
    process.stdout.write(JSON.stringify(result));
  } catch (error) {
    // Never print credential-bearing exception bodies/stacks from auth libraries.
    process.stdout.write(JSON.stringify({ version: 1, id: envelope?.id, ok: false,
      error: 'External bridge setup/transport failure', error_type: error?.name ?? 'Error' }));
    process.exitCode = 1;
  }
}
