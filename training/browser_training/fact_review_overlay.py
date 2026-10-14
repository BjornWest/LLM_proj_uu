"""Exact-source isolated native-review renderer copies with private part spans.

No Website module is written or monkeypatched. Bindings are native producer
identities, not new Product assertion IDs. Unknown disclosure stays unknown.
"""
from contextvars import ContextVar
from functools import wraps
from hashlib import sha256
from html import escape
import importlib.util
import json
from pathlib import Path
import re
from types import ModuleType

from .fact_exposure import object_digest, utf16_length
from .fact_render_overlay import ASSET, _once

_ACTIVE=ContextVar('fact_review_render',default=None)
_BYPASS=ContextVar('fact_review_registration_bypass',default=False)
_ATTRIBUTE='data-fr-review'
LEGACY_RENDERER_PINS={
    'surrounding_pages':'666a2e3113e2b0d7d28a8c1b46db9b40d40158dfcea475a221b03fc445cc2d8e',
    'native_review_pages':'961db9223afbdc44c6192a144dfd0a10103066e5448f8762405066ee9dd286fc'}
SKU_RENDERER_PINS={
    'surrounding_pages':'8a64435bc28336a48531979c599bba54008fe49dcf74161c98afc004218e9887',
    'native_review_pages':'8485565a115e71980e1583432c3bf451156e9c4b336e08503323344f0bc4f692'}
SKU_SCOPE_PIN='93e1483a5c5989d33d291af4086aae94a2dabff0ed621038dd2b9ed24c4af24e'
POPULATION_PIN='d5bd30b5e5dd1d674898439d99e812789e4562c1875468ef2424098e6585ab5c'


class _RegistrationError(ValueError):
    pass


class _Render:
    def __init__(self, site, route, query, pins):
        self.site=site; self.route=route; self.query=dict(query); self.pins=pins; self.records=[]; self.diagnostics=[]

    def element(self, html, text, binding, parts, state):
        number=len(self.records)+1
        identity=f'review-{number}'
        binding={**binding,'site_id':self.site,'source_family':'product_reviews'}
        self.records.append({'anchor':identity,
            'occurrence':{'id':identity,'binding':binding,'effective_state':state},
            'content':{'text':text,'parts':parts}})
        return re.sub(r'^(<[a-z][^\s/>]*)',lambda m:m.group(1)+f' {_ATTRIBUTE}="{identity}"',html,count=1)


def _part(name,text,start=0):
    return {'part':name,'start':start,'end':start+utf16_length(text)}


def _element(html,text,binding,parts,state):
    render=_ACTIVE.get()
    return render.element(html,text,binding,parts,state) if render is not None else html


def review_facts(pid, values, public_facts, pretty, e):
    values=public_facts(values)
    if not values:return ''
    rows=[]
    for key,value in values.items():
        label=key.replace('_',' ').capitalize(); displayed=pretty(value)
        binding={'authority':'native_public_field','field':key,'product_id':pid,
                 'subject_type':'product','subject_id':pid,'displayed_value':value,'grain':'model'}
        state={'product_id':pid,'grain':'model','public_facts_sha256':object_digest(values)}
        # Separate nodes share one occurrence and conjunctive label/value parts.
        render=_ACTIVE.get()
        if render is None:rows.append(f'<dt>{e(label)}</dt><dd>{e(displayed)}</dd>');continue
        first=render.element(f'<dt>{e(label)}</dt>',label,binding,[_part('label',label)],state)
        second=render.element(f'<dd>{e(displayed)}</dd>',displayed,binding,[_part('value',displayed)],state)
        render.records[-1]['occurrence']['id']=render.records[-2]['occurrence']['id']
        rows.append(first+second)
    return '<dl>'+''.join(rows)+'</dl>'


def review_opinion(pid,row,e):
    text=row['text']
    return _element('<blockquote>'+e(text)+'</blockquote>',text,
        {'authority':'renderer_native_review_text','field':'review_text','product_id':pid,
         'review_id':row['review_id'],'sku_id':row['sku_id'],'reviewer':row['reviewer'],'grain':'review'},
        [_part('text',text)],{'product_id':pid,'sku_id':row['sku_id'],'review_id':row['review_id'],
                           'review_text_sha256':sha256(text.encode()).hexdigest()})


def _summary_identity(page,p,pid):
    if getattr(page,'_fact_modern_summary',False) and p.get('sku_id') is not None:
        # Only the exact producer public projection is admitted, never a query
        # alone or a model object relabelled as an option summary.
        if (type(pid) is not str or set(p)!={'product_id','sku_id','rating_summary'} or
                p['product_id']!=pid or pid not in page.products):
            raise _RegistrationError('Review summary lacks exact SKU/product identity')
        sid=p['sku_id'];product=page.products[pid]
        matches=[s for s in product['skus'] if s['sku_id']==sid and s.get('product_id')==pid]
        helper=getattr(page,'_fact_sku_rating_summary',None)
        if len(matches)!=1 or not callable(helper):
            raise _RegistrationError('Review summary lacks unique checked SKU projection')
        if object_digest(p['rating_summary'])!=object_digest(helper(product,sid)):
            raise _RegistrationError('Review summary differs from the complete public SKU corpus')
        return pid
    matches=[key for key,value in page.products.items() if value is p]
    if pid is None:
        if len(matches)!=1:raise _RegistrationError('Review summary lacks unique model identity')
        pid=matches[0]
    elif page.products.get(pid) is not p:raise _RegistrationError('Review summary model mismatch')
    return pid


def _aggregate_scope(page,p,pid):
    pid=_summary_identity(page,p,pid)
    binding={'product_id':pid,'grain':'model',
             'basis':'all_recorded_ratings_all_options_including_silent'}
    state={'product_id':pid,'grain':'model',
           'rating_summary_sha256':object_digest(p['rating_summary'])}
    if getattr(page,'_fact_modern_summary',False) and p.get('sku_id') is not None:
        binding.update(sku_id=p['sku_id'],grain='sku',
                       basis='all_recorded_ratings_one_option_including_silent')
        state.update(sku_id=p['sku_id'],grain='sku')
    return binding,state


def review_average(page,p,pid,rendered_mean=None):
    if _BYPASS.get():
        text=rendered_mean if rendered_mean is not None else str(p['rating_summary']['average_rating'])+' / 5'
        return '<p class="rating-value">'+escape(text)+'</p>'
    scope,state=_aggregate_scope(page,p,pid);summary=p['rating_summary']
    value=str(summary['average_rating']);text=value+' / 5'
    binding={'authority':'renderer_native_review_aggregate','field':'average_rating',
             **scope,'displayed_value':summary['average_rating']}
    if rendered_mean is not None:
        if not summary['rating_count']:
            text='Mean rating undefined (no ratings)'
            parts=[_part('status',text)]
            binding.update(displayed_value=None,value_status='undefined_no_ratings')
        else:
            value=str(summary.get('mean_rounded',summary['average_rating']));text=value+' / 5'
            parts=[_part('value',value),_part('scale','5',utf16_length(value+' / '))]
            if 'mean_rounded' in summary:
                if not re.fullmatch(r'[1-5]\.\d{2}',value) or not 1<=float(value)<=5:
                    raise _RegistrationError('Review mean has an unsupported public numeric format')
                binding.update(displayed_value=float(value),rendered_value=value,
                               value_basis='rounded_public_mean' if scope['grain']=='sku' else 'public_displayed_mean')
        if rendered_mean!=text:raise _RegistrationError('Review mean differs from its producer display')
        html='<p class="rating-value">'+escape(text)+'</p>'
    else:
        parts=[_part('value',value),_part('scale','5',utf16_length(value+' / '))]
        html='<p class="rating-value">'+text+'</p>'
    return _element(html,text,binding,parts,state)


def review_counts(page,p,pid):
    s=p['rating_summary']
    segments=[('rating_count',str(s['rating_count']),' ratings; '),
              ('written_review_count',str(s['written_review_count']),' written reviews, '),
              ('rating_only_count',str(s['rating_only_count']),' ratings without comments.')]
    text=''.join(value+label for _,value,label in segments); html='<p>'+text+'</p>'
    if _BYPASS.get():return html
    scope,state=_aggregate_scope(page,p,pid)
    # Three separately meaningful facts share this single original paragraph.
    render=_ACTIVE.get()
    if render is None:return html
    offset=0; records=[]
    for field,value,label in segments:
        parts=[_part('value',value,offset),_part('label',label,offset+utf16_length(value))]
        decorated=render.element(html,text,
            {'authority':'renderer_native_review_aggregate','field':field,**scope,'displayed_value':s[field]},
            parts,state)
        records.append(render.records[-1]);offset+=utf16_length(value+label)
    # One element can have several factual registrations. They use the same
    # producer anchor, and the private adopter enrolls each without replacing it.
    anchor=records[0]['anchor']
    for record in records:record['anchor']=anchor
    return re.sub(r'^(<p)',lambda m:m.group(1)+f' {_ATTRIBUTE}="{anchor}"',html,count=1)


def review_histogram(page,p,pid,stars,count,label):
    if _BYPASS.get():return f'<tr><th scope="row">{label}</th><td>{count}</td></tr>'
    scope,state=_aggregate_scope(page,p,pid); plain=f'{stars} stars';text=plain+str(count)
    return _element(f'<tr><th scope="row">{label}</th><td>{count}</td></tr>',text,
        {'authority':'renderer_native_review_aggregate','field':'star_counts','stars':stars,
         **scope,'displayed_value':count},
        [_part('stars',plain),_part('count',str(count),utf16_length(plain))],
        state)


def private_review_script():
    # The native Host permits same-origin scripts and blocks inline execution.
    # Keep the payload inert; source bytes are served only by the copied class.
    library=ASSET.read_text().replace('export function ','function ')
    return '(()=>{\n'+library+'''\nconst data=document.getElementById('fact-recording-private-data');
const payload=JSON.parse(data.textContent);data.remove();
const root=document.querySelector('#main');
const nodes=new Map();
for(const node of root.querySelectorAll('[data-fr-review]')) {
  const key=node.getAttribute('data-fr-review');
  if(nodes.has(key))throw new Error('Duplicate review anchor');
  nodes.set(key,node);node.removeAttribute('data-fr-review');
}
try {
  const recorder=createFactRecorder({enabled:true,sink:record=>{
    record.meta.html=root.outerHTML;
    record.diagnostics.push(...(payload.meta.recording_diagnostics||[]));
    if(globalThis.__recordFactCommit)globalThis.__recordFactCommit(record);
  }});
  for(const registration of payload.registrations) {
    const node=nodes.get(registration.anchor);
    if(node)recorder.adopt(node,registration.occurrence,registration.content);
  }
  const commit=()=>recorder.commit(root,{...payload.meta,url:location.href});
  commit();
  for(const kind of ['toggle','change','input'])root.addEventListener(kind,commit,true);
} catch(error) { console.error('Private fact recording unavailable',error); }
})();\n'''


def _finish(html, render):
    base=re.sub(r' '+_ATTRIBUTE+r'="review-\d+"','',html)
    records=render.records
    if render.pins.get('review_rating_scopes')==SKU_SCOPE_PIN:
        # Editorial parts construct then discard other sections. Their private
        # registrations must not turn un-emitted facts into available content.
        anchors=set(re.findall(r' '+_ATTRIBUTE+r'="(review-\d+)"',html))
        records=[record for record in records if record['anchor'] in anchors]
    payload={'registrations':records,'meta':{'kind':'static_review','root_selector':'#main',
        'state_kind':'static_review','state_key':'review:'+render.site,'draft':None,
        'site_id':render.site,'route':render.route,'query':render.query,
        'renderer_source_sha256':render.pins,'response_html_sha256':sha256(base.encode()).hexdigest()}}
    if render.diagnostics:payload['meta']['recording_diagnostics']=render.diagnostics
    data=json.dumps(payload,ensure_ascii=True,separators=(',',':')).replace('<','\\u003c')
    script='\n<script type="application/json" id="fact-recording-private-data" data-fact-recording-private>'+data+'</script>\n<script src="/__fact-recorder-private.js" data-fact-recording-private></script>\n'
    if html.count('</body>')!=1:raise ValueError('Review document boundary changed')
    return html.replace('</body>',script+'</body>')


def copied_review_classes(surrounding_source,native_source,*,enabled=False,expected_sha256=None,
                          rating_scope_source=None):
    """Compile isolated copies, refusing drift from explicitly approved sources.

    The returned classes alone are used by the copied runtime; shared imports and
    global renderer classes remain untouched. Native-rich layouts are in scope.
    Legacy inline opinion/fact surfaces and cards remain qualified unknown.
    """
    if type(enabled) is not bool:raise TypeError('Explicit recording boolean required')
    pins={name:sha256(source.encode()).hexdigest() for name,source in
          [('surrounding_pages',surrounding_source),('native_review_pages',native_source)]}
    modern=pins==SKU_RENDERER_PINS
    private_scope=None
    if rating_scope_source is not None:
        scope_pin=sha256(rating_scope_source.encode()).hexdigest()
        if not modern or scope_pin!=SKU_SCOPE_PIN:
            raise ValueError('Review SKU scope source pin changed')
        pins['review_rating_scopes']=scope_pin
    if modern and rating_scope_source is None:
        raise ValueError('Review SKU copies require their pinned scope source')
    if enabled and not modern and pins!=LEGACY_RENDERER_PINS:
        raise ValueError('Review renderer source pins changed: unsupported pair')
    if enabled and pins!=expected_sha256:raise ValueError('Review renderer source pins changed')
    surrounding=ModuleType('environments.website_world._fact_copy_surrounding');surrounding.__package__='environments.website_world'
    native=ModuleType('environments.website_world._fact_copy_native');native.__package__='environments.website_world'
    if rating_scope_source is not None:
        # This native dependency is stdlib-only; execute its checked source in a
        # private namespace rather than use an ambient module or bytecode cache.
        spec=importlib.util.find_spec('environments.product_world.review_population')
        if spec is None or not isinstance(spec.origin,str) or not spec.origin.endswith('.py'):
            raise ValueError('Review population dependency requires a pinned Python source')
        try:population_source=Path(spec.origin).read_bytes()
        except OSError as error:
            raise ValueError('Review population dependency source is unavailable') from error
        if sha256(population_source).hexdigest()!=POPULATION_PIN:
            raise ValueError('Review population dependency source pin changed')
        population=ModuleType('environments.product_world._fact_copy_review_population')
        exec(compile(population_source,'<copied review_population>','exec'),population.__dict__)
        private_scope=ModuleType('environments.website_world._fact_copy_rating_scopes')
        private_scope.__package__='environments.website_world'
        rating_scope_source=_once(rating_scope_source,
            'from environments.product_world.review_population import summarize_ratings','')
        private_scope.__dict__['summarize_ratings']=population.summarize_ratings
        exec(compile(rating_scope_source,'<copied review_rating_scopes>','exec'),private_scope.__dict__)
        surrounding_source=_once(surrounding_source,
            'from .review_rating_scopes import sku_rating_summary','')
        surrounding.__dict__['sku_rating_summary']=private_scope.sku_rating_summary
    if enabled:
        surrounding_source=_once(surrounding_source,
            "histogram += f'<tr><th scope=\"row\">{label}</th><td>{counts[str(stars)]}</td></tr>'",
            "histogram += review_histogram(self,p,pid,stars,counts[str(stars)],label)")
        if modern:
            surrounding_source=_once(surrounding_source,
                'f\'<p class="rating-value">{e(mean)}</p><p>{s["rating_count"]} ratings; \'\n                f\'{s["written_review_count"]} written reviews, {s["rating_only_count"]} ratings without comments.</p>\'',
                'review_average(self,p,pid,mean) + review_counts(self,p,pid) +')
            surrounding_source=_once(surrounding_source,
                'f\'<section class="rating-panel" aria-label="{e(heading)} summary"><h2>{e(heading)}</h2>\'\n                review_average',
                'f\'<section class="rating-panel" aria-label="{e(heading)} summary"><h2>{e(heading)}</h2>\' +\n                review_average')
        else:
            surrounding_source=_once(surrounding_source,
                'f\'<p class="rating-value">{s["average_rating"]} / 5</p><p>{s["rating_count"]} ratings; \'\n                f\'{s["written_review_count"]} written reviews, {s["rating_only_count"]} ratings without comments.</p>\'',
                'review_average(self,p,pid) + review_counts(self,p,pid) +')
            surrounding_source=_once(surrounding_source,
                'f\'<section class="rating-panel" aria-label="Customer rating summary"><h2>Customer rating</h2>\'\n                review_average',
                'f\'<section class="rating-panel" aria-label="Customer rating summary"><h2>Customer rating</h2>\' +\n                review_average')
        native_source=_once(native_source,"+ facts(values) + '</section>' if values else ''",
            "+ review_facts(pid,values,public_facts,pretty,e) + '</section>' if values else ''")
        native_source=_once(native_source,"+ '</p><blockquote>' + e(row['text']) + '</blockquote><details><summary>Reviewed option</summary>'",
            "+ '</p>' + review_opinion(pid,row,e) + '<details><summary>Reviewed option</summary>'")
    surrounding.__dict__.update(review_histogram=review_histogram,review_average=review_average,review_counts=review_counts)
    exec(compile(surrounding_source,'<copied surrounding_pages>','exec'),surrounding.__dict__)
    native_source=_once(native_source,'from .surrounding_pages import ReviewPage, e, link, path, pretty, fact_section, facts','')
    native.__dict__.update({key:surrounding.__dict__[key] for key in
        ('ReviewPage','e','link','path','pretty','fact_section','facts','public_facts')})
    native.__dict__.update(review_facts=review_facts,review_opinion=review_opinion)
    exec(compile(native_source,'<copied native_review_pages>','exec'),native.__dict__)
    def wrapped(cls):
        if not enabled:return cls
        class RecordedReview(cls):
            _fact_modern_summary=modern
            def __init__(self,site,*args,**kwargs):
                site_id=site.get('site_id',site.get('id'))
                if not isinstance(site_id,str) or not site_id:
                    raise ValueError('Canonical review site identity required')
                super().__init__(site,*args,**kwargs)
                self._fact_site_id=site_id
            @wraps(cls.page)
            def page(self,route,query):
                if route=='/__fact-recorder-private.js':
                    if query:return 400,'Private recording asset takes no query','text/plain'
                    return 200,private_review_script(),'text/javascript; charset=utf-8'
                render=_Render(self._fact_site_id,route,query,pins);token=_ACTIVE.set(render)
                try:
                    try:status,body,mime=super().page(route,query)
                    except _RegistrationError as error:
                        # Recording cannot replace an otherwise valid native
                        # response. Re-render with the active hooks disabled.
                        _ACTIVE.reset(token);token=None
                        if not modern:raise
                        bypass=_BYPASS.set(True)
                        try:status,body,mime=super().page(route,query)
                        finally:_BYPASS.reset(bypass)
                        failure={'reason':'review_registration_rejected',
                            'error_type':type(error).__name__,'detail':str(error)}
                        render.records=[];render.diagnostics.append(failure)
                        if status==200 and mime.startswith('text/html'):body=_finish(body,render)
                        return status,body,mime
                    if status==200 and mime.startswith('text/html'):body=_finish(body,render)
                    return status,body,mime
                finally:
                    if token is not None:_ACTIVE.reset(token)
        if private_scope is not None:
            RecordedReview._fact_sku_rating_summary=staticmethod(private_scope.sku_rating_summary)
        return RecordedReview
    return {'ReviewPage':wrapped(surrounding.ReviewPage),'NativeReviewPage':wrapped(native.NativeReviewPage),
            'receipt':{'enabled':enabled,'source_sha256':pins,
                       'native_dependency_sha256':{'review_population':POPULATION_PIN} if private_scope is not None else {},
                       'shared_files_modified':False,
                       'inventory_complete':False,'producer_qualified':False}}


def copied_review_mount(source,classes,*,expected_sha256):
    """Private module for a copied Runtime, before hosts bind view.page.

    Changing runtime.surrounding_views after host creation would not replace the
    bound HTTP handler. Assign this module's mount callable only to the copied Runtime namespace's
    mount_surrounding global before construction; never to the shared Runtime module.
    """
    if sha256(source.encode()).hexdigest()!=expected_sha256:
        raise ValueError('Surrounding mount source pin changed')
    module=ModuleType('environments.website_world._fact_copy_mount')
    module.__package__='environments.website_world'
    exec(compile(source,'<copied surrounding mount>','exec'),module.__dict__)
    module.NativeReviewPage=classes['NativeReviewPage']
    module.ReviewPage=classes['ReviewPage']
    return module
