# Integrating the Raven prototype

> These notes describe the original imported prototype. The full-page v42 entry now uses the backend API; see [current integration and acceptance](raven-backend-chat-handoff.md). The compact v40 demo retains the original behavior described here.

This describes the imported snapshot at [`design/raven/`](../../design/raven/). It is an uncommitted asset and source handoff. The demo is not connected to the repository's harness, model, session store, or retailer environment.

## Runtime layers

The current full-page entry is [`chat-fullpage-v42.html`](../../design/raven/outputs/raven/chat-fullpage-v42.html), with [`chat-fullpage-v42.css`](../../design/raven/outputs/raven/chat-fullpage-v42.css). Its DOM IDs and script order are part of the current prototype contract.

| Module | Surface | Responsibility |
| --- | --- | --- |
| `chat-demo-fullpage-v42.js` | `window.ravenChatDemo` | Page controller, main Raven state, canvas placement, messages, input, timers, and animation loop |
| `raven-live-v42.js` | `window.RavenLive` | Native motion-bank loading and live geometry rendering |
| `chat-flight-director-live-v36.js` | `window.ChatFlightDirector` | Constrained, randomized flight sequence composition |
| `raven-flock-v42.js` | `window.RavenFlock` | Shared-renderer helper Raven management |
| `raven-idle-gaze-v38.js` | `window.RavenIdleGaze` | Random idle head targets and smooth pointer attention |
| `chat-messages-v33.js` | `window.RavenMessages` | Sanitized GFM Markdown and website link previews |
| `raven-citations-v40.js` | `window.RavenCitations` | Message-scoped captured-evidence cards |
| `raven-web-activity-v39.js` | `window.RavenWebActivity` | Current website label, favicon, and progress dot |
| `raven-web-activity-demo-v39.js` | `window.RavenWebActivityDriver` | Demo browsing schedule and an explicit-event bridge |
| `fullpage-conversations-v41.js` | DOM initialization and an `appendMessage` wrapper | Local history, drafts, search, sidebar, and conversation switching |

These are browser scripts rather than a packaged component library. The controller class itself is lexical; its instance is assigned to `window.ravenChatDemo` on `DOMContentLoaded`. Mounting requires the expected page elements. Do not initialize the existing page scripts twice.

The extension-shaped entry [`chat-live-v40.html`](../../design/raven/outputs/raven/chat-live-v40.html) instead uses `chat-demo-live-v40.js` and `raven-live-v38.js`. It has neither the full-page history layer nor the v42 flock. Both designs retain the same accepted native character and animation family.

## Main controller and lifecycle

Useful current methods and properties on `window.ravenChatDemo`:

```js
controller.ready;                 // Asset loading completed successfully.
controller.state;                 // Current visual state.
controller.start({ replyMs });    // DEMO: consumes input and schedules a fixture reply.
controller.submit();              // Alias of start().
controller.appendMessage(markdown, 'Raven', { sources: [], follow: false });
controller.setConversation([{ who: 'You', text: 'Hello', sources: [] }], {
  title: 'Conversation title'
});
controller.cancelTask({ announce: true });
controller.pet();
await controller.setFrameRate(120);
controller.getStats();
```

`appendMessage` accepts `who` values `You` and `Raven`. It renders Markdown, then evidence citations. If the reader is near the bottom, it follows the new message; otherwise it preserves the scroll position and exposes the new-reply button. `follow: true` explicitly follows. The history layer wraps this method to persist raw Markdown and sources.

`setConversation` first cancels the main task and clears all helper Ravens, then renders the supplied messages. `cancelTask` stops the visual task immediately and returns to idle; it does not cancel a real backend job. It also clears helpers and dismisses open evidence/preview cards and activity.

The ordinary visual lifecycle is:

```text
loading → idle → takeoff → entering → working → diving → cawing
                  ↑         task running                  ↓ typing
                  └──────────────────────────────────── idle
```

Petting and settling are additional resting states. `setState()` updates labels and datasets; directly setting `working` does not create a flight director, establish clocks, or start a task.

The controller dispatches bubbling events from `#chat-scene`:

| Event | Current detail |
| --- | --- |
| `raven-chat-submit` | `{ replyMs }` |
| `raven-chat-reply` | `{ message }` |
| `raven-chat-land` | No payload |
| `raven-chat-cancel` | No payload |
| `raven-conversation-change` | `{ title, messageCount }` |
| `raven-chat-pet`, `raven-chat-roll` | No payload |
| `raven-chat-turn` | `{ direction }` |

These are prototype UI events. Submit currently has no message text, conversation ID, run ID, or transport handle.

## Replacing demo completion with the harness

Do this as a deliberate implementation change; there is no existing production `completeTask(payload)` API.

1. Separate submission from the timer. `start()` consumes composer text and appends the user message; `launch()` creates the task clocks and arms `replyTimer`. Capture the submitted text and assign conversation/run IDs before clearing the composer.
2. Remove both automatic completion paths: `launch()` calls `setTimeout(() => this.reply(), replyMs)`, and `sample()` also calls `reply()` once elapsed time reaches `replyMs`. Clearing only the timer does not disable the latter.
3. Keep indefinite flight while the actual harness works. Remove the demo's known-reply forecast assumptions rather than passing an arbitrary huge timer as the production contract.
4. Split `reply()` into a payload-driven completion method. Replace `RavenShoppingDemo.response` and `.sources` with the harness's Markdown and captured sources. Preserve its existing continuous return, pending-return handling during takeoff, and preloading/landing behavior.
5. Connect Stop to the harness's cancellation mechanism as well as `cancelTask()`. Ignore late output for canceled runs or conversations no longer active. Define how failures and follow-up questions should change visual state; the demo does not provide a complete protocol for those cases.
6. Replace the local history wrapper with the application's authoritative conversation store, or explicitly make the wrapper an adapter. Avoid appending a result once through transport and again through replay.

A possible **new adapter boundary**, to implement rather than assume exists, is:

```ts
type AgentReply = {
  runId: string;
  conversationId: string;
  markdown: string;
  sources: CapturedSource[];
};

// Proposed integration methods, not shipped APIs:
startTask({ runId, conversationId, text });
completeTask(reply: AgentReply);
cancelTask({ runId });
```

`message_to_user` output can supply the complete Markdown/sources payload at once; token streaming is not required by the visual design.

## Renderer API

[`raven-live-v42.js`](../../design/raven/outputs/raven/raven-live-v42.js) installs `RavenLive` globally. Loading it as a module does not give named ES exports; use its global API or adapt it deliberately.

```js
const live = await RavenLive.load({
  canvas,
  url: 'live-raven-v34.json',
  // Optional: binaryUrl, threeURL, THREE, fetch, signal, warmClip, onProgress.
});
live.resize(widthInCssPixels, heightInCssPixels, devicePixelRatio);
const result = live.render({
  clip: 'idle', frame: 0, size: 200,
  point: { x: 120, y: 160 }, anchor: 'contact',
  darker: true
});
live.hitTest(xInCanvasCssPixels, yInCanvasCssPixels);
live.getStats();
live.dispose();
```

`load()` fetches the metadata, its `binary.uri`, and vendored `vendor-v34/three.module.js` unless supplied with `THREE`. The existing controller supplies explicit asset URLs relative to the demo page. Keep this resolution in mind when moving it into a bundler or a different asset base.

`render()` accepts fractional frames and interpolates mesh geometry, local positions/scales, and quaternions. It does not crossfade raster images. Additional options used by the controller include `flightRotation`, `attentionPose`, `blink`, `petHeadPose`, `petIdleFrame`, `petStartBlink`, `blendFrom`, and `blendWeight`. Preserve the controller's normalization of clip-local frames, native frames, size, anchors, and placement when reusing these features.

Results include projected `pose`, `markers`, actual `bounds`, source rectangle, clip/frame, and timing data. `warm(clip)` prepares a rig. `RavenLive.create({ meta, binary, THREE, canvas, ... })` creates directly from already loaded data; `MotionBank` and `LiveRenderer` are also exposed for lower-level use.

`renderBatch(optionsArray)` draws several Ravens using one context, bank, and rig buffers. Its results follow input order. The first bird is restored for `hitTest()` afterward, so the current page pets only the main Raven. Each bird has independent camera placement; the renderer clears depth between birds, yielding painter ordering rather than full world-space flock occlusion.

## Flight and helper APIs

```js
const director = new ChatFlightDirector({
  manifest: flightManifest, geometry,
  rng: Math.random, direction: -1,
  knownReplyMs: null
});
director.configure(updatedGeometry);
const sample = director.sample(elapsedMilliseconds);
director.requestReturn(elapsedMilliseconds);
director.getStats();
```

The director composes routes inside a world perimeter, projects them into the available screen area, and reserves space for turns/return. Its default weighted choices favor side views and swerves while allowing angled routes. Far-depth scale defaults to 80%. The returned sample includes clip/frame, screen point, depth scale, and orientation/blend information. Use the controller's native-frame conversion before rendering.

```js
const flock = new RavenFlock({ controller, button, clearButton, status });
const bird = flock.spawn();       // Bird object with numerical id, or null.
const renderOptions = flock.samples(controller.motionClock);
flock.resize();
flock.clear();
flock.dispose();
```

The shipped limit is **six helpers plus the main Raven**. Helpers arrive from randomly chosen left/right edges and have independent directors; they reuse the main assets, renderer, and motion clock. They continue flying after the main Raven lands. Canceling or switching the main conversation clears them.

The flock currently has no real agent-ID map, per-helper removal/completion, labels, collision avoidance, or helper click interaction. Add those intentionally when wiring subagents. Clearing a visual helper does not cancel a backend agent.

`RavenIdleGaze` accepts `{ rng, intervalMs, turnMs, pointerResponseMs }`. Defaults are approximately a 5-second target cadence, 187.5 ms turn, and 119 ms pointer response. Its `reset()`, `sample(now, pointerPose, orbitTarget)`, `release()`, and `getState()` operate on `[tilt, pitch, yaw]` poses. Releasing attention holds the current pose until a later idle tick.

## Markdown and website links

`RavenMessages.renderMessage(element, markdown)` uses vendored Marked and DOMPurify. It supports GFM tables, headings, lists, code, task checkboxes, images, and links with an allowlist sanitizer. Missing dependencies or input over 100,000 characters falls back to plain text. Remote Markdown images are sent through the image proxy. Do not replace this with unsanitized `innerHTML`.

```js
RavenMessages.configure({
  previewEndpoint: '/api/link-preview',
  imageEndpoint: '/api/link-preview-image',
  hoverDelay: 260
});
RavenMessages.renderMessage(element, '## Result\n\nSee [the shop](https://shop.example/item).');
RavenMessages.hidePreview();
```

Hover/focus website previews fetch metadata through the same-origin backend. They are distinct from captured citation cards, which do not fetch evidence again.

## Captured-evidence schema

Render Markdown first, then call `RavenCitations.enhance(element, sources)`, or pass `sources` through `appendMessage()`. A marker such as `[[offer-1]]` references a source ID within that message.

```json
{
  "markdown": "The item is €149 [[offer-1]], plus €19 delivery [[delivery-1]].",
  "sources": [
    {
      "id": "offer-1",
      "kind": "offer",
      "siteName": "Example retailer",
      "title": "Product · variant · condition",
      "url": "https://retailer.example/item",
      "metric": { "value": "€149", "label": "Item price" },
      "facts": [{ "label": "Availability", "value": "In stock" }],
      "evidence": "Captured text supporting this specific claim.",
      "checkedAt": "2026-10-19T10:00:00+02:00",
      "checkedLabel": "Checked at 10:00",
      "illustrative": false
    },
    {
      "id": "delivery-1",
      "kind": "delivery",
      "siteName": "Example retailer",
      "title": "Delivery quote for the specified destination",
      "metric": { "value": "€19", "label": "Shipping" },
      "facts": [{ "label": "Destination", "value": "The user's quoted area" }],
      "evidence": "Captured delivery quote and its applicable basket/destination."
    }
  ]
}
```

This is an illustrative payload, not a real retailer quote. Supported source fields are:

| Field | Shape |
| --- | --- |
| `id` | Unique within the message, matching `^[A-Za-z0-9][\w:.-]{0,79}$` |
| `kind` | `offer`, `delivery`, `review`, `history`, or `calculation` |
| `siteName`, `title`, `context` | Display strings |
| `url`, `favicon` | Optional HTTP(S) URLs |
| `metric` | `{ value: string, label: string }` |
| `facts` | Up to 12 `{ label, value }` display pairs |
| `evidence` | Captured text, capped at 12,000 characters |
| `checkedAt`, `checkedLabel` | Stored timestamp string and human-facing label; no automatic freshness calculation |
| `illustrative` | `true` only for explicitly illustrative data |
| `inputs` | For calculations: up to 12 `{ sourceId, label, value }` entries |
| `history` | Optional `{ points: number[], startLabel, endLabel, unit }`; 2–365 finite points |

The renderer accepts up to 128 sources; the local-history wrapper retains only 32 per message. Unknown markers remain visible as text. Markers inside code, links, or buttons are not enhanced. Source numbers are scoped to each message; calculation markers show `Σ`. Metric and input values are display strings, not an arithmetic engine.

Cards use a fixed body portal and preserve focus/scroll rather than inserting a panel into history. `RavenCitations.hide()` dismisses them. Sources are captured snapshots, not a promise of current price or availability. The included [`shopping-demo-v40.js`](../../design/raven/outputs/raven/shopping-demo-v40.js) shows every supported kind using fictional data and fictional capture destinations.

## Current website activity

The event bridge listens on `document`:

```js
document.dispatchEvent(new CustomEvent('raven-web-activity', {
  detail: { url: 'https://retailer.example/item', label: 'Example retailer' }
}));
document.dispatchEvent(new CustomEvent('raven-web-activity', {
  detail: { status: 'complete' } // Also supports active: false.
}));
```

A real event clears pending demo browsing events. For integration, remove the bridge's `beginDemo()` response to every submit and dispatch actual harness navigation events instead. The standalone class has `start({ url, label, demo: false })`, `finish()`, `reset()`, `getState()`, and `dispose()`, with required icon/site/label elements. The dot pulses while active; metadata/favicons are best effort.

## Preview backend contract

[`server.py`](../../design/raven/outputs/raven/server.py) serves:

```text
GET /api/link-preview?url=ENCODED_HTTP_URL
→ { status: "ok" | "unavailable", url, title, description, siteName, image, favicon }

GET /api/link-preview-image?url=ENCODED_IMAGE_URL
→ Validated image bytes, or an unavailable/error response.
```

The default paths are root-relative even if the assets are mounted below a path. `RavenMessages.configure()` changes the message preview endpoints; the activity widget currently uses the root endpoints directly.

The local server checks public HTTP(S) destinations, redirects and resolved IPs; bounds request duration, response size and concurrency; and caches responses. It is localhost-only preview tooling, not a production service with authentication or tenant isolation. Preserve equivalent protections in any production backend. Browser extension adoption also needs deliberate CSP, asset loading, WebGL, and backend-origin handling.

## Persistence, performance, and cleanup

The full-page demo's localStorage key is `raven-fullpage-conversations-v41`. Stored JSON has this shape:

```ts
{
  version: 1,
  activeId: string,
  threads: Array<{
    id: string; title: string; draft: string;
    createdAt: number; updatedAt: number; // Epoch milliseconds.
    messages: Array<{ who: 'You' | 'Raven'; text: string; sources: CapturedSource[] }>;
  }>
}
```

Caps are 30 conversations, 120 messages per conversation, 30,000 text characters per stored message, 8,000 draft characters, and roughly two million serialized characters. It is local to the serving browser origin; it is not synchronized with the harness or another preview port.

The native timelines are generally 60 fps; geometry is sampled more sparsely and continuously interpolated. Render targets are 8, 24, 60, 120, or 144 fps, limited by requestAnimationFrame, the display, and GPU/CPU performance. Device pixel ratio is capped at two. Several Ravens still add geometry/render work even though their context and assets are shared. `getStats()` and the canvas's diagnostic datasets expose measured frame rate and CPU submission timing; a target is not a hardware guarantee.

Hidden documents stop drawing and pause the motion clock; the demo reply timer remains a wall-clock timer. The motion step is capped at 250 ms after stalls. Reduced-motion mode shows static resting/helper poses and disables petting/head tracking.

`RavenLive.dispose()`, `RavenFlock.dispose()`, and activity cleanup exist. The page controller has **no `destroy()` method** and registers anonymous window/document listeners, a ResizeObserver, RAF, and timers. Refactor cleanup before using it as a repeatedly mounted SPA component. Keep one active controller/RAF owner rather than duplicating page initialization.

Subsequent implementation must follow [`AGENTS.md`](../../AGENTS.md), including independent cross-family commit review before adoption handoff or integration. This imported snapshot creates no commits and supplies no such approval.
