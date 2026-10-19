/* Captured, message-scoped evidence cards. No evidence fetch or layout insertion. */
(() => {
  'use strict';
  const KIND = Object.freeze({offer:'Product offer',delivery:'Delivery',review:'Reviews',history:'Price history',calculation:'Calculation'});
  const contexts = new WeakMap();
  const messages = new WeakMap();
  const TOKEN = /\[\[([A-Za-z0-9][\w:.-]{0,79})\]\]/g;
  const PORTAL_ID = 'raven-citation-card-v40';
  let portal = null, active = null, hideTimer = null, installed = false, suppressedFocus = null;
  const str = (value, limit = 600) => typeof value === 'string' ? value.slice(0, limit) : '';
  const node = (tag, className, value) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (value !== undefined) element.textContent = String(value);
    return element;
  };
  function safeUrl(value) {
    if (typeof value !== 'string' || value.length > 2048 || /[\u0000-\u0020\u007f\\]/.test(value) || !/^https?:\/\//i.test(value)) return null;
    try {
      const url = new URL(value);
      return ['https:', 'http:'].includes(url.protocol) && url.hostname && !url.username && !url.password ? url.href : null;
    } catch { return null; }
  }
  function normalize(sources) {
    const map = new Map();
    if (!Array.isArray(sources)) return map;
    for (const value of sources.slice(0, 128)) {
      if (!value || typeof value !== 'object' || typeof value.id !== 'string' || !/^[A-Za-z0-9][\w:.-]{0,79}$/.test(value.id) || map.has(value.id)) continue;
      const source = {
        id:value.id, number:map.size + 1, kind:Object.prototype.hasOwnProperty.call(KIND,value.kind) ? value.kind : 'offer',
        siteName:str(value.siteName,100) || 'Captured source', title:str(value.title,220) || 'Source evidence',
        context:str(value.context,400), url:safeUrl(value.url), favicon:safeUrl(value.favicon),
        metric:{value:str(value.metric?.value,120),label:str(value.metric?.label,100)},
        facts:Array.isArray(value.facts) ? value.facts.slice(0,12).filter(f => f && typeof f === 'object').map(f => ({label:str(f.label,100),value:str(f.value,600)})) : [],
        evidence:str(value.evidence,12000), checkedAt:str(value.checkedAt,80), checkedLabel:str(value.checkedLabel,150),
        illustrative:value.illustrative === true,
        inputs:Array.isArray(value.inputs) ? value.inputs.slice(0,12).filter(f => f && typeof f === 'object').map(f => ({sourceId:str(f.sourceId,80),label:str(f.label,120),value:str(f.value,120)})) : [],
        history:null
      };
      if (value.history && Array.isArray(value.history.points)) {
        const points = value.history.points.slice(0,365);
        if (points.length > 1 && points.every(p => typeof p === 'number' && Number.isFinite(p))) {
          source.history = {points:points.slice(),startLabel:str(value.history.startLabel,100),endLabel:str(value.history.endLabel,100),unit:str(value.history.unit,20)};
        }
      }
      map.set(source.id, source);
    }
    return map;
  }
  function focusWithoutScroll(element) {
    if (!element?.isConnected || document.activeElement === element) return;
    suppressedFocus = element;
    element.focus({preventScroll:true});
    suppressedFocus = null;
  }
  function clearHide() { clearTimeout(hideTimer); hideTimer = null; }
  function close(restoreFocus = false) {
    clearHide();
    const origin = active?.origin;
    if (origin) origin.setAttribute('aria-expanded','false');
    active = null;
    if (portal) { portal.hidden = true; portal.replaceChildren(); }
    if (restoreFocus) focusWithoutScroll(origin);
  }
  function clippedOrigin() {
    if (!active?.origin.isConnected || !active.context.container.isConnected || !active.context.container.contains(active.origin)) return true;
    const rect = active.origin.getBoundingClientRect();
    if (!rect.width || !rect.height || rect.top < -1 || rect.left < -1 || rect.bottom > window.innerHeight + 1 || rect.right > window.innerWidth + 1) return true;
    for (let ancestor = active.origin.parentElement; ancestor && ancestor !== document.body; ancestor = ancestor.parentElement) {
      const style = getComputedStyle(ancestor);
      if (style.visibility === 'hidden' || style.display === 'none') return true;
      const clipX = /^(auto|scroll|hidden|clip)$/.test(style.overflowX), clipY = /^(auto|scroll|hidden|clip)$/.test(style.overflowY);
      if (!clipX && !clipY) continue;
      const bounds = ancestor.getBoundingClientRect(), left = bounds.left + ancestor.clientLeft, top = bounds.top + ancestor.clientTop;
      if (clipX && (rect.left < left - 1 || rect.right > left + ancestor.clientWidth + 1)) return true;
      if (clipY && (rect.top < top - 1 || rect.bottom > top + ancestor.clientHeight + 1)) return true;
    }
    return false;
  }
  function position() {
    if (!active || !portal || portal.hidden) return;
    if (clippedOrigin()) { close(); return; }
    const rect = active.origin.getBoundingClientRect(), vw = window.innerWidth, vh = window.innerHeight;
    const margin = 12, gap = 9;
    portal.style.width = Math.max(1,Math.min(336,vw - margin * 2)) + 'px';
    portal.style.maxHeight = Math.max(1,vh - margin * 2) + 'px';
    const card = portal.getBoundingClientRect();
    const below = vh - margin - rect.bottom - gap, above = rect.top - gap - margin;
    const flip = card.height > below && above > below;
    const desiredTop = flip ? rect.top - gap - card.height : rect.bottom + gap;
    portal.style.left = Math.max(margin,Math.min(rect.left - 12,vw - margin - card.width)) + 'px';
    portal.style.top = Math.max(margin,Math.min(desiredTop,vh - margin - card.height)) + 'px';
    portal.dataset.placement = flip ? 'above' : 'below';
  }
  function scheduleClose() {
    clearHide();
    if (!active || active.pinned) return;
    hideTimer = setTimeout(() => {
      if (!active || active.pinned || active.origin.matches(':hover') || portal?.matches(':hover') || document.activeElement === active.origin || portal?.contains(document.activeElement)) return;
      close();
    },400);
  }
  function ensurePortal() {
    if (portal) return portal;
    portal = node('section','raven-citation-card');
    portal.id = PORTAL_ID; portal.hidden = true;
    portal.setAttribute('role','dialog'); portal.setAttribute('aria-modal','false'); portal.setAttribute('aria-labelledby',PORTAL_ID + '-title');
    document.body.append(portal);
    portal.addEventListener('pointerenter',clearHide);
    portal.addEventListener('pointerleave',scheduleClose);
    portal.addEventListener('focusin',clearHide);
    portal.addEventListener('focusout',event => { if (!portal.contains(event.relatedTarget)) scheduleClose(); });
    return portal;
  }
  function factRows(facts) {
    const list = node('dl','raven-citation-facts');
    for (const fact of facts) {
      if (!fact.label && !fact.value) continue;
      const row = node('div'); row.append(node('dt','',fact.label),node('dd','',fact.value)); list.append(row);
    }
    return list;
  }
  function historyChart(history) {
    const wrapper = node('div','raven-citation-history');
    const ns = 'http://www.w3.org/2000/svg', svg = document.createElementNS(ns,'svg'), polyline = document.createElementNS(ns,'polyline');
    const values = history.points, min = Math.min(...values), max = Math.max(...values), span = max - min;
    svg.setAttribute('viewBox','0 0 300 58'); svg.setAttribute('role','img');
    svg.setAttribute('aria-label',`${values.length} captured price observations, ranging from ${history.unit}${min} to ${history.unit}${max}`);
    svg.setAttribute('preserveAspectRatio','none'); svg.dataset.pointCount = String(values.length);
    polyline.setAttribute('points',values.map((value,index) => `${5 + index * 290 / (values.length - 1)},${span ? 6 + (max - value) * 46 / span : 29}`).join(' '));
    polyline.setAttribute('fill','none'); polyline.setAttribute('stroke','currentColor'); polyline.setAttribute('stroke-width','2');
    polyline.setAttribute('stroke-linecap','round'); polyline.setAttribute('stroke-linejoin','round'); polyline.setAttribute('vector-effect','non-scaling-stroke');
    svg.append(polyline); wrapper.append(svg);
    const labels = node('div','raven-citation-chart-labels'); labels.append(node('span','',history.startLabel),node('span','',history.endLabel)); wrapper.append(labels);
    return wrapper;
  }
  function renderCard() {
    if (!active) return;
    const card = ensurePortal(), source = active.context.map.get(active.shownId);
    if (!source) { close(); return; }
    card.replaceChildren();
    const header = node('div','raven-citation-header'), brand = node('span','raven-citation-brand',source.kind === 'calculation' ? 'Σ' : source.siteName.slice(0,1).toUpperCase());
    brand.setAttribute('aria-hidden','true');
    if (source.favicon && !/\.svgz?$/i.test(new URL(source.favicon).pathname)) {
      const favicon = node('img','raven-citation-favicon'); favicon.alt = ''; favicon.hidden = true; favicon.referrerPolicy = 'no-referrer';
      favicon.addEventListener('load',() => { if (card.contains(brand)) { brand.firstChild.textContent = ''; favicon.hidden = false; } },{once:true});
      favicon.addEventListener('error',() => favicon.remove(),{once:true});
      favicon.src = '/api/link-preview-image?url=' + encodeURIComponent(source.favicon); brand.append(favicon);
    }
    const identity = node('div','raven-citation-identity');
    identity.append(node('span','raven-citation-kind',KIND[source.kind] + (source.kind === 'calculation' ? '' : ` · Source ${source.number}`)),node('strong','raven-citation-site',source.siteName));
    const dismiss = node('button','raven-citation-close','×'); dismiss.type = 'button'; dismiss.setAttribute('aria-label','Close citation card');
    dismiss.addEventListener('click',() => close(true)); header.append(brand,identity,dismiss);
    const body = node('div','raven-citation-content'), title = node('h3','raven-citation-title',source.title);
    title.id = PORTAL_ID + '-title'; title.tabIndex = -1; body.append(title);
    if (source.context) body.append(node('p','raven-citation-context',source.context));
    if (source.metric.value) {
      const metric = node('div','raven-citation-metric',source.metric.value);
      if (source.metric.label) metric.append(node('small','',source.metric.label));
      body.append(metric);
    }
    if (source.kind === 'history' && source.history) body.append(historyChart(source.history));
    if (source.facts.length) body.append(factRows(source.facts));
    if (source.kind === 'calculation' && source.inputs.length) {
      const inputs = node('div','raven-citation-calculation');
      for (const input of source.inputs) {
        const row = node('div','raven-citation-calculation-row'), label = node('span','',input.label), linked = active.context.map.get(input.sourceId);
        if (linked && linked.id !== source.id) {
          const button = node('button','raven-citation-input',linked.kind === 'calculation' ? 'Σ' : linked.number);
          button.type = 'button'; button.setAttribute('aria-label',`View ${input.label || linked.title}: source ${linked.number}`);
          button.addEventListener('click',() => {
            if (!active) return; active.shownId = linked.id; active.pinned = true; renderCard(); position();
            focusWithoutScroll(portal.querySelector('.raven-citation-title'));
          }); label.append(button);
        }
        row.append(label,node('span','raven-citation-calculation-value',input.value)); inputs.append(row);
      }
      body.append(inputs,node('p','raven-citation-derived','Calculated from the cited inputs.'));
    }
    if (source.evidence) {
      const disclosure = node('details','raven-citation-evidence');
      disclosure.append(node('summary','','View captured evidence'),node('blockquote','raven-citation-excerpt',source.evidence));
      disclosure.addEventListener('toggle',() => {
        if (!active || !card.contains(disclosure)) return;
        if (disclosure.open) { active.pinned = true; card.querySelector('.raven-citation-pinned').hidden = false; }
        position();
      }); body.append(disclosure);
    }
    const footer = node('div','raven-citation-footer'), check = node('div','raven-citation-check');
    const date = new Date(source.checkedAt), label = source.checkedLabel || (Number.isFinite(date.getTime()) ? 'Checked ' + new Intl.DateTimeFormat(undefined,{dateStyle:'medium',timeStyle:'short'}).format(date) : 'Check time not provided');
    const time = node('time','',label); if (Number.isFinite(date.getTime())) time.dateTime = date.toISOString(); check.append(time);
    const pinned = node('span','raven-citation-pinned','Pinned'); pinned.hidden = !active.pinned; check.append(pinned); footer.append(check);
    const actions = node('div','raven-citation-actions');
    if (source.illustrative) actions.append(node('span','raven-citation-illustrative','Illustrative data'));
    if (source.url) {
      const link = node('a','raven-citation-open','Open source ↗'); link.href = source.url; link.target = '_blank'; link.rel = 'noopener noreferrer';
      link.setAttribute('aria-label','Open source (opens in a new tab)'); actions.append(link);
    }
    if (actions.childElementCount) footer.append(actions);
    card.append(header,body,footer); card.hidden = false;
    // A different source starts at the top of the popup's own scroll area.
    card.scrollTop = 0;
  }
  function show(origin,pinned = false) {
    const context = contexts.get(origin);
    if (!context || !origin.isConnected || !context.map.has(context.id)) return;
    clearHide();
    if (active?.origin === origin && active.shownId === context.id) {
      if (pinned) { active.pinned = true; const marker = portal?.querySelector('.raven-citation-pinned'); if (marker) marker.hidden = false; }
      position(); return;
    }
    close(); active = {origin,context,shownId:context.id,pinned};
    origin.setAttribute('aria-expanded','true'); renderCard(); position();
  }
  function trigger(target) { return target?.closest?.('button.raven-citation'); }
  function install() {
    if (installed) return; installed = true;
    document.addEventListener('pointerover',event => {
      if (event.pointerType === 'touch') return;
      const button = trigger(event.target); if (!contexts.has(button) || button.contains(event.relatedTarget)) return;
      clearHide(); if (!active?.pinned) show(button);
    });
    document.addEventListener('pointerout',event => {
      const button = trigger(event.target); if (!contexts.has(button) || button.contains(event.relatedTarget)) return;
      if (portal?.contains(event.relatedTarget)) return; scheduleClose();
    });
    document.addEventListener('focusin',event => {
      const button = trigger(event.target); if (!contexts.has(button) || suppressedFocus === button) return;
      show(button);
    });
    document.addEventListener('focusout',event => { if (contexts.has(trigger(event.target)) && !portal?.contains(event.relatedTarget)) scheduleClose(); });
    document.addEventListener('pointerdown',event => {
      const button = trigger(event.target);
      if (contexts.has(button)) {
        if (event.button === 0) event.preventDefault();
        return;
      }
      if (active && !portal?.contains(event.target)) close();
    },true);
    document.addEventListener('click',event => {
      const button = trigger(event.target); if (!contexts.has(button)) return;
      const toggleOff = active?.origin === button && active.pinned;
      if (toggleOff) close(); else show(button,true);
      focusWithoutScroll(button);
    });
    document.addEventListener('keydown',event => {
      if (event.key === 'Escape' && active) { event.preventDefault(); close(true); return; }
      const button = trigger(event.target);
      if (event.key === 'ArrowDown' && contexts.has(button)) {
        event.preventDefault(); show(button,true); focusWithoutScroll(portal?.querySelector('.raven-citation-close'));
      }
    });
    document.addEventListener('visibilitychange',() => { if (document.hidden) close(); });
    window.addEventListener('resize',position);
    window.addEventListener('scroll',position,true);
  }
  function decorate(button,source,context) {
    button.className = 'raven-citation'; button.type = 'button'; button.dataset.sourceId = source.id;
    button.textContent = source.kind === 'calculation' ? 'Σ' : String(source.number);
    button.setAttribute('aria-label',source.kind === 'calculation' ? `View calculation: ${source.title}` : `View source ${source.number}: ${source.title}`);
    button.setAttribute('aria-haspopup','dialog'); button.setAttribute('aria-controls',PORTAL_ID); button.setAttribute('aria-expanded','false');
    contexts.set(button,{...context,id:source.id});
  }
  function enhance(container,sources) {
    if (!container || typeof container.querySelectorAll !== 'function') throw new TypeError('A rendered message container is required');
    if (active?.context.container === container) close();
    const context = {container,map:normalize(sources)}; messages.set(container,context);
    for (const button of container.querySelectorAll('button.raven-citation[data-source-id]')) {
      const source = context.map.get(button.dataset.sourceId);
      if (source) decorate(button,source,context); else { contexts.delete(button); button.replaceWith(document.createTextNode(`[[${button.dataset.sourceId}]]`)); }
    }
    const texts = [], walker = document.createTreeWalker(container,NodeFilter.SHOW_TEXT,{acceptNode(text) {
      return text.parentElement?.closest('pre,code,a,button,textarea,script,style') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT;
    }});
    for (let current = walker.nextNode(); current; current = walker.nextNode()) if (current.nodeValue.includes('[[')) texts.push(current);
    for (const text of texts) {
      const value = text.nodeValue, fragment = document.createDocumentFragment(); let end = 0, replaced = false;
      TOKEN.lastIndex = 0;
      for (let match = TOKEN.exec(value); match; match = TOKEN.exec(value)) {
        const source = context.map.get(match[1]); if (!source) continue;
        fragment.append(document.createTextNode(value.slice(end,match.index)));
        const button = node('button'); decorate(button,source,context); fragment.append(button);
        end = match.index + match[0].length; replaced = true;
      }
      if (replaced) { fragment.append(document.createTextNode(value.slice(end))); text.replaceWith(fragment); }
    }
    install(); return container;
  }
  window.RavenCitations = Object.freeze({enhance,hide:close,safeUrl,version:40});
})();
