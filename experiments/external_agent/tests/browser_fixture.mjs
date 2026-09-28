/** Offline provider: sees only the mapped request, never the browser or verifier. */
import fs from 'node:fs';
import { run } from '../worker.mjs';
let input = ''; for await (const chunk of process.stdin) input += chunk;
const envelope = JSON.parse(input);
const mode = process.argv[2];
const prior = envelope.payload.input.filter(x => x.type === 'function_call').length;
const context = JSON.stringify(envelope.payload.input);
if (context.includes('PRIVILEGED_SENTINEL')) throw new Error('Private state leaked');
const texts = envelope.payload.input.flatMap(i => typeof i.output === 'string' ? [i.output] :
  (i.content ?? []).filter(p => typeof p.text === 'string').map(p => p.text)).join('\n');
const structured = envelope.payload.tools.some(t => t.name === 'ax_search');
function bid(role, name) {
  const structuredRE = new RegExp('"bid":\\s*"([^"]+)"[^{}]*"name":\\s*"' + name + '"[^{}]*"role":\\s*"' + role + '"', 'g');
  const flatRE = new RegExp('\\[([^\\]]+)\\] ' + role + " '" + name + "'", 'g');
  const matches = [...texts.matchAll(structured ? structuredRE : flatRE)];
  if (!matches.length) throw new Error('Target absent from supplied observation: ' + name);
  return matches.at(-1)[1];
}
const sequence = structured ? ['search-name', 'fill', 'search-save', 'click', 'finish'] : ['fill', 'click', 'finish'];
let name, args;
const step = sequence[prior];
if (mode === 'forbidden') { name = 'bash'; args = { command: 'cat ~/.pi/agent/auth.json' }; }
else if (step === 'search-name') { name = 'ax_search'; args = { query: 'Name', limit: 3 }; }
else if (step === 'search-save') { name = 'ax_search'; args = { query: 'Save', limit: 3 }; }
else if (step === 'fill') { name = 'fill'; args = { bid: bid('textbox', 'Name'), value: 'Ada' }; }
else if (step === 'click') { name = 'click'; args = { bid: bid('button', 'Save') }; }
else if (step === 'finish') {
  if (!texts.includes('Saved Ada')) throw new Error('No saved-state observation delivered');
  name = 'send_msg_to_user'; args = { text: 'Saved Ada.' };
} else throw new Error('Unexpected additional decision');
const response = { id: 'response-' + prior, model: envelope.payload.model, status: 'completed', output: [
  { type: 'reasoning', id: 'reason-' + prior, summary: [], encrypted_content: 'fixture-' + prior },
  { type: 'function_call', id: 'function-' + prior, call_id: 'call-' + prior, name, arguments: JSON.stringify(args) },
], usage: { input_tokens: 100 + prior * 50, output_tokens: 20, total_tokens: 120 + prior * 50,
  input_tokens_details: { cached_tokens: prior ? 64 : 0 }, output_tokens_details: { reasoning_tokens: 5 } } };
const result = await run(envelope, { fixture: { response } });
process.stdout.write(JSON.stringify(result));
