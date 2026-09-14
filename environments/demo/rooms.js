/* Fictional booking calendar inspired by public TimeEdit student guides. */
const roomFilters = {building:'all', day:'Tuesday', duration:'30', people:'1', from:'09:00'};
const slotMinutes = value => Number(value.slice(0,2))*60 + Number(value.slice(3));
const clockTime = value => String(Math.floor(value/60)).padStart(2,'0')+':'+String(value%60).padStart(2,'0');
function renderRooms(main,state,action){
 document.body.classList.add('room-site');
 document.title='Campus Rooms — study room reservations';
 document.querySelector('#logo').textContent='Campus Rooms';
 const f=roomFilters;
 const times=Array.from({length:16},(_,i)=>clockTime(540+i*30));
 const rooms=state.rooms.filter(r=>(f.building==='all'||r.building===f.building)&&r.capacity>=Number(f.people));
 const free=(r,t)=>r.availability[f.day].includes(t)&&slotMinutes(t)>=slotMinutes(f.from)&&(f.duration==='30'||r.availability[f.day].includes(clockTime(slotMinutes(t)+30)));
 const options=(values,selected)=>values.map(([value,text])=>`<option value="${esc(value)}" ${value===selected?'selected':''}>${esc(text)}</option>`).join('');
 main.innerHTML=`<div class="room-title"><div><p class="site-kicker">STUDENT SELF-SERVICE · DEMO</p><h1>Reserve a study room</h1><p class="site-lede">Find a space on campus. Select an available time to reserve it.</p></div><span class="room-user">AL <span>Alex Lind</span></span></div>
 <div class="room-filters"><label>Building<select id="room-building">${options([['all','All buildings'],...['Ångström','Ekonomikum','Blåsenhus'].map(x=>[x,x])],f.building)}</select></label><label>Day<select id="room-day">${options([['Tuesday','Tuesday · 15 Sep'],['Wednesday','Wednesday · 16 Sep'],['Thursday','Thursday · 17 Sep']],f.day)}</select></label><label>Duration<select id="room-duration">${options([['30','30 minutes'],['60','60 minutes']],f.duration)}</select></label><label>People<select id="room-people">${options(['1','2','3','4','5','6'].map(x=>[x,x]),f.people)}</select></label><label>Earliest start<select id="room-from">${options(times.map(x=>[x,x]),f.from)}</select></label></div>
 <div class="calendar-heading"><strong>${esc(f.day)}, ${f.day==='Tuesday'?'15':f.day==='Wednesday'?'16':'17'} September 2026</strong><span><i></i> Available <b></b> Unavailable</span></div>
 <p class="calendar-note">${rooms.length} rooms · ${f.duration} minute bookings · Times shown in local campus time. Choose the earliest green slot for the first available room.</p>
 <div class="calendar-scroll"><table class="room-calendar"><thead><tr><th>Room / building</th>${times.map(t=>`<th>${t}</th>`).join('')}</tr></thead><tbody>${rooms.map(r=>`<tr><th><strong>${esc(r.name)}</strong><span>${esc(r.building)} · ${r.capacity} seats</span><small>${esc(r.equipment)}</small></th>${times.map(t=>`<td>${free(r,t)?`<button data-room="${r.id}" data-time="${t}" aria-label="Book ${esc(r.name)} ${f.day} ${t}" title="${esc(r.name)} at ${t}"><span aria-hidden="true">+</span></button>`:'<span class="unavailable" aria-label="Unavailable"></span>'}</td>`).join('')}</tr>`).join('')}</tbody></table></div>
 <section class="room-reservations"><h2>My reservations <span>${state.bookings.length}</span></h2>${state.bookings.length?state.bookings.map(b=>`<div class="room-receipt" role="status"><span class="reservation-check">✓</span><div><strong>${esc(b.room)} · ${esc(b.building)}</strong><p>${esc(b.day)} ${esc(b.time)}–${clockTime(slotMinutes(b.time)+b.duration)} · ${b.people} people · ${b.duration} minutes</p></div><span>Confirmed</span></div>`).join(''):'<p>No reservations yet.</p>'}</section>
 <p class="room-demo-note">TimeEdit-inspired local prototype. Room names and availability are fictional. This is not UU’s booking service.</p>`;
 for(const key of ['building','day','duration','people','from']) main.querySelector('#room-'+key).onchange=e=>{f[key]=e.target.value;renderRooms(main,state,action)};
 main.querySelectorAll('[data-room]').forEach(button=>button.onclick=()=>{
  const room=rooms.find(r=>r.id===button.dataset.room),time=button.dataset.time;
  const dialog=document.createElement('dialog');dialog.className='room-dialog';
  dialog.innerHTML=`<p class="site-kicker">CONFIRM RESERVATION</p><h2>${esc(room.name)} · ${esc(room.building)}</h2><p>${f.day}, ${time}–${clockTime(slotMinutes(time)+Number(f.duration))}</p><p>${f.people} people · ${f.duration} minutes · Free for students</p><div><button type="button" class="cancel-reservation">Go back</button><button type="button" class="primary confirm-reservation">Confirm booking</button></div>`;
  main.append(dialog);dialog.showModal();
  dialog.querySelector('.cancel-reservation').onclick=()=>dialog.remove();
  dialog.querySelector('.confirm-reservation').onclick=()=>{dialog.close();action('book',{room_id:room.id,day:f.day,time,duration:f.duration,people:f.people})};
 });
}
