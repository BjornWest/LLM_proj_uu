/* Illustrative shopping evidence. No retailers, prices or claims here are real. */
(() => {
  'use strict';
  const capture=id=>new URL('citation-demo-v40.html#'+id,window.location.href).href;
  const shared={checkedAt:'2026-10-07T10:42:00+02:00',checkedLabel:'Example check · 7 Oct, 10:42',illustrative:true};
  const sources=[
    {...shared,id:'offer',kind:'offer',siteName:'Retailer A',url:capture('offer'),title:'Aster H2 · Black · New',metric:{value:'€149',label:'Item price'},facts:[{label:'Availability',value:'In stock'},{label:'Condition',value:'New'},{label:'Shipping',value:'See source 2'}],evidence:'Aster H2 wireless headphones. Colour: Black. Condition: New. €149. In stock. Delivery calculated separately.'},
    {...shared,id:'delivery',kind:'delivery',siteName:'Retailer A',url:capture('delivery'),title:'Delivery to Zone A (example)',metric:{value:'€19',label:'Shipping'},facts:[{label:'Estimated arrival',value:'2–3 business days'},{label:'Service',value:'Home delivery'},{label:'Applies to',value:'1 × Aster H2 · Zone A'}],evidence:'Home delivery to Zone A: €19. Estimated arrival in 2–3 business days. Quote shown for one Aster H2 in the basket.'},
    {...shared,id:'review',kind:'review',siteName:'Review site',url:capture('review'),title:'Retailer A · Customer reviews',metric:{value:'4.3 / 5',label:'Retailer rating'},facts:[{label:'Review count',value:'128'},{label:'Entity rated',value:'Retailer A'},{label:'Latest review',value:'6 Oct (example)'}],evidence:'Retailer A has an aggregate customer rating of 4.3 out of 5, based on 128 reviews. These reviews concern the retailer and shopping experience.'},
    {...shared,id:'history',kind:'history',siteName:'Comparison site',url:capture('history'),title:'Aster H2 · Black · New',metric:{value:'€149',label:'Current recorded item price'},facts:[{label:'30-day range',value:'€149–€199'},{label:'Coverage',value:'4 retailers'},{label:'Includes shipping',value:'No'}],history:{points:[178,183,179,187,199,189,179,169,159,179,169,149],startLabel:'30 days ago',endLabel:'Example check',unit:'€'},evidence:'The lowest recorded item price across four tracked retailers was €149 over the last 30 days. Current lowest recorded item price: €149. Shipping is excluded.'},
    {...shared,id:'total',kind:'calculation',siteName:'Delivered total',title:'Aster H2 delivered to Zone A',metric:{value:'€168',label:'Calculated total'},inputs:[{sourceId:'offer',label:'Item',value:'€149'},{sourceId:'delivery',label:'Delivery',value:'+ €19'}],evidence:'€149 item price from source 1 + €19 delivery from source 2 = €168. Both inputs use one Aster H2, black and new, delivered to Zone A.'}
  ];
  const welcome=`## Shopping evidence preview

**Illustrative data** — this is a fictional product and shopping result.

The Aster H2 in **black, new** is **€149** at Retailer A [[offer]], plus **€19** home delivery to Zone A [[delivery]]. **Delivered total: €168** [[total]].

Estimated arrival: **2–3 business days** [[delivery]]. Retailer A is rated **4.3/5 from 128 reviews** [[review]]. The price matches the recorded 30-day low across **4 tracked retailers** [[history]].

Hover or click a numbered citation to inspect its evidence. Send a message to try a complete raven patrol and reply.`;
  const response=`## Aster H2 · delivered price

**Demo result · illustrative data.**

| Item | Price | Delivery | Total |
| --- | --- | --- | --- |
| Aster H2 · Black · New | €149 [[offer]] | €19 [[delivery]] | **€168** [[total]] |

Delivery to **Zone A** is estimated at **2–3 business days** [[delivery]]. Retailer A has a **4.3/5 customer rating from 128 reviews** [[review]].

The item price matches the recorded **30-day low across 4 tracked retailers**, excluding shipping [[history]].

Caw caw — hover the citations for the captured evidence.`;
  window.RavenShoppingDemo=Object.freeze({sources:Object.freeze(sources),welcome,response});
})();
