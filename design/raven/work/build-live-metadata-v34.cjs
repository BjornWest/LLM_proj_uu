const fs = require('fs');
const path = require('path');
const vm = require('vm');
const assert = require('assert/strict');

const base = path.resolve(__dirname, '../outputs/raven');
const pairs = [
  ['flight-library-v30.json', 'live-flight-meta-v34.json'],
  ['chat-actions-v26.json', 'live-actions-meta-v34.json'],
  ['chat-idle-v29.json', 'live-idle-meta-v34.json'],
  ['chat-attention-v26.json', 'live-attention-meta-v34.json'],
];
// Remove only atlas/pixel-packing fields; retain complete native pose and timing metadata.
const pixelOnly = new Set(['atlasPages', 'cells', 'poseCells', 'cellCount', 'columns',
  'sourcePattern', 'packing', 'decodedBytesAllPages', 'pixelAliases', 'renderedUniquePoses']);
const removed = {};
function strip(value) {
  if (Array.isArray(value)) return value.map(strip);
  if (!value || typeof value !== 'object') return value;
  const out = {};
  for (const [k, v] of Object.entries(value)) {
    if (pixelOnly.has(k)) { removed[k] = (removed[k] || 0) + 1; continue; }
    out[k] = strip(v);
  }
  return out;
}
const report = { sourceFilesImmutable: true, outputs: [], removedFields: removed };
const manifests = [];
for (const [source, target] of pairs) {
  const bytes = fs.readFileSync(path.join(base, source));
  const original = JSON.parse(bytes);
  const derived = strip(original);
  const encoded = JSON.stringify(derived);
  fs.writeFileSync(path.join(base, target), encoded);
  // No surviving native/semantic field has changed.
  assert.equal(encoded, JSON.stringify(strip(original)));
  report.outputs.push({ source, target, beforeBytes: bytes.length,
    afterBytes: Buffer.byteLength(encoded), clips: Object.keys(derived.clips || {}),
    poses: derived.poses?.length || Object.values(derived.clips || {}).reduce((n, c) => n + c.poses.length, 0) });
  manifests.push([original, derived]);
}
const ctx = { window: {}, console, Math }; vm.createContext(ctx);
vm.runInContext(fs.readFileSync(path.join(base, 'chat-flight-director-v33.js'), 'utf8'), ctx);
const Director = ctx.ChatFlightDirector;
function rng(seed) { return () => { seed = Math.imul(seed ^ seed >>> 15, 1 | seed); seed ^= seed + Math.imul(seed ^ seed >>> 7, 61 | seed); return ((seed ^ seed >>> 14) >>> 0) / 4294967296; }; }
const [original, derived] = manifests[0];
let samples = 0;
for (const [width, height] of [[883, 100], [320, 100]]) {
  for (let seed = 1; seed <= 5; seed++) {
    const config = { left: 0, top: 0, width, height, scale: 26, pad: 2, topPad: 0, preferredSideWidth: 70 };
    const a = new Director({ manifest: original, geometry: config, rng: rng(seed) });
    const b = new Director({ manifest: derived, geometry: config, rng: rng(seed) });
    for (let ms = 0; ms <= 60000; ms += 250) {
      assert.equal(JSON.stringify(a.sample(ms)), JSON.stringify(b.sample(ms)));
      samples++;
    }
  }
}
report.identicalDirectorSamples = samples;
fs.writeFileSync(path.resolve(__dirname, 'live-metadata-v34-report.json'), JSON.stringify(report, null, 2));
console.log(JSON.stringify(report));
