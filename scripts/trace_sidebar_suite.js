// Suite decoration for the shared keyed sidebar. Badge identity survives refresh.
const sidebarSuiteBadges=new WeakMap();
function renderSidebarSuiteBadges(){
  const enabled=document.querySelector('main').dataset.suiteMode==='true';
  for(const session of sessions){
    const button=sessionCards.get(session.id).button;
    if(enabled){
      if(button.classList.contains('selected'))button.classList.remove('selected');
      if(button.hasAttribute('aria-current'))button.removeAttribute('aria-current');
    }
    const member=session.suite;
    let badge=sidebarSuiteBadges.get(button);
    if(!member){if(badge){badge.remove();sidebarSuiteBadges.delete(button)}continue}
    if(!badge){
      badge=node('a','suite-badge');badge.onclick=event=>{event.stopPropagation()};
      sidebarSuiteBadges.set(button,badge);button.append(badge);
    }
    const text=member.title+' · '+member.case_id,href='#suite/'+encodeURIComponent(member.id),title=(member.tags||[]).join(' · ');
    if(badge.textContent!==text)badge.textContent=text;
    if(badge.getAttribute('href')!==href)badge.setAttribute('href',href);
    if(badge.title!==title)badge.title=title;
  }
}
