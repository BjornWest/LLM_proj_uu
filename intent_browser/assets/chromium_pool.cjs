/* Local, supervisor-owned Playwright servers. Clients own connections, not processes. */
'use strict';
const fs = require('fs'), http = require('http'), net = require('net');
const crypto = require('crypto'), path = require('path'), Module = require('module');
const config = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const digest = value => crypto.createHash('sha256').update(value).digest('hex');
const id = () => crypto.randomBytes(32).toString('hex');
const fail = message => { throw new Error(message); };
if (digest(fs.readFileSync(__filename)) !== config.manifest.broker_asset_sha256)
  fail('Pool broker source changed');
for (const name of ['maxServers', 'maxLeases', 'perServer', 'pendingSeconds'])
  if (!Number.isInteger(config[name]) || config[name] < 1) fail('Invalid finite cap: ' + name);
if (config.maxServers > 16 || config.maxLeases > 128 || config.perServer > 64 || config.pendingSeconds > 60)
  fail('Pool cap exceeds supported bounds');
if (digest(fs.readFileSync(config.executable)) !== config.manifest.executable_sha256)
  fail('Chromium executable changed');
const packageJson = JSON.parse(fs.readFileSync(path.join(config.package, 'package.json')));
if (packageJson.version !== config.manifest.node_playwright_version) fail('Playwright package changed');
const pw = require(config.package);
// 1.44 launchServer binds all interfaces. Qualify a private in-memory copy of
// its launcher with the single explicit loopback bind; never edit installed files
// or affect another Python environment/Node process.
const launcherPath = path.join(config.package, 'lib/browserServerImpl.js');
const source = fs.readFileSync(launcherPath, 'utf8');
if (digest(source) !== 'ec9822f9ec710f0485024ed1a2d63b9d09903dc8d6daa7b667282f878aadc296')
  fail('Unsupported Playwright server launcher');
const old = 'server.listen(options.port)';
if (source.split(old).length !== 2) fail('Ambiguous loopback patch');
const qualified = new Module(launcherPath, module);
qualified.filename = launcherPath;
qualified.paths = Module._nodeModulePaths(path.dirname(launcherPath));
qualified._compile(source.replace(old, "server.listen(options.port, '127.0.0.1')"), launcherPath);
pw.chromium._serverLauncher = new qualified.exports.BrowserServerLauncherImpl('chromium');

const groups = new Map(), leases = new Map(), ended = new Map();
let closing = false, acquireQueue = Promise.resolve();
function event(kind, fields) {
  fs.appendFileSync(config.events, JSON.stringify({ kind, time: Date.now(), ...fields }) + '\n', { mode: 0o600 });
}
function remember(lease, reason) {
  if (!leases.delete(lease.id)) return;
  lease.group.leases.delete(lease.id);
  clearTimeout(lease.pendingTimer);
  if (lease.inbound) lease.inbound.destroy();
  if (lease.outbound) lease.outbound.destroy();
  ended.set(lease.id, { owner: lease.owner, releaseToken: lease.releaseToken, reason,
    group: lease.group.id, generation: lease.group.generation });
  event('lease_ended', { lease_id: lease.id, owner: lease.owner, role: lease.role,
    group: lease.group.id, generation: lease.group.generation, reason });
  while (ended.size > 256) ended.delete(ended.keys().next().value);
  if (lease.group.state === 'draining' && !lease.group.leases.size) closeGroup(lease.group);
}
async function closeGroup(group) {
  if (group.state === 'closing' || group.state === 'closed') return;
  group.state = 'closing';
  try { await group.server.close(); } finally { group.state = 'closed'; }
}
function launchOptions(raw) {
  if (!raw || Array.isArray(raw) || typeof raw !== 'object') fail('Expected launch options');
  const allowed = new Set(['headless', 'slow_mo', 'args', 'ignore_default_args']);
  if (Object.keys(raw).some(key => !allowed.has(key))) fail('Unsupported launch-level option');
  if (typeof raw.headless !== 'boolean') fail('headless must be explicit');
  if (raw.slow_mo != null && (!Number.isFinite(raw.slow_mo) || raw.slow_mo < 0)) fail('Invalid slow_mo');
  for (const key of ['args', 'ignore_default_args'])
    if (raw[key] != null && (!Array.isArray(raw[key]) || raw[key].some(x => typeof x !== 'string')))
      fail('Invalid ' + key);
  return { headless: raw.headless, slowMo: raw.slow_mo || 0, args: raw.args || [],
    ignoreDefaultArgs: raw.ignore_default_args || [], executablePath: config.executable, timeout: 10000 };
}
async function acquire(body) {
  if (closing) fail('Pool is shutting down');
  if (typeof body.owner !== 'string' || !body.owner || body.owner.length > 128) fail('Invalid owner');
  if (!['task', 'chat'].includes(body.role)) fail('Invalid role');
  if (leases.size >= config.maxLeases) fail('Pool admission capacity reached');
  if ([...leases.values()].some(x => x.owner === body.owner && x.role === body.role))
    fail('Duplicate live owner/role');
  const options = launchOptions(body.options);
  const key = digest(JSON.stringify({ role: body.role, options }));
  let group = [...groups.values()].find(x => x.key === key && x.state === 'ready' && x.leases.size < config.perServer);
  if (!group) {
    for (const [oldId, oldGroup] of groups) {
      if (groups.size <= config.maxServers + 32) break;
      if (['closed', 'crashed'].includes(oldGroup.state)) groups.delete(oldId);
    }
    if ([...groups.values()].filter(x => !['closed', 'crashed'].includes(x.state)).length >= config.maxServers)
      fail('Pool launch-profile/server capacity reached');
    group = { id: id(), generation: id(), key, state: 'starting', leases: new Set() };
    groups.set(group.id, group);
    try { group.server = await pw.chromium.launchServer(options); group.state = 'ready'; }
    catch (error) { group.state = 'closed'; throw error; }
    event('browser_started', { group: group.id, generation: group.generation,
      profile_sha256: key, process_id: group.server.process().pid });
    group.server.on('close', () => {
      const reason = ['closing', 'draining'].includes(group.state) ? 'server_closed' : 'browser_crashed';
      group.state = reason === 'browser_crashed' ? 'crashed' : 'closed';
      event('browser_ended', { group: group.id, generation: group.generation, reason });
      for (const leaseId of [...group.leases]) remember(leases.get(leaseId), reason);
    });
  }
  if (closing) { await closeGroup(group); fail('Pool is shutting down'); }
  const lease = { id: id(), releaseToken: id(), owner: body.owner, role: body.role,
    group, connected: false };
  leases.set(lease.id, lease); group.leases.add(lease.id);
  event('lease_acquired', { lease_id: lease.id, owner: lease.owner, role: lease.role,
    group: group.id, generation: group.generation });
  lease.pendingTimer = setTimeout(() => remember(lease, 'connect_deadline'), config.pendingSeconds * 1000);
  return { lease_id: lease.id, release_token: lease.releaseToken, owner: lease.owner,
    role: lease.role, group: group.id, generation: group.generation, profile_sha256: key,
    endpoint: `ws://127.0.0.1:${proxy.address().port}/${lease.id}`, manifest: config.manifest };
}
const proxy = http.createServer((_req, res) => { res.writeHead(404); res.end(); });
proxy.on('upgrade', (request, inbound, head) => {
  const lease = leases.get(request.url.slice(1));
  if (!lease || lease.connected || lease.group.state !== 'ready' || closing) { inbound.destroy(); return; }
  lease.connected = true; clearTimeout(lease.pendingTimer); lease.inbound = inbound;
  const endpoint = new URL(lease.group.server.wsEndpoint());
  const outbound = net.connect(Number(endpoint.port), '127.0.0.1'); lease.outbound = outbound;
  const finished = () => remember(lease, 'connection_closed_without_release');
  inbound.on('close', finished); inbound.on('error', finished);
  outbound.on('close', finished); outbound.on('error', finished);
  outbound.on('connect', () => {
    const headers = [];
    for (let i = 0; i < request.rawHeaders.length; i += 2) {
      const name = request.rawHeaders[i];
      headers.push(name + ': ' + (name.toLowerCase() === 'host' ? endpoint.host : request.rawHeaders[i + 1]));
    }
    outbound.write(`GET ${endpoint.pathname} HTTP/1.1\r\n${headers.join('\r\n')}\r\n\r\n`);
    if (head.length) outbound.write(head);
    inbound.pipe(outbound); outbound.pipe(inbound);
  });
});

async function shutdown() {
  if (closing) return; closing = true;
  const timer = setTimeout(() => process.exit(1), 15000); timer.unref();
  await acquireQueue;
  for (const lease of [...leases.values()]) remember(lease, 'supervisor_shutdown');
  await Promise.all([...groups.values()].filter(x => x.server).map(closeGroup));
  // Node removes a Unix socket when its HTTP server closes. A second unlink
  // races that cleanup and turns a successful shutdown into an ENOENT failure.
  control.close(); proxy.close();
}
function status() {
  return { version: 'shared-chromium-v1', manifest: config.manifest,
    groups: [...groups.values()].map(x => ({ id: x.id, generation: x.generation,
      profile_sha256: x.key, state: x.state, leases: x.leases.size,
      process_id: x.server ? x.server.process().pid : null })),
    leases: [...leases.values()].map(x => ({ id: x.id, owner: x.owner, role: x.role,
      group: x.group.id, generation: x.group.generation, connected: x.connected })),
    ended: [...ended].map(([leaseId, x]) => ({ id: leaseId, owner: x.owner, reason: x.reason,
      group: x.group, generation: x.generation })) };
}
const control = http.createServer((request, response) => {
  const admin = request.headers.authorization === 'Bearer ' + config.admin_secret;
  if (request.method !== 'POST' || (!admin && request.headers.authorization !== 'Bearer ' + config.secret)) {
    response.writeHead(403); response.end(); return;
  }
  let bytes = 0, chunks = [], aborted = false;
  request.on('aborted', () => { aborted = true; });
  request.on('data', chunk => { bytes += chunk.length; if (bytes > 8192) request.destroy(); else chunks.push(chunk); });
  request.on('end', async () => {
    let result, created;
    try {
      const body = JSON.parse(Buffer.concat(chunks).toString('utf8'));
      if (['/shutdown', '/drain', '/kill', '/contexts'].includes(request.url) && !admin) fail('Supervisor authority required');
      if (request.url === '/acquire') {
        const operation = acquireQueue.then(() => acquire(body));
        acquireQueue = operation.catch(() => {});
        result = await operation; created = leases.get(result.lease_id);
      } else if (request.url === '/release') {
        const lease = leases.get(body.lease_id) || ended.get(body.lease_id);
        if (!lease || lease.owner !== body.owner || lease.releaseToken !== body.release_token)
          fail('Foreign or unknown lease release');
        if (leases.has(body.lease_id)) remember(lease, 'released');
        else if (lease.reason === 'connection_closed_without_release') lease.reason = 'released';
        result = { released: true };
      } else if (request.url === '/status') result = status();
      else if (request.url === '/drain') {
        const group = groups.get(body.group); if (!group || group.state !== 'ready') fail('Unknown/invalid group');
        group.state = 'draining'; if (!group.leases.size) await closeGroup(group); result = { draining: true };
      } else if (request.url === '/kill') {
        const group = groups.get(body.group); if (!group || group.state !== 'ready') fail('Unknown/invalid group');
        await group.server.kill(); result = { killed: true };
      } else if (request.url === '/contexts') {
        const group = groups.get(body.group); if (!group || group.state !== 'ready') fail('Unknown/invalid group');
        const browser = await pw.chromium.connect(group.server.wsEndpoint(), { timeout: 5000 });
        try {
          const session = await browser.newBrowserCDPSession();
          result = await session.send('Target.getBrowserContexts');
          await session.detach();
        } finally { await browser.close(); }
      } else if (request.url === '/shutdown') { result = { shutdown: true };
        setImmediate(() => shutdown().catch(error => { console.error(error.message); process.exit(1); })); }
      else fail('Unknown operation');
      if (aborted || response.destroyed) { if (created) remember(created, 'abandoned_acquire'); return; }
      response.writeHead(200, { 'content-type': 'application/json' }); response.end(JSON.stringify(result));
    } catch (error) {
      if (!response.destroyed) { response.writeHead(409, { 'content-type': 'application/json' });
        response.end(JSON.stringify({ error: error.message.split('\n')[0].slice(0, 300) })); }
    }
  });
});
control.requestTimeout = 15000; control.headersTimeout = 5000;
control.on('error', error => { console.error(error.message); process.exit(1); });
proxy.listen(0, '127.0.0.1', () => control.listen(config.socket, () => {
  fs.chmodSync(config.socket, 0o600);
  fs.writeFileSync(config.ready + '.tmp', JSON.stringify({ version: 'shared-chromium-v1', socket: config.socket,
    secret: config.secret, manifest: config.manifest }), { flag: 'wx', mode: 0o600 });
  fs.renameSync(config.ready + '.tmp', config.ready);
}));
for (const sig of ['SIGTERM', 'SIGINT', 'SIGHUP']) process.on(sig, () => shutdown().catch(() => process.exit(1)));
