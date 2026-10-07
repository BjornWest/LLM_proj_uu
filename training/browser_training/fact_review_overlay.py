"""Exact-source isolated native-review renderer copies with private part spans.

No Website module is written or monkeypatched. Bindings are native producer
identities, not new Product assertion IDs. Unknown disclosure stays unknown.
"""
from contextvars import ContextVar
from functools import wraps
from hashlib import sha256
from html import escape
import json
import re
from types import ModuleType

from .fact_exposure import object_digest, utf16_length
from .fact_render_overlay import ASSET, _once

_ACTIVE=ContextVar('fact_review_render',default=None)
_ATTRIBUTE='data-fr-review'


class _Render:
    def __init__(self, site, route, query, pins):
        self.site=site; self.route=route; self.query=dict(query); self.pins=pins; self.records=[]

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
    matches=[key for key,value in page.products.items() if value is p]
    if pid is None:
        if len(matches)!=1:raise ValueError('Review summary lacks unique model identity')
        pid=matches[0]
    elif page.products.get(pid) is not p:raise ValueError('Review summary model mismatch')
    return pid


def review_average(page,p,pid):
    pid=_summary_identity(page,p,pid); value=str(p['rating_summary']['average_rating']);text=value+' / 5'
    return _element('<p class="rating-value">'+text+'</p>',text,
        {'authority':'renderer_native_review_aggregate','field':'average_rating','product_id':pid,
         'grain':'model','basis':'all_recorded_ratings_all_options_including_silent','displayed_value':p['rating_summary']['average_rating']},
        [_part('value',value),_part('scale','5',utf16_length(value+' / '))],
        {'product_id':pid,'grain':'model','rating_summary_sha256':object_digest(p['rating_summary'])})


def review_counts(page,p,pid):
    pid=_summary_identity(page,p,pid);s=p['rating_summary']
    segments=[('rating_count',str(s['rating_count']),' ratings; '),
              ('written_review_count',str(s['written_review_count']),' written reviews, '),
              ('rating_only_count',str(s['rating_only_count']),' ratings without comments.')]
    text=''.join(value+label for _,value,label in segments); html='<p>'+text+'</p>'
    # Three separately meaningful facts share this single original paragraph.
    render=_ACTIVE.get()
    if render is None:return html
    offset=0; records=[]
    for field,value,label in segments:
        parts=[_part('value',value,offset),_part('label',label,offset+utf16_length(value))]
        decorated=render.element(html,text,
            {'authority':'renderer_native_review_aggregate','field':field,'product_id':pid,
             'grain':'model','basis':'all_recorded_ratings_all_options_including_silent','displayed_value':s[field]},
            parts,{'product_id':pid,'grain':'model','rating_summary_sha256':object_digest(s)})
        records.append(render.records[-1]);offset+=utf16_length(value+label)
    # One element can have several factual registrations. They use the same
    # producer anchor, and the private adopter enrolls each without replacing it.
    anchor=records[0]['anchor']
    for record in records:record['anchor']=anchor
    return re.sub(r'^(<p)',lambda m:m.group(1)+f' {_ATTRIBUTE}="{anchor}"',html,count=1)


def review_histogram(page,p,pid,stars,count,label):
    pid=_summary_identity(page,p,pid); plain=f'{stars} stars';text=plain+str(count)
    return _element(f'<tr><th scope="row">{label}</th><td>{count}</td></tr>',text,
        {'authority':'renderer_native_review_aggregate','field':'star_counts','stars':stars,
         'product_id':pid,'grain':'model','basis':'all_recorded_ratings_all_options_including_silent','displayed_value':count},
        [_part('stars',plain),_part('count',str(count),utf16_length(plain))],
        {'product_id':pid,'grain':'model','rating_summary_sha256':object_digest(p['rating_summary'])})


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
    payload={'registrations':render.records,'meta':{'kind':'static_review','root_selector':'#main',
        'state_kind':'static_review','state_key':'review:'+render.site,'draft':None,
        'site_id':render.site,'route':render.route,'query':render.query,
        'renderer_source_sha256':render.pins,'response_html_sha256':sha256(base.encode()).hexdigest()}}
    data=json.dumps(payload,ensure_ascii=True,separators=(',',':')).replace('<','\\u003c')
    script='\n<script type="application/json" id="fact-recording-private-data" data-fact-recording-private>'+data+'</script>\n<script src="/__fact-recorder-private.js" data-fact-recording-private></script>\n'
    if html.count('</body>')!=1:raise ValueError('Review document boundary changed')
    return html.replace('</body>',script+'</body>')


def copied_review_classes(surrounding_source,native_source,*,enabled=False,expected_sha256=None):
    """Compile isolated copies, refusing drift from explicitly approved sources.

    The returned classes alone are used by the copied runtime; shared imports and
    global renderer classes remain untouched. Native-rich layouts are in scope.
    Legacy inline opinion/fact surfaces and cards remain qualified unknown.
    """
    if type(enabled) is not bool:raise TypeError('Explicit recording boolean required')
    pins={name:sha256(source.encode()).hexdigest() for name,source in
          [('surrounding_pages',surrounding_source),('native_review_pages',native_source)]}
    if enabled and pins!=expected_sha256:raise ValueError('Review renderer source pins changed')
    surrounding=ModuleType('environments.website_world._fact_copy_surrounding');surrounding.__package__='environments.website_world'
    native=ModuleType('environments.website_world._fact_copy_native');native.__package__='environments.website_world'
    if enabled:
        surrounding_source=_once(surrounding_source,
            "histogram += f'<tr><th scope=\"row\">{label}</th><td>{counts[str(stars)]}</td></tr>'",
            "histogram += review_histogram(self,p,pid,stars,counts[str(stars)],label)")
        surrounding_source=_once(surrounding_source,
            'f\'<p class="rating-value">{s["average_rating"]} / 5</p><p>{s["rating_count"]} ratings; \'\n                f\'{s["written_review_count"]} written reviews, {s["rating_only_count"]} ratings without comments.</p>\'',
            'review_average(self,p,pid) + review_counts(self,p,pid) +')
        # The adjacent original literal needs an explicit concatenation now.
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
                    status,body,mime=super().page(route,query)
                    if status==200 and mime.startswith('text/html'):body=_finish(body,render)
                    return status,body,mime
                finally:_ACTIVE.reset(token)
        return RecordedReview
    return {'ReviewPage':wrapped(surrounding.ReviewPage),'NativeReviewPage':wrapped(native.NativeReviewPage),
            'receipt':{'enabled':enabled,'source_sha256':pins,'shared_files_modified':False,
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
