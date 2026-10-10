// Local authoring content plan. Production generation should export this before
// layout sampling. No task, shopper state, stock preference or page-unit inputs.
import {shuffled} from './manifest.js';
import {availableRanges} from './market-range.js';

const collectionCopy = {
  Footwear: {title:'Everyday journeys', intro:'Walking shoes, boots and everyday footwear for the journeys ahead.', note:'Explore the different shoe types, then check the size and configuration on the product page.'},
  Home: {title:'Objects for everyday living', intro:'Useful pieces for the kitchen, desk and the spaces you spend time in.', note:'Browse by product type to find the dimensions, materials and options for each piece.'},
  Outdoors: {title:'Time outside', intro:'Equipment for walking, camping and carrying the essentials.', note:'Explore packs, camp equipment and the rest of our outdoor range.'},
  Electronics: {title:'Work, listen and connect', intro:'Everyday electronics for a place to work and time to listen.', note:'Browse the individual product types to check connections, configurations and specifications.'},
  Apparel: {title:'Layers for the day', intro:'Clothing for everyday wear and time outdoors.', note:'Choose a range, then check the measurements and available sizes for each garment.'},
  Pets: {title:'At home with pets', intro:'Bowls and everyday supplies for the animals who share your home.', note:'Check the listed capacity and materials on the product page before choosing an option.'},
};

export function homeContent(assortment, seed) {
  const categories=[...new Set(assortment.map(p=>p.category))];
  const departments=categories.map(category=>({category,
    ...(collectionCopy[category] || {title:category,intro:`Explore our ${category.toLowerCase()} range.`,note:'Check the individual product page for details and options.'}),
    types:[...new Set(assortment.filter(p=>p.category===category).map(p=>p.type))],
    ranges:availableRanges(assortment.filter(p=>p.category===category)),
  }));
  const brandNames=[...new Set(assortment.map(p=>p.brand))];
  return {
    departments,
    collections:shuffled(departments,seed,'home:collections').slice(0,3),
    brands:shuffled(brandNames,seed,'home:brands').slice(0,6).map(name=>({name,
      categories:categories.filter(category=>assortment.some(p=>p.category===category&&p.brand===name)),
    })),
    showcase:shuffled(assortment,seed,'home:showcase').slice(0,4),
  };
}
