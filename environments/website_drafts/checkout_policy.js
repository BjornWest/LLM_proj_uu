// Finite reset policies shared by every checkout layout. Cart and remembered
// item-estimate destination are never reset by these policies.
export const resetPolicies = Object.freeze({
  preserve: [],
  services: ['deliveryChoices', 'split'],
  delivery: ['address', 'instructions', 'deliveryChoices', 'split'],
  checkout: ['address', 'instructions', 'deliveryChoices', 'split', 'coupon'],
});
export function resetPolicy(conf) {
  const key=conf.resetPolicy ?? (conf.reset?'checkout':'preserve');
  if(!Object.hasOwn(resetPolicies,key))throw Error('Invalid checkout reset policy');
  return key;
}
export function shouldReset({policy,from,to,historyBack=false,explicitBack=false}) {
  if(policy==='preserve'||from.role!=='checkout')return false;
  return historyBack||explicitBack||(to.role==='checkout'&&to.step<from.step);
}
export function applyReset(state, initialAddress, policy) {
  for(const field of resetPolicies[policy]) {
    state[field]=field==='address'?{...initialAddress}:field==='deliveryChoices'?{}:field==='split'?false:'';
  }
  if(resetPolicies[policy].includes('address'))state.addressStatus='unvalidated';
  state.revision++;
}
