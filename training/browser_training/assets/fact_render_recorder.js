// Opt-in renderer provenance. Intended to be served only in an isolated overlay.
// No assertion registry, hidden preferences, tasks, or grader data belong here.
const clone = value => JSON.parse(JSON.stringify(value));
const escape = text => String(text).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

export function fragment(segments) {
  let html='', text=''; const parts=[];
  for (const segment of segments) {
    const value=String(segment.text ?? ''), start=text.length;
    html += segment.html ?? escape(value); text += value;
    if (segment.part && value.length) parts.push({part:segment.part,start,end:text.length});
  }
  return {html,text,parts}; // JS string offsets are UTF-16 code units.
}

// This function is also evaluated by the private Python collector. Keep it
// self-contained. Only BrowserGym's pinned bookkeeping is normalized; ordinary
// attributes/text/child order and live control state remain part of the check.
export function renderAttestation(root) {
  const ignored=new Set(['bid','browsergym_visibility_ratio','browsergym_set_of_marks']);
  function visit(node) {
    const properties={};
    if(node.nodeType===1) {
      for(const key of ['value','checked','selected','indeterminate']) {
        if(typeof node[key]!=='undefined') properties[key]=node[key];
      }
    }
    const attributes=node.nodeType===1?Array.from(node.attributes)
      .filter(({name})=>!ignored.has(name) && !(name==='value' && 'value' in properties)
        && !(name==='checked' && 'checked' in properties))
      .map(({name,value})=>[name,value]).sort((a,b)=>a[0]<b[0]?-1:a[0]>b[0]?1:0):[];
    if(node.shadowRoot) throw new Error('Shadow render attestation is not qualified');
    return [node.nodeType,node.nodeName,node.nodeValue,attributes,properties,
      Array.from(node.childNodes,visit)];
  }
  if(!root) throw new Error('Missing render root');
  return {schema:'fact-render-state-browsergym-v1',tree:visit(root)};
}

export function createFactRecorder({enabled=false, sink=null, attribute='data-fr-occurrence'}={}) {
  if (!enabled) return Object.freeze({enabled:false, begin(){}, occurrence(){return null;},
    element(html){return html;}, adopt(){}, commit(){return null;}});
  if (typeof sink !== 'function') throw new TypeError('Enabled recording requires a private sink');
  if (!/^data-[a-z0-9-]+$/.test(attribute)) throw new TypeError('Opaque data attribute required');
  let serial=0, revision=0, pending=new Map(), active=new Map();
  function occurrence(binding,effectiveState) {
    return {id:`o${++serial}`,binding:clone(binding),effective_state:clone(effectiveState)};
  }
  function element(html, occurrence, content, {kind='text_node'}={}) {
    if (!occurrence || !['text_node','control_value'].includes(kind)) throw new TypeError('Bound occurrence required');
    if (!/^<[a-z][^>]*>/i.test(html) || typeof content.text!=='string' || !Array.isArray(content.parts)) throw new TypeError('Existing element and explicit fragment required');
    for(const part of content.parts) {
      if (!Number.isInteger(part.start)||!Number.isInteger(part.end)||part.start<0||part.end<=part.start||part.end>content.text.length) throw new TypeError('Invalid UTF-16 part interval');
    }
    const key=`a${++serial}`;
    pending.set(key,{key,occurrence:clone(occurrence),content:clone(content),kind});
    return html.replace(/^(<[a-z][^\s/>]*)/i, `$1 ${attribute}="${key}"`);
  }
  function adopt(node, occurrence, content) {
    // Private Python-rendered documents already contain existing-element anchors.
    // Reuse element() validation; no replacement node or fact text is inserted.
    if(!node || node.nodeType!==1) throw new TypeError('Existing element required');
    const tagged=element('<p></p>',occurrence,content);
    const key=tagged.match(new RegExp(`${attribute}="([^"]+)"`))[1];
    // Several facts may occupy the very same paragraph. Enroll each privately;
    // a single data attribute would otherwise overwrite earlier registrations.
    const record=pending.get(key);pending.delete(key);
    active.set(key,{...record,element:node});
  }
  function commit(root, meta={}) {
    const diagnostics=[];
    for(const [key,record] of active) if(!root.contains(record.element)) active.delete(key);
    for(const element of root.querySelectorAll(`[${attribute}]`)) {
      const key=element.getAttribute(attribute),record=pending.get(key);
      element.removeAttribute(attribute); // No public metadata remains after this synchronous hook.
      if (!record || active.has(key)) {diagnostics.push({key,reason:'unregistered_or_duplicate_anchor'});continue;}
      active.set(key,{...record,element});pending.delete(key);
    }
    // Nonselected tabs/render branches may build HTML that is never inserted.
    // Those are not DOM occurrences and cannot establish an exposure inventory.
    pending.clear();
    const registrations=[];
    for(const [key,record] of active) {
      const actual=record.kind==='control_value'?String(record.element.value):record.element.textContent;
      if(actual!==record.content.text) {
        diagnostics.push({key,occurrence_id:record.occurrence.id,reason:'rendered_content_changed',expected:record.content.text,actual});
        active.delete(key);continue;
      }
      const runs=[];
      if(record.kind==='control_value') runs.push({relative_child_path:[],kind:record.kind,text:actual,start:0,end:actual.length});
      else {
        let offset=0;
        function visit(node,path) {
          if(node.nodeType===3) {const text=node.nodeValue; if(text.length) runs.push({relative_child_path:path,kind:'text_node',text,start:offset,end:offset+text.length});offset+=text.length;}
          for(let i=0;i<node.childNodes.length;i++) visit(node.childNodes[i],[...path,i]);
        }
        visit(record.element,[]);
      }
      const parts=record.content.parts.map(part=>({...part,ranges:runs.flatMap((run,index)=>{
        const start=Math.max(part.start,run.start),end=Math.min(part.end,run.end);
        return end>start?[{run_index:index,start:start-run.start,end:end-run.start}]:[];
      })}));
      // Preserve node references privately for CDP conversion within this commit.
      const element_path=[];
      for(let node=record.element;node!==root;node=node.parentNode) element_path.unshift([...node.parentNode.childNodes].indexOf(node));
      registrations.push({key,occurrence:record.occurrence,kind:record.kind,text:actual,runs,parts,element_path});
    }
    const result={schema:'fact-render-dom-v1',offset_unit:'utf16_code_units',revision:++revision,
      meta:{...clone(meta),render_state:renderAttestation(root)},registrations,diagnostics};
    sink(result);return result;
  }
  return Object.freeze({enabled:true,begin(){pending.clear();},occurrence,element,adopt,commit});
}
