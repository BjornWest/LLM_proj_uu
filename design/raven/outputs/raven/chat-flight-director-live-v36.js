/* Native routes with a short, continuous interruption when a reply is ready. */
(function (host, factory) {
  'use strict';
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else host.ChatFlightDirector = api.ChatFlightDirector;
})(typeof globalThis === 'object' ? globalThis : this, function () {
  'use strict';
  const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));
  const sideOf = h => h[0] === 'l' ? 'l' : 'r';
  const directionOf = h => sideOf(h) === 'r' ? 1 : -1;
  const distance = (a, b) => Math.hypot(a.x - b.x, a.z - b.z);
  const yawDifference = (a, b) => Math.atan2(Math.sin(a - b), Math.cos(a - b));
  const ease = u => {u = clamp(u); return u*u*u*(10+u*(-15+6*u));};
  const headings = {r: 0, ra: Math.PI * 25 / 180, rt: -Math.PI * 25 / 180,
    l: Math.PI, la: Math.PI * 155 / 180, lt: Math.PI * 205 / 180};
  const labels = {soar_forward: 'Soaring', soar_backward: 'Riding the wind',
    connect: 'Changing course', turn: 'Turning', wingbeats: 'Two wingbeats',
    roll: 'Rolling', swerve:'Swerving', entry: 'Entering', exit: 'Returning'};

  class ChatFlightDirector {
    constructor({manifest, geometry, rng = Math.random, direction = -1,
      weights, knownReplyMs = null} = {}) {
      if (!manifest?.clips) throw new TypeError('Supply the native flight library.');
      this.manifest = manifest; this.clips = manifest.clips; this.rng = rng;
      this.weights = {side:.35,swerve:.40,diagonal:.20,curve:.05,...weights};
      this.plane = {...{minX: -8, maxX: 8, minZ: -8, maxZ: 8}, ...manifest.composition?.plane};
      if (!Object.values(this.plane).every(Number.isFinite) ||
        this.plane.minX >= this.plane.maxX || this.plane.minZ >= this.plane.maxZ)
        throw new TypeError('Supply a finite airspace perimeter.');
      this.headingAngles = {...headings};
      for (const [id, info] of Object.entries(manifest.headings ?? {})) {
        if (!Number.isFinite(info.yaw)) throw new TypeError('Invalid native heading ' + id);
        this.headingAngles[id] = info.yaw;
      }
      this.farScale = clamp(manifest.composition?.farScale ?? .8, .4, 1);
      this.catalog = new Map(); this.outgoing = new Map();
      this.history = []; this.plan = []; this.startMs = 0; this.joins = 0;
      this.done = false; this.returnRequested = false; this.lastSampleMs = 0;
      this.knownReplyMs = Number.isFinite(knownReplyMs) ? knownReplyMs : null;
      this.holding = null; this.nextRollMs = 28000 + this.random() * 22000;
      this.hasAngledRoute = false; this.sideOnlyPlannedMs = 0;
      this.sideOnlyLimitMs = 12000; this.forcedAngleChoices = 0;
      this.depthVisits = [0, 0, 0, 0, 0];
      this.depthTarget = this.plane.maxZ - .8;
      this.compile(); this.compileEdgeCruises(); this.compileSwerves(); this.configure(geometry);
      this.heading = direction === 1 ? 'r' : 'l';
      const entry = this.find('entry', null, this.heading);
      this.current = entry?.name ?? this.find('soar_forward', this.heading, this.heading)?.name;
      if (!this.current) throw new RangeError('No initial flight action for ' + this.heading);
      this.origin = this.initialOrigin();
      this.queueFrom(this.endState());
    }

    random() { return clamp(Number(this.rng()) || 0, 0, 1 - Number.EPSILON); }
    get direction() { return directionOf(this.heading); }
    get next() {
      if (this.promptReturn) return this.promptReturn.phases[this.promptReturn.index + 1]?.name ?? null;
      return this.plan[0]?.name ?? null;
    }
    get baseSteps() { return this.origin.x; }
    get entrancePoint() { return this.point(this.current, 0, this.origin); }
    get entranceDepthScale() { return this.depthScale(this.origin.z); }
    get entranceVelocity() { return this.velocity(this.current, 0, this.origin); }

    compile() {
      for (const [name, clip] of Object.entries(this.clips)) {
        if (!clip.poses?.length || clip.poses.length !== clip.frames || !Number.isInteger(clip.frames) ||
          clip.frames < 2 || !Number.isFinite(clip.fps) || clip.fps <= 0 ||
          !Number.isFinite(clip.duration ?? clip.frames / clip.fps) || (clip.duration ?? clip.frames / clip.fps) <= 0)
          throw new TypeError('Flight poses are missing for ' + name);
        const action = clip.action;
        const startHeading = clip.startHeading, endHeading = clip.endHeading;
        if (!action || !startHeading || !endHeading)
          throw new TypeError('Flight junction metadata is missing for ' + name);
        if (!['entry', 'exit'].includes(action) &&
          (!Number.isFinite(this.headingAngles[startHeading]) || !Number.isFinite(this.headingAngles[endHeading])))
          throw new TypeError('Unknown rendered flight heading for ' + name);
        const first = clip.poses[0], last = clip.poses.at(-1);
        for (const p of clip.poses) if (!p.route || !p.root || !p.bounds ||
          ![p.route.x, p.route.z, p.route.yaw, p.route.vx, p.route.vz, p.route.curvature,
            p.root.x, p.root.y, p.bounds.left, p.bounds.right, p.bounds.top, p.bounds.bottom,
            p.orthoScale].every(Number.isFinite) || p.orthoScale <= 0 ||
          p.bounds.left >= p.bounds.right || p.bounds.top >= p.bounds.bottom)
          throw new TypeError('Invalid route or silhouette in ' + name);
        if (Math.hypot(first.route.x, first.route.z) > 1e-8)
          throw new Error('Flight routes must start at a local origin: ' + name);
        if (!['entry', 'exit'].includes(action) &&
          (Math.abs(yawDifference(first.route.yaw, this.headingAngles[startHeading])) > 1e-6 ||
           Math.abs(yawDifference(last.route.yaw, this.headingAngles[endHeading])) > 1e-6))
          throw new Error('The route heading does not match its rendered junction: ' + name);
        const info = {name, clip, action, startHeading, endHeading,
          delta: {x: last.route.x, z: last.route.z},
          durationMs: (clip.duration ?? clip.frames / clip.fps) * 1000};
        this.catalog.set(name, info);
        if (!this.outgoing.has(startHeading)) this.outgoing.set(startHeading, []);
        this.outgoing.get(startHeading).push(info);
      }
      this.extents = {left: 0, right: 0, up: 0, down: 0, windMin: 0, windMax: 0};
      for (const info of this.catalog.values()) for (const p of info.clip.poses) {
        const e = this.extents, s = p.orthoScale;
        e.left = Math.max(e.left, (p.root.x - p.bounds.left) * s);
        e.right = Math.max(e.right, (p.bounds.right - p.root.x) * s);
        e.up = Math.max(e.up, (p.root.y - p.bounds.top) * s);
        e.down = Math.max(e.down, (p.bounds.bottom - p.root.y) * s);
        e.windMin = Math.min(e.windMin, p.motion?.y ?? 0);
        e.windMax = Math.max(e.windMax, p.motion?.y ?? 0);
      }
      // Ordinary routes must fit at every depth. Large wingbeats and rolls
      // instead use the exact per-frame corridor check before being selected.
      this.coreExtents = {up: 0, down: 0};
      for (const info of this.catalog.values()) {
        if (['wingbeats', 'roll'].includes(info.action)) continue;
        for (const p of info.clip.poses) {
          this.coreExtents.up = Math.max(this.coreExtents.up, (p.root.y - p.bounds.top) * p.orthoScale);
          this.coreExtents.down = Math.max(this.coreExtents.down, (p.bounds.bottom - p.root.y) * p.orthoScale);
        }
      }
      this.sideFootprint = Math.max(...['r', 'l'].map(side => {
        const pose = this.find('soar_forward', side, side)?.clip.poses[0];
        return pose ? (pose.bounds.right - pose.bounds.left) * pose.orthoScale : 0;
      }));
    }

    find(action, startHeading = null, endHeading = null) {
      return [...this.catalog.values()].find(i => i.action === action &&
        (startHeading === null || i.startHeading === startHeading) &&
        (endHeading === null || i.endHeading === endHeading));
    }
    compileEdgeCruises() {
      this.edgeCruises = new Map();
      for (const side of ['r', 'l']) {
        const steady = this.find('soar_forward', side, side);
        if (!steady) continue;
        const source = steady.clip.poses[0], direction = directionOf(side), choices = [];
        for (let units = 1; units <= 5; units++) {
          const fps = steady.clip.fps, frames = units * fps + 1, name = 'edge_cruise_' + side + '_' + units;
          // A canonical pose is a genuine native mesh, already scanning down.
          // Holding it for a short coast lets the raven reach a boundary when
          // a whole six-unit animation no longer fits. Both ends are exact
          // native junctions, so the following banked turn has no pose cut.
          const sourceFrames = Array.from({length:frames}, (_, i) =>
            Math.min(fps*2,units*fps*25/60)*Math.sin(Math.PI*i/(frames-1))**2);
          const poses = Array.from({length:frames}, (_, i) => {
            const native = this.poseAt(steady.name,sourceFrames[i]);
            return {...native,route:{...source.route,
              x:direction * units * i / (frames - 1),z:0,yaw:this.headingAngles[side],
              vx:direction,vz:0,speed:1,curvature:0}};
          });
          const clip = {...steady.clip,frames,fps,duration:units,poses,
            sourceClip:steady.name,sourceFrames};
          const info = {name,clip,action:'soar_forward',startHeading:side,endHeading:side,
            delta:{x:direction * units,z:0},durationMs:units * 1000};
          this.catalog.set(name,info); choices.push(info);
        }
        this.edgeCruises.set(side,choices);
      }
    }
    compileSwerves() {
      this.swerves=new Map();
      const depthSign=this.manifest.camera?.depthYawSign??1;
      const bob=.038,oldWindMin=this.extents.windMin;
      const envelope=u=>ease(u/.16)*ease((1-u)/.16);
      const path=(u,direction,sign)=>{
        const gate=envelope(u),phase=4*Math.PI*u;
        return {x:direction*(6*u+.12*gate*(1-Math.cos(phase))),
          z:sign*.42*gate*Math.sin(phase),bob:-bob*gate*Math.sin(phase)**2};
      };
      for(const side of ['r','l']) {
        const steady=this.find('soar_forward',side,side);if(!steady)continue;
        const direction=directionOf(side),base=this.headingAngles[side],variants=[];
        for(const sign of [-1,1]) {
          const name='swerve_'+side+'_'+(sign>0?'away':'toward');
          const poses=steady.clip.poses.map((source,f)=>{
            const u=f/(steady.clip.frames-1),p=path(u,direction,sign),h=1e-4;
            const a=path(Math.max(0,u-h),direction,sign),b=path(Math.min(1,u+h),direction,sign);
            const span=Math.min(1,u+h)-Math.max(0,u-h);
            let vx=(b.x-a.x)/(span*6),vz=(b.z-a.z)/(span*6),curvature=0;
            if(f>0&&f<steady.clip.frames-1) {
              const ax=(b.x-2*p.x+a.x)/(h*h*36),az=(b.z-2*p.z+a.z)/(h*h*36);
              curvature=(vx*az-vz*ax)/Math.max(1e-8,(vx*vx+vz*vz)**1.5);
            }else {vx=direction;vz=0;}
            const yaw=base+yawDifference(Math.atan2(vz,vx),base);
            const flightRotation={yaw:depthSign*yawDifference(yaw,base),
              bank:-depthSign*.23*Math.tanh(curvature/.65)};
            const e=this.extents,c=this.coreExtents,s=source.orthoScale;
            // Native turn samples already include the same full azimuth range
            // and larger banks. Their common silhouette envelope bounds this
            // additional shallow yaw/roll conservatively, including the head.
            const bounds={left:source.root.x-e.left/s,right:source.root.x+e.right/s,
              top:source.root.y-c.up/s,bottom:source.root.y+c.down/s};
            return {...source,bounds,flightRotation,motion:{...source.motion,y:(source.motion?.y??0)+p.bob},
              route:{...source.route,x:p.x,z:p.z,yaw,vx,vz,speed:Math.hypot(vx,vz),curvature}};
          });
          const clip={...steady.clip,action:'swerve',poses,sourceClip:steady.name};
          const info={name,clip,action:'swerve',startHeading:side,endHeading:side,
            delta:{x:direction*6,z:0},durationMs:steady.durationMs};
          this.catalog.set(name,info);variants.push(info);
        }
        this.swerves.set(side,variants);
      }
      this.extents.windMin=oldWindMin-bob;
    }
    info(name = this.current) {
      const result = this.catalog.get(name);
      if (!result) throw new RangeError('Unknown native flight action ' + name);
      return result;
    }
    sourceFrameAt(clip,frame) {
      if (!clip.sourceFrames) return frame;
      const f=clamp(frame,0,clip.frames-1),i=Math.floor(f),t=f-i;
      return clip.sourceFrames[i]+(clip.sourceFrames[Math.min(i+1,clip.frames-1)]-clip.sourceFrames[i])*t;
    }
    poseAt(name,frame){const c=this.info(name).clip,f=Math.max(0,Math.min(c.frames-1,frame)),i=Math.floor(f),a=c.poses[i],b=c.poses[Math.min(c.frames-1,i+1)],t=f-i;
      if(t<1e-9)return a;
      const lerp=(x,y)=>typeof x==='number'&&typeof y==='number'?x+(y-x)*t:x&&typeof x==='object'?Object.fromEntries(Object.entries(x).map(([k,v])=>[k,lerp(v,y?.[k])])):x;
      return lerp(a,b);
    }
    localState(name, frame, origin = this.origin) {
      const info = this.info(name), p = this.poseAt(name,frame);
      return {x: origin.x + p.route.x, z: origin.z + p.route.z,
        heading: frame === info.clip.frames - 1 ? info.endHeading : info.startHeading,
        yaw: p.route.yaw};
    }
    endState(name = this.current, origin = this.origin) {
      const i = this.info(name);
      return this.localState(name, i.clip.frames - 1, origin);
    }
    depthScale(z) {
      const q = (z - this.plane.minZ) / (this.plane.maxZ - this.plane.minZ);
      // A distant fixed camera: far/near scale is exactly .8, rather than a
      // separate animation clock or an image-specific scale adjustment.
      return 1 / (1 + (1 / this.farScale - 1) * q);
    }
    project(world, windY = 0) {
      const g = this.geometry, p = this.plane, scale = this.depthScale(world.z);
      const centreX = (p.minX + p.maxX) / 2, centreZ = (p.minZ + p.maxZ) / 2;
      return {x: g.midpointX + (world.x - centreX) * g.unitWidth * scale,
        y: g.midpointY + (world.z - centreZ) * g.depthUnit * scale + windY * g.usableHeight * scale};
    }
    point(name, frame, origin = this.origin) {
      return this.project(this.localState(name, frame, origin), this.poseAt(name,frame).motion?.y ?? 0);
    }
    velocity(name, frame, origin = this.origin) {
      const info = this.info(name), p = this.poseAt(name,frame), world = this.localState(name, frame, origin);
      const g = this.geometry, plane = this.plane, s = this.depthScale(world.z);
      const dzScale = -(1 / this.farScale - 1) / (plane.maxZ - plane.minZ) * s * s;
      const vx = p.route.vx ?? Math.cos(p.route.yaw), vz = p.route.vz ?? Math.sin(p.route.yaw);
      return {x: g.unitWidth * (vx * s + (world.x - (plane.minX + plane.maxX) / 2) * dzScale * vz),
        y: g.depthUnit * (vz * s + (world.z - (plane.minZ + plane.maxZ) / 2) * dzScale * vz)};
    }

    configure(geometry) {
      if (!geometry) throw new TypeError('Supply the fixed sky geometry.');
      const g = this.geometry = {...geometry}, e = this.extents, p = this.plane;
      g.left ??= 0; g.top ??= 0;
      g.pad ??= 8; g.topPad ??= g.pad;
      g.usableWidth = Math.max(1, g.width - 2 * g.pad);
      g.usableHeight = Math.max(1, g.height - g.topPad - g.pad);
      // The same fixed Blender camera defines depth projection and the baked
      // headings. Its slight upward view places farther routes slightly lower.
      const depthSlope = this.manifest.camera?.depthScreenYPerUnit ??
        this.manifest.composition?.projectionDepthSlope ?? .024955585;
      const maxWorldX = Math.max(Math.abs(p.minX), Math.abs(p.maxX));
      const maxSideExtent = Math.max(e.left, e.right);
      const vertical = {...this.coreExtents};
      // An ongoing rare action must also remain valid when the viewport is
      // resized. Include its silhouette without changing its world phase.
      const active = this.promptReturn ? this.promptReturn.phases.flatMap(phase =>
        [{name:phase.name}, ...(phase.blendFrom ? [{name:phase.blendFrom.clip}] : [])]) :
        this.current ? [{name:this.current}, ...this.plan] : [];
      for (const item of active) {
        for (const pose of this.info(item.name).clip.poses) {
          vertical.up = Math.max(vertical.up, (pose.root.y - pose.bounds.top) * pose.orthoScale);
          vertical.down = Math.max(vertical.down, (pose.bounds.bottom - pose.root.y) * pose.orthoScale);
        }
      }
      const centreZ = (p.minZ + p.maxZ) / 2;
      // Keep the readable raven and compact depth projection independent of
      // the horizontal patrol corridor. A short header must not squeeze a
      // desktop-wide route into the same small span as a phone's route.
      const windHeight = (e.windMax - e.windMin) * g.usableHeight;
      g.scale = Math.max(0, Math.min(g.scale,
        (g.preferredSideWidth ?? 70) / Math.max(.01, this.sideFootprint),
        (g.usableHeight - windHeight) / Math.max(.01, vertical.up + vertical.down),
        g.usableWidth * .48 / Math.max(.01, e.left + e.right))) * (1 - 1e-8);
      const verticalBounds = unit => {
        let top = Infinity, bottom = -Infinity;
        for (const z of [p.minZ, p.maxZ]) {
          const s = this.depthScale(z), position = (z - centreZ) * depthSlope * unit;
          top = Math.min(top, (position - vertical.up * g.scale + e.windMin * g.usableHeight) * s);
          bottom = Math.max(bottom, (position + vertical.down * g.scale + e.windMax * g.usableHeight) * s);
        }
        return {top, bottom};
      };
      const maxUnit = Math.max(0, (g.usableWidth / 2 - maxSideExtent * g.scale) / maxWorldX);
      let low = 0, high = maxUnit;
      for (let i = 0; i < 40; i++) {
        const middle = (low + high) / 2, b = verticalBounds(middle);
        if (b.bottom - b.top <= g.usableHeight) low = middle; else high = middle;
      }
      g.unitWidth = maxUnit * (1 - 1e-8);
      g.depthUnit = depthSlope * low * (1 - 1e-8);
      g.depthPixels = Math.abs(g.depthUnit) * (p.maxZ - p.minZ);
      g.midpointX = g.left + g.width / 2;
      const fit = verticalBounds(low);
      g.midpointY = g.top + g.topPad + (g.usableHeight - fit.top - fit.bottom) / 2;
      g.horizontalScale = g.unitWidth / (g.usableWidth * (this.manifest.composition?.unitWidthFraction ?? .03));
      this.blocked = !(g.scale > 0 && g.unitWidth > 0 && g.height > g.topPad + g.pad + 12);
      // Resize changes the horizontal corridor and compact depth projection.
      // World positions, junctions,
      // queued clips and the current frame phase are all retained.
      if (!this.blocked && this.current) {
        if (this.promptReturn) this.blocked = !this.returnFramesFit();
        else {
          const paths = [{name:this.current,origin:this.origin}, ...this.plan];
          this.blocked = paths.some(i => !this.canFit(i.name,i.origin));
        }
      }
    }

    worldFits(name, origin) {
      const p = this.plane;
      for (const pose of this.info(name).clip.poses) {
        const x = origin.x + pose.route.x, z = origin.z + pose.route.z;
        if (x < p.minX - 1e-7 || x > p.maxX + 1e-7 || z < p.minZ - 1e-7 || z > p.maxZ + 1e-7) return false;
      }
      return true;
    }
    canFit(name, origin = this.origin, onlyFrame = undefined) {
      if (!this.worldFits(name, origin)) return false;
      const {clip} = this.info(name), g = this.geometry;
      for (let f = onlyFrame ?? 0; f < (onlyFrame === undefined ? clip.frames : onlyFrame + 1); f++) {
        const p = clip.poses[f], b = p.bounds, w = this.localState(name, f, origin);
        const point = this.project(w, p.motion?.y ?? 0), s = p.orthoScale * g.scale * this.depthScale(w.z);
        if (point.x + (b.left - p.root.x) * s < g.left + g.pad - 1e-5 ||
          point.x + (b.right - p.root.x) * s > g.left + g.width - g.pad + 1e-5 ||
          point.y + (b.top - p.root.y) * s < g.top + g.topPad - 1e-5 ||
          point.y + (b.bottom - p.root.y) * s > g.top + g.height - g.pad + 1e-5) return false;
      }
      return true;
    }
    sequence(names, state) {
      const items = []; let next = {...state};
      for (const name of names) {
        const info = this.info(name);
        if (info.startHeading !== next.heading && info.action !== 'entry') return null;
        const origin = {x: next.x, z: next.z};
        if (!this.canFit(name, origin)) return null;
        items.push({name, origin}); next = this.endState(name, origin);
      }
      return {items, end: next};
    }
    sideConnector(heading) {
      return heading === sideOf(heading) ? null : this.find('connect', heading, sideOf(heading));
    }
    returnSequence(state) {
      const connector = this.sideConnector(state.heading), side = sideOf(state.heading);
      if (state.heading !== side && !connector) return null;
      const exit = this.find('exit', side);
      if (!exit) return null;
      return this.sequence([...(connector ? [connector.name] : []), exit.name], state);
    }
    turnSequences(state) {
      const connector = this.sideConnector(state.heading), side = sideOf(state.heading);
      if (state.heading !== side && !connector) return [];
      return (this.outgoing.get(side) ?? []).filter(i => i.action === 'turn')
        .map(i => this.sequence([...(connector ? [connector.name] : []), i.name], state)).filter(Boolean)
        .filter(s => !!this.returnSequence(s.end));
    }
    hasReserve(state) { return !!this.returnSequence(state) && this.turnSequences(state).length > 0; }

    initialOrigin() {
      const p = this.plane, direction = directionOf(this.heading);
      // Search junctions before flight begins; no visible position is clamped.
      const zs = [p.minZ + .8, p.minZ + 1.8, 0, -2, 2, -1, 1];
      const edge=direction === -1 ? p.maxX : p.minX;
      for (let inset = 0; inset <= p.maxX-p.minX; inset += .25)
        for (const z of zs) {
          const origin = {x: edge+direction*inset, z}, entryEnd = this.endState(this.current, origin);
          const steady = this.find('soar_forward', this.heading, this.heading);
          if (!this.canFit(this.current, origin)) continue;
          const first = this.sequence([steady.name], entryEnd);
          if (first && this.hasReserve(first.end)) return origin;
        }
      throw new RangeError('The raven needs more room in this sky.');
    }
    weighted(candidates) {
      if (!candidates.length) return null;
      let value = this.random() * candidates.reduce((sum, c) => sum + c.weight, 0);
      for (const c of candidates) { value -= c.weight; if (value < 0) return c; }
      return candidates.at(-1);
    }
    queueFrom(state) {
      if (this.returnRequested) {
        const returning = this.returnSequence(state);
        if (!returning) throw new RangeError('The reserved return corridor is unavailable.');
        this.plan = returning.items.map(i => ({...i, family: 'return'})); return;
      }
      const currentInfo = this.info(), side = sideOf(state.heading);
      if (state.heading !== side) {
        const connector = this.sideConnector(state.heading);
        const route = connector && this.sequence([connector.name], state);
        if (!route || !this.hasReserve(route.end)) throw new RangeError('The reserved heading connector is unavailable.');
        this.plan = route.items.map(i => ({...i, family: 'diagonal'})); return;
      }
      const candidates = [];
      const add = (names, family, weight, extra = {}) => {
        const seq = this.sequence(names, state);
        if (seq && this.hasReserve(seq.end) &&
          seq.items.every(i => !!this.returnSequence(this.endState(i.name, i.origin))))
          candidates.push({...seq, family, weight, ...extra});
      };
      const normal = this.find('soar_forward', side, side), wind = this.find('soar_backward', side, side);
      if (normal) add([normal.name], 'side', this.weights.side * .65);
      for(const swerve of this.swerves.get(side)??[])
        add([swerve.name],'swerve',this.weights.swerve*.5);
      if (!candidates.some(c => c.items.some(i => i.name === normal?.name))) {
        // Prefer the longest safe coast. Repeated full-length blocks used to
        // turn around near the middle simply because six units would not fit.
        for (const coast of [...(this.edgeCruises.get(side) ?? [])].reverse()) {
          const before = candidates.length;
          add([coast.name], 'side', this.weights.side * .65);
          if (candidates.length > before) break;
        }
      }
      if (wind && currentInfo.action !== 'soar_backward') add([wind.name], 'side', this.weights.side * .20);
      const beats = this.find('wingbeats', side, side);
      if (beats && currentInfo.action !== 'wingbeats') add([beats.name], 'side', this.weights.side * .15);
      for (const suffix of ['a', 't']) {
        const h = side + suffix, out = this.find('connect', side, h), back = this.find('connect', h, side);
        const glide = this.find('soar_forward', h, h);
        if (out && back && glide) add([out.name, glide.name, back.name], 'diagonal', this.weights.diagonal * .5);
        const other = side + (suffix === 'a' ? 't' : 'a'), out2 = this.find('connect', side, other);
        const back2 = this.find('connect', other, side);
        if (out && back && out2 && back2)
          add([out.name, back.name, out2.name, back2.name], 'curve', this.weights.curve * .5);
      }
      // A wind retreat cannot indefinitely postpone a necessary boundary turn.
      const advancing = candidates.filter(c => c.items.some(i => this.info(i.name).action !== 'soar_backward'));
      if (!advancing.length) candidates.length = 0;
      const lastFamilies = this.history.filter(i => i.family && !['turn', 'return'].includes(i.family)).slice(-2).map(i => i.family);
      for (const c of candidates) {
        if (lastFamilies.length === 2 && lastFamilies.every(f => f === c.family)) c.weight *= .35;
        if (c.family === 'diagonal') {
          const change = Math.abs(state.z - this.depthTarget) - Math.abs(c.end.z - this.depthTarget);
          c.weight *= change > .2 ? 2 : change < -.2 ? .3 : 1;
        }
      }
      const nextStart = this.startMs + currentInfo.durationMs;
      const diagonal = candidates.filter(c => c.family === 'diagonal');
      const swerves=candidates.filter(c=>c.family==='swerve');
      const angled = candidates.filter(c => ['diagonal','curve','swerve'].includes(c.family));
      const firstAngles = !this.hasAngledRoute && angled.length > 0;
      const durationOf = c => c.items.reduce((sum, item) => sum + this.info(item.name).durationMs, 0);
      const budgeted = candidates.filter(c => c.family !== 'side' ||
        this.sideOnlyPlannedMs + durationOf(c) <= this.sideOnlyLimitMs);
      const angleDue = firstAngles || (angled.length > 0 && !budgeted.some(c => c.family === 'side'));
      // A normal ten-second demo must show a held shallow heading before its
      // reply. Later randomness stays bounded so a string of side-only picks
      // cannot hide the depth and camera angles in a longer patrol either.
      const available = firstAngles ? (swerves.length?swerves:diagonal.length ? diagonal : angled) :
        angleDue ? angled : budgeted;
      if (!angleDue && available.length && this.sideOnlyPlannedMs + 5000 <= this.sideOnlyLimitMs &&
        nextStart >= this.nextRollMs && currentInfo.action !== 'roll') {
        const roll = this.find('roll', side, side), route = roll && this.sequence([roll.name], state);
        if (route && this.hasReserve(route.end)) {
          this.plan = route.items.map(i => ({...i, family: 'roll'}));
          this.sideOnlyPlannedMs += route.items.reduce((sum, item) => sum + this.info(item.name).durationMs, 0); return;
        }
      }
      const chosen = this.weighted(available);
      if (chosen) {
        this.plan = chosen.items.map(i => ({...i, family: chosen.family}));
        if (['diagonal', 'curve','swerve'].includes(chosen.family)) {
          this.hasAngledRoute = true; this.sideOnlyPlannedMs = 0;
          if (angleDue) this.forcedAngleChoices++;
        } else this.sideOnlyPlannedMs += durationOf(chosen);
        return;
      }
      const turns = this.turnSequences(state);
      if (!turns.length) throw new RangeError('No reserved inward flight turn is available.');
      turns.sort((a, b) => Math.abs(a.end.z - this.depthTarget) - Math.abs(b.end.z - this.depthTarget));
      const turn = turns.length > 1 && this.random() < .10 ? turns[1] : turns[0];
      this.plan = turn.items.map(i => ({...i, family: 'turn'}));
      this.sideOnlyPlannedMs += turn.items.reduce((sum, item) => sum + this.info(item.name).durationMs, 0);
    }

    requestReturn(ms = this.lastSampleMs) {
      if (this.done || this.promptReturn) return this.getReturnFrames();
      const snapshot = this.sample(Number.isFinite(ms) ? ms : this.lastSampleMs);
      const info = this.info(), sourcePose = this.poseAt(this.current,snapshot.routeFrame??snapshot.frame);
      const phases = []; let cursor = this.lastSampleMs, world = {x:snapshot.world.x,z:snapshot.world.z};
      const add = phase => {
        phase.startMs = cursor; phase.endMs = cursor + phase.durationMs;
        cursor = phase.endMs; phases.push(phase);
      };
      const native = (name,fromFrame,toFrame,durationMs,fixedWorld=null,origin=null) => {
        add({kind:'native',name,fromFrame,toFrame,durationMs,
          world:fixedWorld ? {...fixedWorld} : null,origin:origin ? {...origin} : null});
        if (!fixedWorld) {
          const p=this.poseAt(name,toFrame);world={x:origin.x+p.route.x,z:origin.z+p.route.z};
        }
      };
      const blend = (name,frame) => {
        const incoming = this.poseAt(name,frame);
        if (incoming.evaluatedGeometrySha256 === sourcePose.evaluatedGeometrySha256 &&
          Math.abs(sourcePose.motion?.y ?? 0) < 1e-10&&
          Math.abs(snapshot.flightRotation?.yaw??0)<1e-10&&Math.abs(snapshot.flightRotation?.bank??0)<1e-10) return;
        add({kind:'blend',name,fromFrame:frame,toFrame:frame,durationMs:80,world:{...world},
          blendFrom:{...snapshot,world:{...world}},fromWind:sourcePose.motion?.y ?? 0});
      };
      let heading;
      if (['soar_forward','soar_backward','swerve'].includes(info.action)) {
        heading=info.startHeading; const side=sideOf(heading),connector=this.sideConnector(heading);
        if (connector) {
          blend(connector.name,0);
          native(connector.name,0,connector.clip.frames-1,160,world);
        } else blend(this.find('exit',side).name,0);
        heading=side;
      } else if (info.action === 'exit') {
        heading=info.startHeading;
        native(info.name,snapshot.frame,info.clip.frames-1,220,world);
      } else {
        // Replay the current body motion toward its closest available side
        // junction. Reversal avoids completing a whole roll or turn when the
        // reply arrives just after the manoeuvre began; there is no pose cut.
        const endpoints=[0,info.clip.frames-1].filter(frame => {
          const h=frame===0?info.startHeading:info.endHeading;
          return h==='r'||h==='l';
        });
        if (!endpoints.length) throw new RangeError('No prompt return junction for '+info.name);
        endpoints.sort((a,b)=>Math.abs(a-snapshot.frame)-Math.abs(b-snapshot.frame));
        const end=endpoints[0];heading=end===0?info.startHeading:info.endHeading;
        const durationMs=info.action==='roll'?280:info.action==='turn'||info.action==='wingbeats'?220:160;
        native(info.name,snapshot.frame,end,durationMs,null,this.origin);
      }
      if (info.action !== 'exit') {
        const exit=this.find('exit',heading);
        native(exit.name,0,exit.clip.frames-1,220,world);
      }
      this.returnRequested=true;this.holding=null;this.plan=[];
      this.promptReturn={startMs:this.lastSampleMs,endMs:cursor,phases,index:0,
        source:{...snapshot,world:{...snapshot.world}},endingHeading:heading};
      return this.getReturnFrames();
    }
    returnFrame(phase,u) {
      const f=phase.fromFrame+(phase.toFrame-phase.fromFrame)*ease(u);return this.info(phase.name).clip.fps===60?f:Math.round(f);
    }
    returnSample(phase,u,frameOverride=undefined) {
      const frame=frameOverride??this.returnFrame(phase,u),pose=this.poseAt(phase.name,frame);
      const world=phase.world?{...phase.world}:{x:phase.origin.x+pose.route.x,z:phase.origin.z+pose.route.z};
      const wind=phase.kind==='blend' ? phase.fromWind*(1-ease(u)) : pose.motion?.y ?? 0;
      const result={clip:phase.name,frame,anchor:'root',world,point:this.project(world,wind),
        depthScale:this.depthScale(world.z),heading:this.info(phase.name).startHeading,
        routeYaw:pose.route.yaw,direction:directionOf(this.info(phase.name).startHeading),
        action:'exit',label:'Returning',family:'return',done:false,returning:true,promptReturn:true};
      if(phase.kind==='blend'){
        result.blendWeight=ease(u);
        result.blendFrom={...phase.blendFrom,world:{...world},point:{...result.point},depthScale:result.depthScale};
      }
      return result;
    }
    returnFramesFit() {
      for(const phase of this.promptReturn.phases) {
        const count=Math.max(2,Math.abs(phase.toFrame-phase.fromFrame)+1);
        for(let i=0;i<count;i++) {
          const u=i/(count-1),frame=Math.round(phase.fromFrame+(phase.toFrame-phase.fromFrame)*u);
          const sample=this.returnSample(phase,u,frame),g=this.geometry;
          for(const source of [sample,...(sample.blendFrom?[sample.blendFrom]:[])]) {
            const p=this.poseAt(source.clip,source.frame),b=source.bounds??p.bounds,
              size=p.orthoScale*g.scale*source.depthScale,point=source.point;
            if(source.world.x<this.plane.minX-1e-7||source.world.x>this.plane.maxX+1e-7||
              source.world.z<this.plane.minZ-1e-7||source.world.z>this.plane.maxZ+1e-7||
              point.x+(b.left-p.root.x)*size<g.left+g.pad-1e-5||
              point.x+(b.right-p.root.x)*size>g.left+g.width-g.pad+1e-5||
              point.y+(b.top-p.root.y)*size<g.top+g.topPad-1e-5||
              point.y+(b.bottom-p.root.y)*size>g.top+g.height-g.pad+1e-5)return false;
          }
        }
      }
      return true;
    }
    getReturnFrames(fps=60,ms=this.lastSampleMs) {
      if(!this.promptReturn) {
        if(this.done)return [];
        // Forecasting may advance already queued clips, but must not consume
        // the live RNG or mutate the live flight when warming return pages.
        const forecast=Object.assign(Object.create(ChatFlightDirector.prototype),this,
          {rng:()=>.5,history:this.history.slice(),plan:this.plan.map(item=>({...item,origin:{...item.origin}})),
            depthVisits:this.depthVisits.slice(),origin:{...this.origin},
            holding:this.holding?{...this.holding,world:{...this.holding.world},origin:{...this.holding.origin}}:null});
        forecast.sample(Math.max(this.lastSampleMs,Number.isFinite(ms)?ms:this.lastSampleMs));
        forecast.requestReturn(forecast.lastSampleMs);
        return forecast.getReturnFrames(fps);
      }
      const frames=new Map();
      for(const phase of this.promptReturn.phases) {
        const ticks=Math.ceil(phase.durationMs*fps/1000);
        for(let i=0;i<=ticks;i++) {
          const sample=this.returnSample(phase,i/ticks);
          for(const source of [sample,...(sample.blendFrom?[sample.blendFrom]:[])])
            frames.set(source.clip+'/'+source.frame,{clip:source.clip,frame:source.frame});
        }
      }
      return [...frames.values()];
    }
    advance() {
      const previous = this.info(), end = this.endState(), previousPoint = this.point(this.current, previous.clip.frames - 1);
      const previousScale = this.depthScale(end.z);
      this.startMs += previous.durationMs; this.joins++;
      this.history.push({name: previous.name, action: previous.action, family: this.currentFamily ?? 'entry',
        heading: previous.endHeading, world: {x: end.x, z: end.z}, atMs: this.startMs});
      if (this.history.length > 24) this.history.shift();
      if (this.headingAngles[previous.endHeading] !== undefined) this.heading = previous.endHeading;
      const bin = Math.min(4, Math.max(0, Math.floor((end.z - this.plane.minZ) / (this.plane.maxZ - this.plane.minZ) * 5)));
      this.depthVisits[bin] += previous.durationMs;
      if (Math.abs(end.z - this.depthTarget) < 1.4) {
        const levels = [this.plane.minZ + .8, this.plane.minZ + (this.plane.maxZ - this.plane.minZ) * .3,
          (this.plane.minZ + this.plane.maxZ) / 2, this.plane.minZ + (this.plane.maxZ - this.plane.minZ) * .7,
          this.plane.maxZ - .8];
        const least = Math.min(...this.depthVisits.filter((_, i) => i !== bin));
        const bins = this.depthVisits.map((v, i) => ({v, i})).filter(i => i.i !== bin && i.v <= least + 6000);
        this.depthTarget = levels[bins[Math.floor(this.random() * bins.length)].i];
      }
      if (previous.action === 'roll') this.nextRollMs = this.startMs + 28000 + this.random() * 30000;
      if (previous.action === 'exit') {
        this.done = true; this.completedAtMs = this.startMs; this.endPoint = previousPoint; this.plan = []; return false;
      }
      const delay = this.knownReplyMs === null ? Infinity : this.knownReplyMs - this.startMs;
      if (!this.returnRequested && delay > 0 && delay <= 300) {
        this.holding = {clip: previous.name, frame: previous.clip.frames - 1, origin: {...this.origin},
          world: end, point: previousPoint, depthScale: previousScale, endMs: this.knownReplyMs};
        this.queueFrom(end); return true;
      }
      if (this.returnRequested) this.queueFrom(end);
      if (!this.plan.length) this.queueFrom(end);
      const next = this.plan.shift();
      if (!next || distance(next.origin, end) > 1e-7) throw new Error('A flight route changed position at a junction.');
      const incoming = this.info(next.name);
      if (incoming.startHeading !== previous.endHeading)
        throw new Error('A flight route changed its rendered heading at a junction.');
      this.current = next.name; this.origin = next.origin; this.currentFamily = next.family;
      const firstPoint = this.point(this.current, 0), firstScale = this.depthScale(this.origin.z);
      if (Math.hypot(firstPoint.x - previousPoint.x, firstPoint.y - previousPoint.y) > 1e-4 ||
        Math.abs(previousScale - firstScale) > 1e-10)
        throw new Error('A flight route changed projection or scale at a junction.');
      if (!this.plan.length && incoming.action !== 'exit') this.queueFrom(this.endState());
      return true;
    }
    sample(ms) {
      if (this.blocked) ms = this.lastSampleMs; else this.lastSampleMs = ms;
      if(this.promptReturn) {
        const returning=this.promptReturn;
        while(returning.index<returning.phases.length-1&&ms+1e-6>=returning.phases[returning.index].endMs)returning.index++;
        const phase=returning.phases[returning.index],u=clamp((ms-phase.startMs)/phase.durationMs);
        const result=this.returnSample(phase,u);this.current=phase.name;this.startMs=phase.startMs;
        this.heading=returning.endingHeading;this.currentFamily='return';
        if(ms+1e-6>=returning.endMs){this.done=true;this.completedAtMs=returning.endMs;this.endPoint={...result.point};result.done=true;}
        result.returnProgress=clamp((ms-returning.startMs)/(returning.endMs-returning.startMs));
        result.next=this.next;return result;
      }
      if (this.holding) {
        const h = this.holding;
        if (!this.returnRequested || ms + 1e-6 < h.endMs) {
          const heldClip = this.info(h.clip).clip;
          return {clip: heldClip.sourceClip ?? h.clip, frame: this.sourceFrameAt(heldClip,h.frame),
            routeFrame:h.frame, anchor: 'root', point: this.point(h.clip, h.frame, h.origin), world: {...h.world},
            depthScale: h.depthScale, heading: this.heading, direction: this.direction,
            action: this.info(h.clip).action, next: this.next, done: false, holding: true};
        }
        this.holding = null; this.startMs = h.endMs; this.queueFrom(h.world);
        const next = this.plan.shift(); this.current = next.name; this.origin = next.origin; this.currentFamily = next.family;
      }
      while (!this.done && ms + 1e-6 >= this.startMs + this.info().durationMs) this.advance();
      if (this.holding) return this.sample(ms);
      const info = this.info(), clip = info.clip;
      const frame = this.done ? clip.frames - 1 : Math.min(clip.frames - 1,
        (clip.fps===60?Math.max(0,ms-this.startMs)*clip.fps/1000:Math.floor(Math.max(0,ms-this.startMs)*clip.fps/1000+1e-6)));
      const world = this.localState(this.current, frame),pose=this.poseAt(this.current,frame);
      return {clip: clip.sourceClip ?? this.current, frame: this.sourceFrameAt(clip,frame),
        routeFrame: frame, anchor: 'root', point: this.point(this.current, frame),
        flightRotation:pose.flightRotation,bounds:clip.sourceClip?pose.bounds:undefined,
        world, depthScale: this.depthScale(world.z), heading: this.heading, routeYaw: world.yaw,
        action: info.action, label: labels[info.action], family: this.currentFamily ?? 'entry',
        direction: this.direction, steps: this.origin.x, next: this.next, done: this.done};
    }
    getGuide() {
      const p = this.plane, corners = [{x: p.minX, z: p.minZ}, {x: p.maxX, z: p.minZ},
        {x: p.maxX, z: p.maxZ}, {x: p.minX, z: p.maxZ}, {x: p.minX, z: p.minZ}];
      if(this.promptReturn) return {boundary:corners.map(w=>this.project(w)),worldBounds:{...p},
        nearScale:1,farScale:this.farScale,paths:this.promptReturn.phases.slice(this.promptReturn.index).map((phase,i)=>
          ({clip:phase.name,current:i===0,points:Array.from({length:13},(_,j)=>this.returnSample(phase,j/12).point)}))};
      const routes = [{name: this.current, origin: this.origin, current: true}, ...this.plan];
      return {boundary: corners.map(w => this.project(w)), worldBounds: {...p}, nearScale: 1, farScale: this.farScale,
        paths: routes.map(i => ({clip: i.name, current: !!i.current,
          points: this.info(i.name).clip.poses.filter((_, f) => f % 12 === 0 || f === this.info(i.name).clip.frames - 1)
            .map(pose => this.project({x: i.origin.x + pose.route.x, z: i.origin.z + pose.route.z}))}))};
    }
    getStats() {
      return {action: this.current, queued: this.next, heading: this.heading, direction: this.direction,
        world: {...this.origin}, joins: this.joins, returnRequested: this.returnRequested,
        completed: this.done, holding: !!this.holding, blocked: !!this.blocked,
        horizontalScale: this.geometry.horizontalScale, history: this.history.slice(),
        planned: this.plan.map(i => ({clip: i.name, origin: {...i.origin}, family: i.family})), farScale: this.farScale,
        depthTarget: this.depthTarget, depthVisits: this.depthVisits.slice(),
        hasAngledRoute: this.hasAngledRoute, sideOnlyPlannedMs: this.sideOnlyPlannedMs,
        forcedAngleChoices: this.forcedAngleChoices, projectedPlaneWidth: gUnitWidth(this.geometry, this.plane),
        patrolSpeedPixelsPerSecond:this.geometry.unitWidth,depthProjectionPixels:this.geometry.depthPixels,
        edgeCruise:this.current.startsWith('edge_cruise_'),
        promptReturn:this.promptReturn?{startMs:this.promptReturn.startMs,endMs:this.promptReturn.endMs,
          durationMs:this.promptReturn.endMs-this.promptReturn.startMs,index:this.promptReturn.index}:null};
    }
  }
  const gUnitWidth = (g, p) => g.unitWidth * (p.maxX - p.minX);
  return {ChatFlightDirector};
});
