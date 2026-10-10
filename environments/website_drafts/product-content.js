// Presentation helpers over the supplied public content, without fact sampling.
export function presentFact(fact) {
  if(![undefined,'known'].includes(fact.status)||fact.value==null)return false;
  if(typeof fact.value==='string')return !!fact.value.trim();
  if(Array.isArray(fact.value))return fact.value.length>0;
  return true; // A known false or zero remains a meaningful declaration.
}
export function optionalParagraph(value, escape) {
  return typeof value === 'string' && value.trim() ? `<p>${escape(value)}</p>` : '';
}

export function normalizeProductContent(product) {
  const list = (value, name) => {
    if (value == null) return [];
    if (!Array.isArray(value)) throw new TypeError(`${name} must be a list`);
    return value;
  };
  const introduction = product.introduction ?? '';
  if (typeof introduction !== 'string') throw new TypeError('Introduction must be text');
  return {...product, introduction, descriptions:list(product.descriptions, 'Descriptions'),
    variants:product.variants.map(variant => ({...variant,
      details:list(variant.details, 'Details').map(group => ({...group, facts:list(group.facts, 'Facts').filter(presentFact)})).filter(group=>group.facts.length)
    }))};
}

export function informationTabs(description, details, current) {
  const labels = {...(description ? {description:'Description'} : {}),
    ...(details ? {details:'Product details'} : {}), delivery:'Availability & delivery'};
  return {labels, active:Object.hasOwn(labels, current) ? current : Object.keys(labels)[0]};
}

export function highlightFacts(variant, limit = 2) {
  if (Object.hasOwn(variant, 'highlights')) {
    return [...variant.highlights].filter(f=>f.status==='known'&&f.value!=null)
      .sort((a,b)=>b.priority-a.priority).slice(0,limit);
  }
  const preferred = ['Main material', 'Component materials', 'Capacity', 'Nominal capacity', 'Construction', 'Wearing style', 'Key mechanism', 'Heel', 'Fastening', 'Body width'];
  const facts = (variant.details || []).flatMap(group => {
    if (group.role) return group.role === 'descriptive' ? group.facts : [];
    // Compatibility with the historical authoring fixture. Live adapters declare
    // roles, so translated/reordered headings do not determine eligibility.
    return group.heading === 'Selected options' ? [] : group.facts;
  }).filter(f => (f.status === undefined || f.status === 'known') && f.value !== null && f.value !== undefined);
  const rank = fact => preferred.includes(fact.label) ? preferred.indexOf(fact.label) : preferred.length;
  return [...facts].sort((a, b) => rank(a) - rank(b)).slice(0, limit);
}
