// Shared by human/client and BrowserGym: one public state implementation.
// The transport only records events; it supplies no goals, answers or grades.
import users from './components/health/data/users';
const clone=x=>JSON.parse(JSON.stringify(x));
const initial={privacy:{dataSharing:false,activityTracking:false,locationAccess:false},appointments:clone(users.find(u=>u.id==='1').appointments)};
if(localStorage.getItem('membershipSubscriptions')===null)localStorage.setItem('membershipSubscriptions','[]');
window.__privacyState=window.__privacyReady?await window.__privacyReady:JSON.parse(localStorage.getItem('fullHealthState')||JSON.stringify(initial));
const persistHealth=()=>localStorage.setItem('fullHealthState',JSON.stringify(window.__privacyState));
persistHealth();
let queue=Promise.resolve();
const notify=async(family,kind,payload)=>{
 const event=clone({family,kind,payload,url:location.href,at:Date.now()});
 if(window.__intentEmit)await window.__intentEmit(family+':'+kind,clone(payload));
 window.dispatchEvent(new CustomEvent('intent-site-event',{detail:event}));
};
window.__fullEmit=(family,kind,payload)=>{
 const copy=clone(payload);
 const next=queue.then(async()=>{
  if(family==='music'&&kind==='activation'){
   const subscriptions=JSON.parse(localStorage.getItem('membershipSubscriptions'));
   const receipt={plan_index:copy.planIndex,title:copy.plan.title,monthly_usd_cents:Math.round(Number(copy.plan.price.replace('US$',''))*100)};
   await notify(family,kind,copy);subscriptions.push(receipt);localStorage.setItem('membershipSubscriptions',JSON.stringify(subscriptions));return subscriptions;
  }
  await notify(family,kind,copy);return true;
 });queue=next;return next;
};
window.__fullDrain=()=>queue;
await window.__fullEmit('health','hydrate',{state:window.__privacyState});
async function health(kind,payload,after){
 const before=clone(window.__privacyState);
 await window.__fullEmit('health',kind,{before,after,...payload});window.__privacyState=after;persistHealth();
}
window.__privacySave=async draft=>health('privacy_commit',{draft:clone(draft)},{...clone(window.__privacyState),privacy:clone(draft)});
window.__privacyCancel=async appointmentId=>health('cancel',{appointmentId},{...clone(window.__privacyState),appointments:window.__privacyState.appointments.filter(a=>a.id!==appointmentId)});
window.__privacySchedule=async appointment=>health('schedule',{appointment:clone(appointment)},{...clone(window.__privacyState),appointments:[...clone(window.__privacyState.appointments),clone(appointment)]});
window.__fullSnapshot=()=>({site_revision:document.querySelector('meta[name="intent-site-revision"]')?.content||null,url:location.href,
 health:clone(window.__privacyState),subscriptions:JSON.parse(localStorage.getItem('membershipSubscriptions')),
 cart:JSON.parse(localStorage.getItem('cart')||'[]'),purchasedItems:JSON.parse(localStorage.getItem('purchasedItems')||'[]')});
