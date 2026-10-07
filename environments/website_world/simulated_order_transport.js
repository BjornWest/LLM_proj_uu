// No price/route calculation: keep the exact native displayed quote and receipt.
const sameSelection=(a,b)=>a&&b&&Object.keys(a).length===Object.keys(b).length&&Object.keys(a).every(k=>a[k]===b[k]);

async function fetchQuote(request){
  const response=await fetch('/api/basket-quote',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request)});
  const value=await response.json();
  if(!response.ok)throw Error(value.error||'Delivery quote unavailable');
  return value;
}

export async function explicitOrderQuote(value,draft,{data,payload,inquiryKey,expectedKey}){
  if(!data.simulatedOrders||!value.selected||(draft.basketSelection&&!value.selectionReset))return {value,selection:null};
  const request={...payload(draft),selections:{...value.selected.selection}};
  const next=await fetchQuote(request);
  if(inquiryKey(draft)!==expectedKey||next.revision!==draft.revision)return null;
  if(next.status!=='quoted'||next.selectionReset||!next.selected||
     !sameSelection(next.selected.selection,request.selections)||
     next.quoteId!==value.quoteId||next.selected.id!==value.selected.id||
     next.selected.totalMinor!==value.selected.totalMinor)
    throw Error('The delivery quote changed. Review your delivery choice again.');
  return {value:next,selection:request.selections};
}

export function orderMethods({data,payload,requests,inquiryKey}){
  function submission(draft,shown,key){
    if(!data.simulatedOrders)throw Error('Ordering is unavailable for this shop.');
    const cached=requests.get(inquiryKey(draft))?.value,selected=cached?.selected;
    const request=payload(draft);
    if(!selected||cached.status!=='quoted'||cached.selectionReset||
       !sameSelection(request.selections,selected.selection)||
       shown.errors.length||shown.quoteId!==cached.quoteId||shown.total!==selected.totalMinor/100)
      throw Error('Review the current basket and delivery quote before completing your order.');
    return {idempotency_key:key,quote_request:request,
      displayed_quote:{request_id:cached.requestId,quote_id:cached.quoteId,
        option_id:selected.id,total_minor:selected.totalMinor,currency:'SEK'},
      delivery_instructions:draft.instructions||'',terms_accepted:true};
  }
  return {
    simulatedOrders:!!data.simulatedOrders,
    orderIdentity(draft,shown){return JSON.stringify(submission(draft,shown,''));},
    async placeOrder(draft,shown,key){
      const body=submission(draft,shown,key);
      const response=await fetch('/api/order',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      const value=await response.json();
      if(!response.ok)throw Error(value.error||'The order could not be completed.');
      return value.confirmation;
    },
  };
}
