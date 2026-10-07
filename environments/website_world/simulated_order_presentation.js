// Generated shops only. The server owns acceptance and the immutable receipt.
// Card numbers, expiry and security codes are never requested or submitted.
let submitting = false;

export function purchaseForm(result, {state, e, link}) {
  return `<form data-form="purchase"><h3>Confirm order</h3><p>This shop uses simulated payment. No payment details are needed.</p><label><input name="terms" type="checkbox" required> I accept the ${link('info/terms','shopping terms')}.</label><p><button ${submitting||result.errors.length||!state.cart.length?'disabled':''}>Complete purchase</button></p></form>`;
}

export function confirmation(order, {e, money, serviceTypes}) {
  const a=order.address;
  return `<section aria-label="Order confirmation"><h1>Order confirmed</h1><p>Order ${e(order.id)} · ${e(order.date)} · Simulated order received.</p><ul>${order.items.map(i=>`<li>${e(i.name)}${i.options?' · '+e(i.options):''} · Quantity ${e(i.quantity)}</li>`).join('')}</ul><h2>Submitted address</h2><p>${e(a.name)}, ${e(a.street)}${a.unit?`, Apartment ${e(a.unit)}`:''}, ${e(a.postcode)} ${e(a.city)}${a.country?`, ${e(a.country)}`:''}.</p>${order.instructions?`<p>Delivery instructions: ${e(order.instructions)}</p>`:''}<h2>Delivery</h2>${order.shipments.map(s=>`<section><p>${e(s.company)} — ${e(serviceTypes[s.type])} — ${e(s.name)}</p><p>${e(s.location.name)} · ${e(s.location.address)}</p><p>${s.arrival?e(s.arrival):'Arrival date not yet confirmed'} · Delivery charge ${money(s.shippingMinor/100)}</p></section>`).join('')}<dl><dt>Products</dt><dd>${money(order.subtotalMinor/100)}</dd><dt>Discount</dt><dd>${money(order.discountMinor/100)}</dd><dt>Delivery</dt><dd>${money(order.shippingMinor/100)}</dd><dt>Total</dt><dd><strong>${money(order.totalMinor/100)}</strong></dd></dl></section>`;
}

export async function complete({state, values, result, binding, save, goto, notify}) {
  if(submitting)return;
  if(!values.terms||result.errors.length||!state.cart.length){
    notify('Review your basket and delivery details, and accept the shopping terms.');return;
  }
  submitting=true;
  try{
    const identity=binding.orderIdentity(state,result);
    if(state.pendingOrder?.identity!==identity)
      state.pendingOrder={identity,key:crypto.randomUUID()};
    save();
    const submitted=structuredClone(state);
    // Only the quote binding constructs the allowlisted request. FormData,
    // browser prices and any payment fields do not cross this boundary.
    const order=await binding.placeOrder(submitted,result,submitted.pendingOrder.key);
    if(!order||typeof order.id!=='string'||!order.id||order.simulated!==true)
      throw Error('The shop did not return an order confirmation.');
    if(!state.orders.some(o=>o.id===order.id))state.orders.push(order);
    // An asynchronous confirmation must not erase later basket changes. Remove
    // only the exact submitted line identities/quantities still present.
    const sent=new Map(submitted.cart.map(l=>[l.id,l]));
    state.cart=state.cart.flatMap(l=>{
      const old=sent.get(l.id);
      if(!old||old.key!==l.key)return [l];
      const quantity=l.quantity-old.quantity;
      return quantity>0?[{...l,quantity}]:[];
    });
    if(state.revision===submitted.revision){state.coupon='';state.split=false;state.editing=null;}
    if(state.pendingOrder?.key===submitted.pendingOrder.key)state.pendingOrder=null;
    state.deliveryChoices={};state.basketSelection=null;state.revision++;save();
    goto(`info/order-${order.id}`);
  }catch(error){notify(error.message||'The order could not be completed.');}
  finally{submitting=false;}
}
