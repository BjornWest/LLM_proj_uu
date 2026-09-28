"""Experimental screenshot gate. Local/browser-only, no model or task knowledge.

Checks viewport-intersecting elements in one explicit region, image decoding,
document font loading, finite animations and sampled layout. It cannot certify
canvas/video pixels, future mutations, or arbitrary application completion.
"""
import time


WAIT = r"""async ({scope, timeout_ms, stable_frames, max_elements}) => {
  const started=performance.now();
  const document_id=globalThis.__intentVisualDocumentId ??=
    Array.from(crypto.getRandomValues(new Uint32Array(4)),n=>n.toString(16)).join('-');
  return await new Promise(resolve => {
    let done=false, frame, timer, previous=null, stable=0, samples=0;
    let latest={pending:[], unsupported:[]};
    const decoded=new WeakMap();
    const finish=(status,reason)=>{
      if(done)return; done=true;cancelAnimationFrame(frame);clearTimeout(timer);
      resolve({status,reason,document_id,elapsed_ms:performance.now()-started,samples,
        stable_frames:stable,signature:previous,scope,...latest,task_success:null});
    };
    const visible=el=>{
      const r=el.getBoundingClientRect(),s=getComputedStyle(el);
      return r.width>0 && r.height>0 && r.bottom>0 && r.right>0 &&
        r.top<innerHeight && r.left<innerWidth && s.visibility==='visible' &&
        s.display!=='none' && Number(s.opacity)!==0;
    };
    const sample=()=>{
      if(done)return;
      samples++;
      const roots=document.querySelectorAll(scope);
      if(roots.length!==1)return finish('unknown','scope_missing_or_ambiguous');
      const root=roots[0];
      const all=[root,...root.querySelectorAll('*')];
      if(all.length>max_elements)return finish('unknown','region_element_limit');
      const elements=all.filter(visible), pending=[], unsupported=[], failed=[];
      if(!elements.length)return finish('unknown','region_outside_viewport_or_hidden');
      if(root.closest('[aria-busy="true"]') || elements.some(e=>e.getAttribute('aria-busy')==='true'))
        pending.push('aria_busy');
      if(document.fonts.status!=='loaded')pending.push('fonts_loading');
      const signature=elements.map(el=>{
        const r=el.getBoundingClientRect(),s=getComputedStyle(el);
        if(['CANVAS','VIDEO','IFRAME','SVG'].includes(el.tagName))unsupported.push(el.tagName.toLowerCase());
        if(s.backgroundImage!=='none')unsupported.push('css_background_image');
        for(const pseudo of ['::before','::after']) {
          const content=getComputedStyle(el,pseudo).content;
          if(content && content!=='none' && content!=='normal')unsupported.push('pseudo_content');
        }
        if(el instanceof HTMLImageElement) {
          const src=el.currentSrc || el.src;
          if(!el.complete)pending.push('image_loading');
          else if(!el.naturalWidth)failed.push('image_failed');
          else {
            let state=decoded.get(el);
            if(!state || state.src!==src) {
              state={src,status:'pending'};decoded.set(el,state);
              el.decode().then(()=>state.status='ready',()=>state.status='failed');
            }
            if(state.status==='pending')pending.push('image_decode');
            if(state.status==='failed')failed.push('image_decode_failed');
          }
        }
        for(const a of el.getAnimations()) if(a.playState==='running' || a.pending) {
          if(a.effect?.getComputedTiming().iterations===Infinity)unsupported.push('infinite_animation');
          else pending.push('animation');
        }
        return [el.tagName,...['x','y','width','height'].map(k=>r[k]),
          s.font,s.color,s.backgroundColor,s.opacity,s.transform,
          el.childElementCount?null:el.textContent,el.value??null,el.checked??null,
          el.currentSrc??null];
      });
      latest={pending:[...new Set(pending)],unsupported:[...new Set(unsupported)],
        failed:[...new Set(failed)],elements:elements.length};
      const next=JSON.stringify(signature);
      stable=next===previous?stable+1:1;previous=next;
      if(failed.length)return finish('failed','asset_failure');
      if(unsupported.length)return finish('unknown','unsupported_visual_content');
      if(!pending.length && stable>=stable_frames)return finish('ready','assets_and_sampled_layout_ready');
      frame=requestAnimationFrame(sample);
    };
    timer=setTimeout(()=>finish('pending','deadline'),timeout_ms);
    try { sample(); } catch(error) { finish('unknown','inspection_error: '+error.message); }
  });
}"""


def wait_visual(page, *, scope='body', timeout_ms=2000, stable_frames=3, max_elements=2000):
    for name,value,minimum in [('timeout_ms',timeout_ms,1),('stable_frames',stable_frames,2),
                               ('max_elements',max_elements,1)]:
        if type(value) is not int or value < minimum:
            raise ValueError(f'{name} must be an integer >= {minimum}')
    return page.evaluate(WAIT, dict(scope=scope, timeout_ms=timeout_ms,
                                   stable_frames=stable_frames,max_elements=max_elements))


def capture_visual(page, path, *, allow_uncertain=False, **options):
    """Keep an uncertain screenshot as evidence, but never label it ready.

    Caller must establish application/document readiness first. This gate only
    addresses screenshot-specific work. No action or screenshot automatic retry.
    """
    started=time.perf_counter()
    before=wait_visual(page,**options)
    if type(allow_uncertain) is not bool:raise ValueError('allow_uncertain must be boolean')
    if before['status']!='ready':
        if allow_uncertain:
            page.screenshot(path=str(path),timeout=options.get('timeout_ms',2000),caret='initial')
            return dict(before,screenshot_saved=True,uncertain_capture=True)
        return dict(before,screenshot_saved=False)
    # Playwright's default caret hiding temporarily injects CSS. Keep page state
    # untouched so revision tracking does not observe our own screenshot edits.
    page.screenshot(path=str(path),timeout=options.get('timeout_ms',2000),caret='initial')
    after=wait_visual(page,**options)
    same=(after['status']=='ready' and before['signature']==after['signature']
          and before['document_id']==after['document_id'])
    return dict(status='ready' if same else 'unknown',
                reason='validated_around_capture' if same else 'visual_state_changed_during_capture',
                screenshot_saved=True,before=before,after=after,
                seconds=time.perf_counter()-started,task_success=None)
