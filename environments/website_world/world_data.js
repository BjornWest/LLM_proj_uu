// Only the explicit public adapter payload is sent to this browser.
const response=await fetch('/api/catalog');
if(!response.ok)throw Error('The catalog could not be loaded');
export const data=await response.json();
