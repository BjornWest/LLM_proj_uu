/* Helper ravens share the chat controller's native assets, renderer and clock. */
(function (host, factory) {
  'use strict';
  const api = factory(host);
  if (typeof module === 'object' && module.exports) module.exports = api;
  host.RavenFlock = api.RavenFlock;
})(typeof globalThis === 'object' ? globalThis : this, function (host) {
  'use strict';
  const MAX_RAVENS = 6;
  const clamp = (value, min = 0, max = 1) => Math.max(min, Math.min(max, value));
  const cubic = (a, b, c, d, t) => {
    const u = 1 - t;
    return {
      x: u*u*u*a.x + 3*u*u*t*b.x + 3*u*t*t*c.x + t*t*t*d.x,
      y: u*u*u*a.y + 3*u*u*t*b.y + 3*u*t*t*c.y + t*t*t*d.y
    };
  };

  class RavenFlock {
    constructor({controller, button, clearButton = null, status = null} = {}) {
      if (!controller) throw new TypeError('Supply the shared raven controller.');
      this.controller = controller;
      this.button = button;
      this.clearButton = clearButton;
      this.status = status;
      this.birds = [];
      this.nextId = 1;
      this.disposed = false;
      this.onSpawn = () => this.spawn();
      this.onClear = () => this.clear();
      this.onPageHide = () => this.dispose();
      button?.addEventListener('click', this.onSpawn);
      clearButton?.addEventListener('click', this.onClear);
      host.addEventListener?.('pagehide', this.onPageHide);
      status?.setAttribute('role', 'status');
      status?.setAttribute('aria-live', 'polite');
      this.updateControls();
    }

    updateControls(message = null) {
      const ready = !this.disposed && this.controller.ready && !!this.controller.geometry?.director;
      const count = this.birds.length;
      if (this.button) {
        this.button.disabled = !ready || count >= MAX_RAVENS;
        this.button.title = count >= MAX_RAVENS ? 'The demo supports six helper ravens.' : 'Bring another helper raven into the chat.';
      }
      if (this.clearButton) this.clearButton.disabled = !count;
      if (this.status) {
        this.status.textContent = message || (count ? count + ' helper raven' + (count === 1 ? '' : 's') +
          (count >= MAX_RAVENS ? ' · limit reached' : '') : 'No helper ravens');
      }
    }

    spawn() {
      const controller = this.controller;
      if (this.disposed || !controller.ready || !controller.geometry?.director) {
        this.updateControls('Ravens are still loading.');
        return null;
      }
      if (this.birds.length >= MAX_RAVENS) {
        this.updateControls();
        return null;
      }
      try {
        const Director = host.ChatFlightDirector;
        if (!Director) throw new Error('The flight director is unavailable.');
        const director = new Director({
          manifest: controller.flightManifest,
          geometry: controller.geometry.director,
          direction: Math.random() < .5 ? 1 : -1,
          rng: Math.random,
          knownReplyMs: null
        });
        if (director.blocked) throw new Error('The flight area needs more room.');
        const bird = {
          id: this.nextId++,
          director,
          spawnClock: controller.motionClock,
          entrance: null,
          lastClock: controller.motionClock,
          pausedMs: 0,
          reduced: !!controller.motion?.matches
        };
        this.configureEntrance(bird);
        this.birds.push(bird);
        controller.lastDrawKey = '';
        controller.updateControls?.();
        this.updateControls();
        return bird;
      } catch (error) {
        this.updateControls('Could not spawn a raven: ' + error.message);
        return null;
      }
    }

    configureEntrance(bird, preserveDuration = false) {
      const controller = this.controller, director = bird.director;
      const target = director.entrancePoint;
      const velocity = director.entranceVelocity || {x: director.direction * director.geometry.unitWidth, y: 0};
      const info = director.info(), clip = info.clip.sourceClip || info.name;
      const frame = director.sourceFrameAt(info.clip, 0), pose = controller.pose(clip, frame);
      const scale = director.geometry.scale * (director.entranceDepthScale ?? 1);
      const size = controller.cellSize(pose, scale);
      const left = Math.max(8, (pose.root.x - pose.bounds.left) * size);
      const right = Math.max(8, (pose.bounds.right - pose.root.x) * size);
      const direction = Math.sign(velocity.x) || director.direction;
      const edge = direction < 0 ? controller.geometry.width + left + 2 : -right - 2;
      const speed = Math.max(8, Math.abs(velocity.x));
      const durationMs = preserveDuration && bird.entrance ? bird.entrance.durationMs :
        clamp(Math.abs(target.x - edge) / (speed * 1.125) * 1000, 1000, 7000);
      const seconds = durationMs / 1000;
      const from = {x: edge, y: target.y - velocity.y * seconds};
      bird.entrance = {
        clip, frame, from,
        first: {x: from.x + velocity.x * 1.25 * seconds / 3, y: from.y + velocity.y * seconds / 3},
        second: {x: target.x - velocity.x * seconds / 3, y: target.y - velocity.y * seconds / 3},
        target: {...target}, velocity: {...velocity}, durationMs,
        depthScale: director.entranceDepthScale ?? 1,
        flightRotation: director.poseAt(info.name, 0).flightRotation
      };
    }

    resize() {
      const geometry = this.controller.geometry?.director;
      if (!geometry || this.disposed) return;
      for (const bird of this.birds) {
        bird.director.configure(geometry);
        // Configure preserves the native origin, queued route and phase. Only
        // an unfinished edge approach needs a new screen-space projection.
        const elapsed = bird.lastClock - bird.spawnClock - bird.pausedMs;
        if (elapsed < bird.entrance.durationMs && !bird.director.blocked)
          this.configureEntrance(bird, true);
      }
      this.controller.lastDrawKey = '';
    }

    renderOptions(sample, scale) {
      const controller = this.controller;
      const pose = controller.pose(sample.clip, sample.frame);
      const options = {
        ...sample,
        frame: controller.nativeFrame(sample.clip, sample.frame),
        size: controller.cellSize(pose, scale * (sample.depthScale ?? 1)),
        anchor: sample.anchor || 'root',
        point: {...sample.point},
        darker: !!controller.darker?.checked,
        attentionPose: null,
        blink: false,
        blendWeight: sample.blendWeight ?? 1
      };
      options.blendFrom = sample.blendFrom ? this.renderOptions({...sample.blendFrom, blendFrom: null}, scale) : null;
      return options;
    }

    staticSample(bird, index) {
      const geometry = this.controller.geometry, sky = geometry.director;
      const scale = bird.director.geometry.scale;
      const pose = this.controller.pose('idle', 0), size = this.controller.cellSize(pose, scale);
      const footprint = Math.max(12, (pose.bounds.right - pose.bounds.left) * size);
      const left = sky.left + (pose.root.x - pose.bounds.left) * size + 8;
      const right = sky.left + sky.width - (pose.bounds.right - pose.root.x) * size - 8;
      const span = Math.max(0, right - left);
      // Fixed slots do not move existing helpers when another one is spawned.
      const slot = (index + .5) / MAX_RAVENS;
      const x = left + span * slot;
      const top = sky.top + (pose.root.y - pose.bounds.top) * size + 8;
      const bottom = sky.top + sky.height - (pose.bounds.bottom - pose.root.y) * size - 8;
      const row = footprint * MAX_RAVENS > sky.width ? index % 2 : 0;
      return this.renderOptions({clip: 'idle', frame: 0, anchor: 'root',
        point: {x, y: clamp(top + row * size * .4, top, Math.max(top, bottom))}}, scale);
    }

    samples(clock = this.controller.motionClock) {
      if (this.disposed || !this.controller.ready) return [];
      const reduced = !!this.controller.motion?.matches;
      return this.birds.map((bird, index) => {
        const now = Math.max(bird.lastClock, Number.isFinite(clock) ? clock : bird.lastClock);
        // Resume the same flight phase if reduced motion is toggled off.
        if (bird.reduced || reduced || bird.director.blocked) bird.pausedMs += now - bird.lastClock;
        bird.lastClock = now;
        bird.reduced = reduced;
        if (reduced) return this.staticSample(bird, index);
        const elapsed = Math.max(0, now - bird.spawnClock - bird.pausedMs), e = bird.entrance;
        const sample = elapsed < e.durationMs ? {
          clip: e.clip, frame: e.frame, anchor: 'root',
          depthScale: e.depthScale, flightRotation: e.flightRotation,
          point: cubic(e.from, e.first, e.second, e.target, clamp(elapsed / e.durationMs))
        } : bird.director.sample(elapsed - e.durationMs);
        return this.renderOptions(sample, bird.director.geometry.scale);
      });
    }

    clear() {
      this.birds.length = 0;
      this.controller.lastDrawKey = '';
      this.controller.updateControls?.();
      this.updateControls();
    }

    dispose() {
      if (this.disposed) return;
      this.disposed = true;
      this.button?.removeEventListener('click', this.onSpawn);
      this.clearButton?.removeEventListener('click', this.onClear);
      host.removeEventListener?.('pagehide', this.onPageHide);
      this.clear();
    }
  }

  return {RavenFlock};
});
