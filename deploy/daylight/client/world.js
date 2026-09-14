export class World {
  constructor(fixture) {this.fixture=fixture;this.state=structuredClone(fixture.state);this.events=[];}
  public() {
    const {products,rooms,days}=this.fixture,s=this.state;
    const subtotal=products.reduce((n,p)=>n+p.price*(s.cart[p.id]||0),0);
    return {...structuredClone(s),products,rooms:rooms.map(r=>({...r,free:undefined,
      availability:Object.fromEntries(days.map(day=>[day,Array.from({length:16},(_,i)=>540+i*30)
        .filter(t=>this.available(r,day,t,30)).map(time)]))})),total:subtotal+(subtotal&&s.shipping==='delivery'?39:0)};
  }
  available(room,day,start,duration) {
    const shift=this.fixture.days.indexOf(day)*30,end=start+duration;
    return room.free.some(([a,b])=>a*60+shift<=start&&end<=Math.min(1020,b*60+shift))&&
      !this.state.bookings.some(b=>b.room_id===room.id&&b.day===day&&start<mins(b.time)+b.duration&&mins(b.time)<end);
  }
  action(v) {
    const s=this.state,p=this.fixture.products;
    if(v.type==='cart') {
      if(!p.some(p=>p.id===v.product)||![-1,1].includes(v.delta))throw Error('Invalid product');
      const q=(s.cart[v.product]||0)+v.delta;if(q<0||q>10)throw Error('Choose 0–10 items');
      if(q)s.cart[v.product]=q;else delete s.cart[v.product];
    } else if(v.type==='shipping') {
      if(!['pickup','delivery'].includes(v.value))throw Error('Invalid shipping');s.shipping=v.value;
    } else if(v.type==='checkout') {
      if(!Object.keys(s.cart).length)throw Error('Add an item first');
      s.orders.push({items:p.filter(p=>s.cart[p.id]).map(p=>({id:p.id,name:p.name,quantity:s.cart[p.id]})),
        total:this.public().total,shipping:s.shipping});s.cart={};
    } else if(v.type==='preferences') {
      if(!['weekly','monthly','never'].includes(v.frequency)||typeof v.tips!=='boolean')throw Error('Invalid preferences');
      s.preferences={frequency:v.frequency,tips:v.tips};s.preferences_saved=true;
    } else if(v.type==='book') {
      const r=this.fixture.rooms.find(r=>r.id===v.room_id),duration=Number(v.duration),people=Number(v.people);
      if(!r||!this.fixture.days.includes(v.day)||!/^\d\d:(00|30)$/.test(v.time)||![30,60].includes(duration)||
        !Number.isInteger(people)||people<1||people>r.capacity||!this.available(r,v.day,mins(v.time),duration))throw Error('Room is unavailable for this booking');
      s.bookings.push({room_id:r.id,room:r.name,building:r.building,day:v.day,time:v.time,duration,people});
    } else throw Error('Unknown page action');
    this.events.push({at:new Date().toISOString(),action:structuredClone(v)});return this.public();
  }
}
function mins(t){const [h,m]=t.split(':').map(Number);return h*60+m;}
function time(t){return String(Math.floor(t/60)).padStart(2,'0')+':'+String(t%60).padStart(2,'0');}
