// Called privately before the original AX capture. No DOM, storage, assets,
// renderer globals, task or grader are changed. Cached public module exports
// identify facts; only exact existing text/control bindings are registered.
function nativeReviewProductId(route, href) {
  const raw=['reviews','models','model'].includes(route[0])?route[1]:
    href?.split('/reviews/')[1]?.split(/[?#]/)[0];
  return raw?decodeURIComponent(raw):null;
}
function nativeSelectedParts(product, variant) {
  let cursor='Selected: '.length;
  const entries=Object.entries(variant.selection), parts=[], labels=[];
  for(const [axis,value] of entries) {
    const label=product.options.find(o=>o.key===axis)?.label;
    if(!label)return null;
    const phrase=label+' '+value;
    parts.push({axis,value,parts:[{part:'label',start:cursor,end:cursor+label.length},
      {part:'value',start:cursor+label.length+1,end:cursor+phrase.length}]});
    labels.push(phrase);cursor+=phrase.length+' · '.length;
  }
  return {text:'Selected: '+labels.join(' · '),parts};
}
async function nativeFactProbe(config) {
  const root=document.querySelector('#app')||document.querySelector('main')||document.body;
  if(!root)throw new Error('native_root_unavailable');
  if(root.tagName==='MAIN'&&!root.id&&document.querySelectorAll('main').length!==1)throw new Error('ambiguous_native_main');
  let output;
  const recorder=createFactRecorder({enabled:true,sink:result=>{output=result;}});
  const site=config.site_id||location.origin, diagnostics=[];
  const base={authority:'native_existing_public_dom',site_id:site,source_family:'retailer'};
  const all=text=>[{part:'value',start:0,end:text.length}];
  function add(node,binding,state,parts=null,kind='text_node') {
    if(!node)return;
    const text=kind==='control_value'?String(node.value):node.textContent;
    if(!text.length)return;
    recorder.adopt(node,recorder.occurrence({...base,...binding},state),
      {text,parts:parts||all(text)},{kind});
  }
  function unique(nodes,expected,field,binding,state,parts=null) {
    const matches=[...nodes].filter(n=>n.textContent===expected);
    if(matches.length!==1){diagnostics.push({reason:'no_unique_native_text',field,match_count:matches.length});return;}
    add(matches[0],{field,...binding},state,parts);
  }
  const retailer=!!document.querySelector('#app');
  let draft=null;
  if(retailer) {
    // Both modules were already imported by shop.js. No quote refresh, fetch,
    // ensureProduct/ensureQuote or other asynchronous producer method is called.
    const catalog=await import(new URL('/catalog.js',location.href).href);
    const quotes=await import(new URL('/quote.js',location.href).href);
    const nativeSite=quotes.worldBinding?.siteId;
    if(!nativeSite)throw new Error('native_site_identity_unavailable');
    base.site_id=nativeSite;
    draft=JSON.parse(localStorage.getItem('website-drafts.state.'+nativeSite));
    if(!draft)throw new Error('native_draft_unavailable');
    const [path,query='']=location.hash.replace(/^#\/?/,'').split('?');
    const [role,id]=path.split('/');
    const params=Object.fromEntries(new URLSearchParams(query));
    const resolved=role==='product'?catalog.resolveProduct(id,draft.selection?.[id]||params):null;
    const p=resolved?.product,v=resolved?.variant;
    const snapshot=window.websiteDraftReview?.snapshot();
    const conf=snapshot?.configuration;
    if(snapshot?.site!==nativeSite||!conf)throw new Error('native_configuration_unavailable');
    const manifest=await import(new URL('/manifest.js',location.href).href);
    const money=value=>{
      const amount=value.toLocaleString('en-GB'),style=manifest.globals[conf.global].money;
      return style==='prefix'?'SEK '+amount:style==='code'?amount+' SEK':amount+' kr';
    };
    if(p&&v) {
      const pid=p.canonicalProductId??p.id;
      const state={site:nativeSite,product_id:pid,page_id:p.id,sku_id:v.skuId??null,
        offer_id:v.offerId??null,variant_key:v.key,page_configuration:{...p.pageKey},selection:{...v.selection}};
      const scope={product_id:pid,page_id:p.id,sku_id:v.skuId??null,offer_id:v.offerId??null};
      unique(root.querySelectorAll('main h1'),p.name,'product_name',{...scope,displayed_value:p.name},state);
      unique(root.querySelectorAll('main .amount'),money(v.price),'listing_price',
        {...scope,value:v.price,currency:'SEK',unit:'SEK_major',displayed_value:money(v.price)},state);
      const details=[...(v.details||[])];
      if(p.marketRange?.status==='known') {
        const ranges=await import(new URL('/market-range.js',location.href).href);
        details.push({facts:[{label:'Market range',value:ranges.rangeLabels[p.marketRange.value],
          field:'product.facts.market_range',status:'known'}]});
      }
      for(const group of details)for(const fact of group.facts||[]) {
        if(!fact.field&&!fact.slotId)continue;
        const valueText=Array.isArray(fact.value)?fact.value.map(String).join(''):String(fact.value);
        const expected=valueText+(fact.unit?' '+fact.unit:'')+(fact.qualifier||'');
        const candidates=[];
        for(const th of root.querySelectorAll('main th[scope="row"]')) {
          const cell=th.nextElementSibling;
          if(th.textContent===fact.label&&cell&&cell.textContent===expected)candidates.push([th,cell]);
        }
        for(const dt of root.querySelectorAll('main dt')) {
          const cell=dt.nextElementSibling;
          if(dt.textContent===fact.label&&cell?.tagName==='DD'&&cell.textContent===expected)candidates.push([dt,cell]);
        }
        if(candidates.length!==1){diagnostics.push({reason:'no_unique_native_fact_row',field:fact.field||fact.slotId,match_count:candidates.length});continue;}
        const [label,value]=candidates[0];
        const binding={...scope,field:fact.field??null,slot_id:fact.slotId??null,
          displayed_value:fact.value,unit:fact.unit??null,status:fact.status??null,
          assertions:fact.assertions||[],subject_type:fact.subjectType??null,subject_id:fact.subjectId??null};
        const occurrence=recorder.occurrence({...base,...binding},state);
        recorder.adopt(label,occurrence,{text:label.textContent,parts:[{part:'label',start:0,end:label.textContent.length}]});
        const parts=[{part:'value',start:0,end:valueText.length}];
        if(fact.unit)parts.push({part:'unit',start:valueText.length+1,end:valueText.length+1+fact.unit.length});
        if(fact.qualifier)parts.push({part:'qualifier',start:expected.length-fact.qualifier.length,end:expected.length});
        recorder.adopt(value,occurrence,{text:value.textContent,parts});
      }
      const selected=nativeSelectedParts(p,v);
      if(selected) {
        const rows=[...root.querySelectorAll('main p')].filter(n=>n.textContent===selected.text);
        if(rows.length===1)for(const part of selected.parts) {
          add(rows[0],{...scope,field:'sku.'+part.axis,displayed_value:part.value,status:'known'},state,part.parts);
        }
      }
    }
    for(const input of root.querySelectorAll('form[data-form="address"] input,form[data-form="address"] textarea')) {
      add(input,{field:'recipient_address.'+input.name,address_component:input.name,
        value:input.value},{site:nativeSite,draft},null,'control_value');
    }
    // quote() reads the original cached result. Pass a clone defensively: it
    // never schedules a quote or mutates the renderer's lexical draft.
    const q=quotes.quote(structuredClone(draft.cart),structuredClone(draft),conf,draft.revision);
    if(q?.quoteId&&!q.errors?.length) {
      const state={site:nativeSite,quote_id:q.quoteId,quote_result:q,draft};
      const panel=root.querySelector('[aria-label="Current quote"]');
      if(panel)for(const field of ['subtotal','discount','shipping','total']) {
        const labels={subtotal:'Products',discount:'Coupon discount',shipping:'Delivery charges',total:'Total'};
        const pairs=[...panel.querySelectorAll('dt')].filter(n=>n.textContent===labels[field]&&n.nextElementSibling?.textContent===money(q[field]));
        if(pairs.length===1)add(pairs[0].nextElementSibling,{field,value:q[field],currency:'SEK',quote_id:q.quoteId,authority:'renderer_native_quote_scalar'},state);
      }
      if(panel)for(const [i,s] of q.shipments.entries()) {
        const section=panel.querySelectorAll(':scope > ol > li > section')[i];
        if(!section)continue;
        const binding={quote_id:q.quoteId,shipment_index:i};
        const service=s.selected,serviceText=service.company+' — '+quotes.serviceTypes[service.type]+' — '+service.name;
        unique(section.querySelectorAll(':scope > p'),serviceText,'selected_service',
          {...binding,selected_service:service},state);
        unique(section.querySelectorAll(':scope > p'),service.location.name+' · '+service.location.address,
          'selected_location',{...binding,selected_location:service.location},state);
        const segments=[];
        for(const [j,line] of s.lines.entries()) {
          segments.push({text:line.product.name,part:'line-'+j+'.product_name'});
          if(Object.values(line.variant.selection).length) {
            segments.push({text:' · '});
            for(const [k,[axis,value]] of Object.entries(line.variant.selection).entries()) {
              if(k)segments.push({text:' / '});
              segments.push({text:value,part:'line-'+j+'.selection.'+axis});
            }
          }
          segments.push({text:' · Quantity '},{text:line.quantity,part:'line-'+j+'.quantity'});
        }
        const lines=fragment(segments);
        unique(section.querySelectorAll(':scope > ul'),lines.text,'public_quote_lines',
          {...binding,authority:'renderer_native_quote_line_listing',lines:s.lines.map(l=>({
            product_id:l.product.canonicalProductId??l.product.id,sku_id:l.variant.skuId,
            offer_id:l.variant.offerId,quantity:l.quantity,selection:l.variant.selection,name:l.product.name}))},state,lines.parts);
      }
    }
  } else {
    // Original Python-rendered pages already carry review IDs. Quantities are
    // parsed from the native renderer's explicit public summary grammar.
    const state={site_id:site,url:location.href,query:location.search};
    const route=location.pathname.split('/').filter(Boolean);
    const pid=nativeReviewProductId(route,null);
    base.source_family=document.querySelector('[data-review-id],.rating-panel')?'review':'comparison';
    for(const article of root.querySelectorAll('[data-review-id]')) {
      const link=article.querySelector('a[href*="/reviews/"]');
      const product=pid||nativeReviewProductId([],link?.getAttribute('href'));
      if(!product)continue;
      const scope={product_id:product,review_id:article.getAttribute('data-review-id')};
      const text=article.querySelector('blockquote');
      add(text,{...scope,field:'review_text',displayed_value:text?.textContent},{...state,...scope});
      const rating=article.querySelector('[role="img"][aria-label*=" out of 5"]');
      if(rating) {
        const match=rating.getAttribute('aria-label').match(/^([1-5]) out of 5(?: stars)?$/);
        if(match&&rating.textContent.trim().length)add(rating,{...scope,field:'rating',value:Number(match[1])},{...state,...scope});
      }
    }
    if(pid)for(const panel of root.querySelectorAll('.rating-panel')) {
      const scope={product_id:pid},average=panel.querySelector('.rating-value');
      const m=average?.textContent.match(/^(\d+(?:\.\d+)?) \/ 5$/);
      if(m)add(average,{...scope,field:'average_rating',value:Number(m[1])},state);
      for(const row of panel.querySelectorAll('p')) {
        const counts=row.textContent.match(/^(\d+) ratings; (\d+) written reviews, (\d+) ratings without comments\.$/);
        if(!counts)continue;
        const names=['rating_count','written_review_count','rating_only_count'];let start=0;
        for(let i=0;i<names.length;i++) {
          const pos=row.textContent.indexOf(counts[i+1],start);start=pos+counts[i+1].length;
          add(row,{...scope,field:names[i],value:Number(counts[i+1])},state,[{part:'value',start:pos,end:start}]);
        }
      }
    }
  }
  recorder.commit(root,{kind:'native_private_probe',url:location.href,
    root_selector:root.id?'#'+root.id:root.tagName==='MAIN'?'main':'body',state_kind:retailer?'local_storage':'static_review',
    state_key:retailer?'website-drafts.state.'+base.site_id:'native-static:'+site,draft});
  output.diagnostics.push(...diagnostics);
  output.revision=config.revision;
  return output;
}
