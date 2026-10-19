/* Live Blender geometry and motion. High refresh-rate runtime; the source bank stays at its native timeline. Three.js is vendored under vendor-v34. */
(() => {
  'use strict';
  const host=typeof globalThis!=='undefined'?globalThis:window;
  const scriptURL=typeof document!=='undefined'&&document.currentScript?.src;
  const baseURL=scriptURL?new URL('.',scriptURL).href:null;
  const clamp=(x,a=0,b=1)=>Math.max(a,Math.min(b,x));
  const now=()=>typeof performance!=='undefined'?performance.now():Date.now();
  const EPS=1e-10, TYPES={Float32:Float32Array,Uint16:Uint16Array,Uint32:Uint32Array};
  const fail=message=>{throw new Error('Live raven: '+message+' You can return to the v33 sprite demo.');};
  const finite=(value,label)=>{if(!Number.isFinite(value))fail(label+' must be finite.');return value;};
  let threePromise;

  function bracket(axis,value){
    finite(value,'Attention angle');
    if(value<=axis[0])return [[0,1]];
    const last=axis.length-1;if(value>=axis[last])return [[last,1]];
    for(let i=0;i<last;i++)if(value<=axis[i+1]){
      const t=(value-axis[i])/(axis[i+1]-axis[i]);
      return t<EPS?[[i,1]]:1-t<EPS?[[i+1,1]]:[[i,1-t],[i+1,t]];
    }
    fail('Invalid attention grid.');
  }
  function attentionWeights(pose,grid,blink=false){
    if(!Array.isArray(pose)||pose.length!==3)fail('Attention pose needs [tilt,pitch,yaw].');
    for(const key of ['tilt','pitch','yaw']){
      const a=grid[key];if(!Array.isArray(a)||!a.length||a.some((v,i)=>!Number.isFinite(v)||(i&&v<=a[i-1])))fail('Invalid '+key+' attention axis.');
    }
    const order=grid.order||['blink','tilt','pitch','yaw'];
    if(order.length!==4||new Set(order).size!==4||order.some(k=>!['blink','tilt','pitch','yaw'].includes(k)))fail('Invalid attention order.');
    const sizes={blink:grid.blinkLayers||1,tilt:grid.tilt.length,pitch:grid.pitch.length,yaw:grid.yaw.length};
    const results=[],closure=typeof blink==='boolean'?(blink?1:0):clamp(finite(blink,'Eye closure'));
    const blinkWeights=sizes.blink===1?[[0,1]]:bracket(Array.from({length:sizes.blink},(_,i)=>i/(sizes.blink-1)),closure);
    for(const [blinkIndex,d]of blinkWeights)for(const [tilt,a]of bracket(grid.tilt,pose[0]))for(const [pitch,b]of bracket(grid.pitch,pose[1]))for(const [yaw,c]of bracket(grid.yaw,pose[2])){
      const indices={blink:blinkIndex,tilt,pitch,yaw};let index=0;
      for(const key of order)index=index*sizes[key]+indices[key];
      results.push({index,weight:a*b*c*d,indices});
    }
    return results;
  }
  // A normalized shortest-arc quaternion average. No Euler interpolation at wraps.
  function blendQuaternion(out,entries,get){
    let x=0,y=0,z=0,w=0,rx=0,ry=0,rz=0,rw=1,first=true;
    for(const entry of entries){
      const q=get(entry),weight=entry.weight;if(weight<=0)continue;
      if(first){rx=q[0];ry=q[1];rz=q[2];rw=q[3];first=false;}
      const sign=rx*q[0]+ry*q[1]+rz*q[2]+rw*q[3]<0?-1:1;
      x+=q[0]*weight*sign;y+=q[1]*weight*sign;z+=q[2]*weight*sign;w+=q[3]*weight*sign;
    }
    const length=Math.hypot(x,y,z,w);if(length<EPS)fail('Invalid zero quaternion.');
    out[0]=x/length;out[1]=y/length;out[2]=z/length;out[3]=w/length;return out;
  }
  function slerpPair(out,a,b,t){
    let bx=b[0],by=b[1],bz=b[2],bw=b[3],dot=a[0]*bx+a[1]*by+a[2]*bz+a[3]*bw;
    if(dot<0){dot=-dot;bx=-bx;by=-by;bz=-bz;bw=-bw;}
    if(dot>.9995){const n=Math.hypot(out[0]=a[0]+(bx-a[0])*t,out[1]=a[1]+(by-a[1])*t,out[2]=a[2]+(bz-a[2])*t,out[3]=a[3]+(bw-a[3])*t);for(let i=0;i<4;i++)out[i]/=n;return out;}
    const angle=Math.acos(clamp(dot,-1,1)),sin=Math.sin(angle),u=Math.sin((1-t)*angle)/sin,v=Math.sin(t*angle)/sin;
    out[0]=a[0]*u+bx*v;out[1]=a[1]*u+by*v;out[2]=a[2]*u+bz*v;out[3]=a[3]*u+bw*v;return out;
  }
  function weightedValue(entries,read){
    const source=read(entries.reduce((a,b)=>a.weight>=b.weight?a:b));
    if(typeof source==='number')return entries.reduce((sum,e)=>sum+(typeof read(e)==='number'?read(e):source)*e.weight,0);
    if(Array.isArray(source))return source.map((_,i)=>weightedValue(entries,e=>read(e)?.[i]));
    if(source&&typeof source==='object'){
      const result={};for(const key of Object.keys(source))result[key]=weightedValue(entries,e=>read(e)?.[key]);return result;
    }
    return source;
  }


  function multiplyQ(a,b){
    const [x,y,z,w]=a,[X,Y,Z,W]=b;
    return [w*X+x*W+y*Z-z*Y,w*Y-x*Z+y*W+z*X,w*Z+x*Y-y*X+z*W,w*W-x*X-y*Y-z*Z];
  }
  function rotatePoint(point,pivot,q){
    const x=point[0]-pivot[0],y=point[1]-pivot[1],z=point[2]-pivot[2],tx=2*(q[1]*z-q[2]*y),ty=2*(q[2]*x-q[0]*z),tz=2*(q[0]*y-q[1]*x);
    return [pivot[0]+x+q[3]*tx+q[1]*tz-q[2]*ty,pivot[1]+y+q[3]*ty+q[2]*tx-q[0]*tz,pivot[2]+z+q[3]*tz+q[0]*ty-q[1]*tx];
  }
  function quaternionEulerBlenderXYZ(q){
    // Blender Euler XYZ is qZ(yaw)*qY(pitch)*qX(tilt), Three.js order ZYX.
    const [x,y,z,w]=q,m31=2*(x*z-y*w),pitch=Math.asin(clamp(-m31,-1,1));
    return Math.abs(m31)<.9999999?[Math.atan2(2*(y*z+x*w),1-2*(x*x+y*y)),pitch,Math.atan2(2*(x*y+z*w),1-2*(y*y+z*z))]:[0,pitch,Math.atan2(2*(z*w-x*y),1-2*(x*x+z*z))];
  }
  function localToWorld(point,transforms,chain){
    let p=point.slice();for(const node of chain){const k=node*10,v=[p[0]*transforms[k+7],p[1]*transforms[k+8],p[2]*transforms[k+9]];p=rotatePoint(v,[0,0,0],Array.from(transforms.subarray(k+3,k+7)));for(let i=0;i<3;i++)p[i]+=transforms[k+i];}return p;
  }
  function worldToLocal(point,transforms,chain){
    let p=point.slice();for(let j=chain.length-1;j>=0;j--){const k=chain[j]*10,q=Array.from(transforms.subarray(k+3,k+7));p=rotatePoint(p.map((v,i)=>v-transforms[k+i]),[0,0,0],[-q[0],-q[1],-q[2],q[3]]);for(let i=0;i<3;i++)p[i]/=transforms[k+7+i];}return p;
  }

  class MotionBank{
    constructor(meta,binary){
      if(meta?.version!==34||!String(meta.coordinateSystem||'').startsWith('Blender Z-up'))fail('Unsupported motion bank.');
      if(!(binary instanceof ArrayBuffer))fail('A binary geometry buffer is required.');
      if(meta.binary?.byteLength!==undefined&&binary.byteLength!==meta.binary.byteLength)fail('Geometry download is incomplete.');
      if(meta.binary?.endianness&&meta.binary.endianness!=='little')fail('Unsupported geometry byte order.');
      this.meta=meta;this.binary=binary;this.arrayCache=new Map();this.geometryCache=new Map();this.clipCache=new Map();this.compatibilityCache=new Map();this.petCache=new Map();this.raisedHeadCache=new Map();
      if(!meta.rigs||!meta.clips||!Array.isArray(meta.arrays)||!Array.isArray(meta.geometries))fail('Motion bank is missing meshes or clips.');
      for(const name of Object.keys(meta.clips)){
        const clip=this.clip(name);
        if(!meta.rigs[clip.rig]||!Array.isArray(clip.samples)||!clip.samples.length)fail('Missing rig or samples for '+name+'.');
        if(clip.samples.some((s,i)=>!Number.isFinite(s.frame)||(i&&s.frame<=clip.samples[i-1].frame)))fail('Samples are not ordered in '+name+'.');
      }
    }
    array(id,expected){
      const ref=this.meta.arrays[id];if(!ref)fail('Unknown binary array '+id+'.');
      const Constructor=TYPES[ref.type];if(!Constructor)fail('Unsupported binary array type '+ref.type+'.');
      let count=ref.count;
      // Both explicit scalarCount and item-count arrays are accepted when unambiguous.
      if(ref.scalarCount!==undefined)count=ref.scalarCount;
      else if(expected!==undefined&&count!==expected&&count*(ref.itemSize||1)===expected)count=expected;
      if(!Number.isInteger(count)||count<0||!Number.isInteger(ref.byteOffset)||ref.byteOffset<0||ref.byteOffset%Constructor.BYTES_PER_ELEMENT||ref.byteOffset+count*Constructor.BYTES_PER_ELEMENT>this.binary.byteLength)fail('Invalid binary array range '+id+'.');
      if(expected!==undefined&&count!==expected)fail('Wrong geometry array length '+id+'.');
      const key=id+':'+count;if(!this.arrayCache.has(key))this.arrayCache.set(key,new Constructor(this.binary,ref.byteOffset,count));
      return this.arrayCache.get(key);
    }
    geometry(id){
      if(!this.geometryCache.has(id)){
        const g=this.meta.geometries[id];if(!g)fail('Unknown local geometry '+id+'.');
        this.geometryCache.set(id,this.array(g.positions,g.vertexCount*3));
      }
      return this.geometryCache.get(id);
    }
    clip(name){
      if(this.clipCache.has(name))return this.clipCache.get(name);
      const seen=new Set();let cursor=name,overrides={};
      while(true){const c=this.meta.clips[cursor];if(!c)fail('Missing live animation '+cursor+'.');if(seen.has(cursor))fail('Cyclic animation alias.');seen.add(cursor);
        overrides={...c,...overrides};if(!c.aliasOf){const result={...c,...overrides,samples:c.samples};this.clipCache.set(name,result);return result;}cursor=c.aliasOf;
      }
    }
    temporal(name,frame){
      const clip=this.clip(name),samples=clip.samples,f=clamp(finite(frame,'Animation frame'),samples[0].frame,samples[samples.length-1].frame);
      if(f<=samples[0].frame)return [{sample:samples[0],weight:1,rig:clip.rig}];
      let lo=0,hi=samples.length-1;
      while(hi-lo>1){const mid=(lo+hi)>>1;if(samples[mid].frame<=f)lo=mid;else hi=mid;}
      const a=samples[lo],b=samples[hi],t=(f-a.frame)/(b.frame-a.frame);
      if(t<EPS)return [{sample:a,weight:1,rig:clip.rig}];if(1-t<EPS)return [{sample:b,weight:1,rig:clip.rig}];
      return [{sample:a,weight:1-t,rig:clip.rig},{sample:b,weight:t,rig:clip.rig}];
    }
    attention(pose,blink){
      const grid=this.meta.attention;if(!grid)fail('Attention geometry is unavailable.');
      const clip=this.clip(grid.clip||'attention');
      if(!this.attentionSamples){this.attentionSamples=new Map(clip.samples.map(s=>[s.frame,s]));}
      const excess=clamp(pose[1],-.42,grid.pitch[grid.pitch.length-1])-clamp(pose[1],grid.pitch[0],grid.pitch[grid.pitch.length-1]);
      return attentionWeights(pose,grid,blink).map(({index,weight,indices})=>{
        const frame=grid.frames?.[index]??index,sample=this.attentionSamples.get(frame);if(!sample)fail('Missing attention geometry '+index+'.');
        const entry={sample,weight,rig:clip.rig,index,indices};
        return excess<-EPS?{...this.raisedHeadEntry(entry,excess),weight}:entry;
      });
    }
    raisedHeadEntry(entry,excess){
      const key=entry.rig+':'+entry.sample.frame+':'+excess;if(this.raisedHeadCache.has(key))return this.raisedHeadCache.get(key);
      const rig=this.meta.rigs[entry.rig],head=rig.nodes.findIndex(n=>n.name==='Head'||n.name.startsWith('Head •')),body=rig.meshes.findIndex(m=>rig.nodes[m.node].name.startsWith('Continuous breast, neck'));
      if(head<0||body<0)fail('Raised attention requires the connected head and neck.');
      if(!this.attentionBasis){
        const neutral=this.resolve({clip:'idle',frame:0,attentionPose:[0,0,0],blink:false}),m=this.meta.rigs[neutral.rig].meshes.findIndex(mesh=>this.meta.rigs[neutral.rig].nodes[mesh.node].name.startsWith('Continuous breast, neck'));
        this.attentionBasis=this.positions(neutral,m,null,false);
      }
      const source=this.array(entry.sample.transforms,rig.nodes.length*10),transforms=source.slice(),h=head*10,oldQ=Array.from(source.subarray(h+3,h+7)),yaw=this.meta.attention.yaw[entry.indices.yaw];
      const qz=[0,0,Math.sin(yaw/2),Math.cos(yaw/2)],qy=[0,Math.sin(excess/2),0,Math.cos(excess/2)],delta=multiplyQ(multiplyQ(qz,qy),[0,0,-qz[2],qz[3]]),newQ=multiplyQ(delta,oldQ);
      for(let k=0;k<4;k++)transforms[h+3+k]=newQ[k];
      const geometries=entry.sample.geometry.map(id=>this.geometry(id)),positions=geometries[body].slice(),basis=this.attentionBasis;
      if(positions.length!==basis.length)fail('Raised head basis topology changed.');
      for(let i=0;i<positions.length;i+=3){
        const t=clamp((basis[i+2]-.53)/.29),weight=t*t*(3-2*t);if(!weight)continue;
        const v=[basis[i]-.45,basis[i+1],basis[i+2]-.79],old=rotatePoint(v,[0,0,0],oldQ),next=rotatePoint(v,[0,0,0],newQ);
        for(let k=0;k<3;k++)positions[i+k]+=weight*(next[k]-old[k]);
      }
      geometries[body]=positions;
      const chain=[];for(let node=head;node!==null&&node!==undefined;node=rig.nodes[node].parent)chain.push(node);
      const anchors={...entry.sample.worldAnchors};for(const marker of ['head','beak'])if(anchors[marker])anchors[marker]=localToWorld(worldToLocal(anchors[marker],source,chain),transforms,chain);
      const pose={...entry.sample.pose,headTilt:[this.meta.attention.tilt[entry.indices.tilt],this.meta.attention.pitch[entry.indices.pitch]+excess,yaw]};
      const result={...entry,sample:{...entry.sample,pose,worldAnchors:anchors},procedural:{transforms,geometries}};
      this.raisedHeadCache.set(key,result);if(this.raisedHeadCache.size>12)this.raisedHeadCache.delete(this.raisedHeadCache.keys().next().value);return result;
    }
    compatibility(from,to){
      const key=from+'→'+to;if(this.compatibilityCache.has(key))return this.compatibilityCache.get(key);
      const a=this.meta.rigs[from],b=this.meta.rigs[to];if(!a||!b)fail('Unknown rig.');
      const nodeNames=new Map(a.nodes.map((n,i)=>[n.name,i])),meshNames=new Map(a.meshes.map((m,i)=>[a.nodes[m.node].name,i]));
      const nodes=b.nodes.map(n=>nodeNames.get(n.name)),meshes=b.meshes.map(m=>meshNames.get(b.nodes[m.node].name));
      if(nodes.some(i=>i===undefined)||meshes.some(i=>i===undefined)||a.nodes.length!==b.nodes.length||a.meshes.length!==b.meshes.length)fail('The two live rigs cannot be blended.');
      for(let i=0;i<b.meshes.length;i++){
        const am=a.meshes[meshes[i]],bm=b.meshes[i],ai=this.array(am.triangles),bi=this.array(bm.triangles);
        if(am.vertexCount!==bm.vertexCount||ai.length!==bi.length||ai.some((v,j)=>v!==bi[j]))fail('The two live mesh topologies cannot be blended.');
      }
      for(let i=0;i<b.nodes.length;i++)if((a.nodes[nodes[i]].parent===null?null:a.nodes[a.nodes[nodes[i]].parent].name)!==(b.nodes[i].parent===null?null:b.nodes[b.nodes[i].parent].name))fail('The two live hierarchies cannot be blended.');
      const result={nodes,meshes};this.compatibilityCache.set(key,result);return result;
    }
    rotatedEntries(entries,rotation){
      const yaw=finite(rotation.yaw??0,'Flight yaw'),bank=finite(rotation.bank??0,'Flight bank');
      if(Math.abs(yaw)+Math.abs(bank)<EPS)return entries;
      const qz=[0,0,Math.sin(yaw/2),Math.cos(yaw/2)],qx=[Math.sin(bank/2),0,0,Math.cos(bank/2)];
      return entries.map(entry=>{
        const rig=this.meta.rigs[entry.rig],values=this.array(entry.sample.transforms,rig.nodes.length*10),alignedRoots=new Map();
        let rotationDelta=null,pivot=entry.sample.worldAnchors?.root;
        for(let node=0;node<rig.nodes.length;node++)if(rig.nodes[node].parent===null||rig.nodes[node].parent===undefined){
          const k=node*10,trs=Array.from(values.subarray(k,k+10)),q=trs.slice(3,7),n=Math.hypot(...q),native=q.map(v=>v/n);
          const next=multiplyQ(multiplyQ(qz,native),qx),delta=multiplyQ(next,[-native[0],-native[1],-native[2],native[3]]);
          pivot??=trs.slice(0,3);const point=rotatePoint(trs.slice(0,3),pivot,delta);
          alignedRoots.set(node,new Float32Array([...point,...next,...trs.slice(7)]));rotationDelta??=delta;
        }
        const anchors=entry.sample.worldAnchors&&rotationDelta?Object.fromEntries(Object.entries(entry.sample.worldAnchors).map(([key,point])=>[key,rotatePoint(point,pivot,rotationDelta)])):null;
        return {...entry,alignedRoots,worldAnchors:anchors};
      });
    }
    petEntry(options,frame){
      const headPose=options.petHeadPose,initialBlink=clamp(finite(Number(options.petStartBlink??0),'Petting initial blink')),idleFrame=finite(options.petIdleFrame??0,'Petting body frame');
      const key=[frame,idleFrame,initialBlink,...headPose].join('|');if(this.petCache.has(key))return this.petCache.get(key);
      const native=this.resolve({clip:'pet',frame}),neutral=this.resolve({clip:'pet',frame:0}),clip=this.clip('pet');
      // An eye already closed at the click stays closed through the initial native closure, then releases normally.
      const phase=clamp(frame/Math.max(1,clip.frames-1)),u=clamp((phase-.25)/.1),hold=1-u*u*(3-2*u);
      const closure=clamp(native.pose.eyeClosure??0)+(1-clamp(native.pose.eyeClosure??0))*initialBlink*hold;
      const base=this.resolve({clip:'idle',frame:idleFrame,attentionPose:headPose,blink:closure}),rig=this.meta.rigs[base.rig],transforms=this.transforms(base),nativeTransforms=this.transforms(native),neutralTransforms=this.transforms(neutral);
      const map=this.compatibility(native.rig,base.rig),head=rig.nodes.findIndex(n=>n.name==='Head'||n.name.startsWith('Head •'));
      if(head<0)fail('Petting requires a head node.');
      const h=head*10,nh=map.nodes[head]*10,baseQ=Array.from(transforms.subarray(h+3,h+7)),nq=Array.from(neutralTransforms.subarray(nh+3,nh+7)),pq=Array.from(nativeTransforms.subarray(nh+3,nh+7));
      const deltaQ=multiplyQ([-nq[0],-nq[1],-nq[2],nq[3]],pq),finalQ=multiplyQ(baseQ,deltaQ),headDelta=rotatePoint([nativeTransforms[nh]-neutralTransforms[nh],nativeTransforms[nh+1]-neutralTransforms[nh+1],nativeTransforms[nh+2]-neutralTransforms[nh+2]],[0,0,0],baseQ);
      const before=transforms.slice();for(let k=0;k<3;k++)transforms[h+k]+=headDelta[k];for(let k=0;k<4;k++)transforms[h+3+k]=finalQ[k];
      const geometries=rig.meshes.map((mesh,i)=>{
        const positions=this.positions(base,i,null,false);
        if(rig.nodes[mesh.node].name.startsWith('Continuous breast, neck')){
          const m=map.meshes[i],current=this.positions(native,m,null,false),start=this.positions(neutral,m,null,false);
          for(let j=0;j<positions.length;j+=3){const delta=rotatePoint([current[j]-start[j],current[j+1]-start[j+1],current[j+2]-start[j+2]],[0,0,0],baseQ);for(let k=0;k<3;k++)positions[j+k]+=delta[k];}
        }
        return positions;
      });
      const chain=[];for(let node=head;node!==null&&node!==undefined;node=rig.nodes[node].parent)chain.push(node);
      const anchors={...base.worldAnchors};for(const marker of ['head','beak'])if(anchors[marker])anchors[marker]=localToWorld(worldToLocal(anchors[marker],before,chain),transforms,chain);
      const petPose={...base.pose,...native.pose,headTilt:quaternionEulerBlenderXYZ(finalQ),eyeClosure:closure};
      const sample={frame,geometry:[],transforms:null,visible:base.entries[0].sample.visible,pose:petPose,camera:base.camera,worldAnchors:anchors};
      const entry={sample,weight:1,rig:base.rig,procedural:{transforms,geometries}};
      this.petCache.set(key,entry);if(this.petCache.size>6)this.petCache.delete(this.petCache.keys().next().value);return entry;
    }
    resolve(options){
      const clip=this.clip(options.clip),frame=options.nativeSeconds!==undefined?finite(options.nativeSeconds,'Animation seconds')*(clip.fps||60):finite(options.frame??0,'Animation frame');
      let entries=options.clip==='pet'&&options.petHeadPose?[this.petEntry(options,frame)]:options.attentionPose?this.attention(options.attentionPose,options.blink):this.temporal(options.clip,frame),rig=entries[0].rig;
      if(options.flightRotation)entries=this.rotatedEntries(entries,options.flightRotation);
      let blendSources=null;
      if(options.blendFrom&&options.blendWeight<1){
        const t=clamp(options.blendWeight??1),old=this.resolve({...options.blendFrom,attentionPose:null,blendFrom:null});
        const current=this.resolve({...options,blendFrom:null});blendSources={old,current,weight:t,from:options.blendFrom};
        if(old.rig!==rig)this.compatibility(old.rig,rig);
        entries=old.entries.map(e=>({...e,weight:e.weight*(1-t),fromPrevious:true})).concat(entries.map(e=>({...e,weight:e.weight*t}))).filter(e=>e.weight>EPS);
      }
      const pose=weightedValue(entries,e=>e.sample.pose||{}),camera=weightedValue(entries,e=>e.sample.camera);
      if(!camera?.position||!camera.quaternion||!camera.orthoScale)fail('Missing native camera for '+options.clip+'.');
      camera.quaternion=Array.from(entries.length===2?slerpPair(new Float64Array(4),entries[0].sample.camera.quaternion,entries[1].sample.camera.quaternion,entries[1].weight):blendQuaternion(new Float64Array(4),entries,e=>e.sample.camera.quaternion));
      const worldAnchors=entries.every(e=>e.sample.worldAnchors)?weightedValue(entries,e=>e.worldAnchors||e.sample.worldAnchors):null;
      const result={clip:options.clip,frame,time:frame/(clip.fps||60),rig,entries,pose,camera,worldAnchors,blendSources};
      if(options.attentionPose){
        pose.headTilt=options.attentionPose.slice();pose.eyeClosure=Number(options.blink||0);
        if(options.clip==='idle')result.idleBase={rig:clip.rig,entries:this.temporal(options.clip,frame)};
      }
      if(options.flightRotation)result.alignmentKey='rotation:'+options.flightRotation.yaw+','+options.flightRotation.bank;
      return result;
    }
    pose(clip,frame=0,options={}){return this.resolve({clip,frame,...options}).pose;}
    transforms(state,out){
      const rig=this.meta.rigs[state.rig],count=rig.nodes.length;
      out??=new Float32Array(count*10);if(out.length!==count*10)fail('Transform output has wrong size.');
      const arrays=state.entries.map(e=>e.procedural?.transforms||this.array(e.sample.transforms,this.meta.rigs[e.rig].nodes.length*10));
      const maps=state.entries.map(e=>e.rig===state.rig?null:this.compatibility(e.rig,state.rig).nodes);
      const q=new Float64Array(4),qa=new Float64Array(4),qb=new Float64Array(4);
      for(let n=0;n<count;n++){
        const offset=n*10;
        for(let k=0;k<10;k++)if(k<3||k>6){let sum=0;for(let j=0;j<arrays.length;j++){
          const aligned=state.entries[j].alignedRoots?.get(n),source=aligned||arrays[j],start=aligned?0:(maps[j]?.[n]??n)*10;
          sum+=source[start+k]*state.entries[j].weight;
        }out[offset+k]=sum;}
        if(arrays.length===2){
          for(let j=0;j<2;j++){const aligned=state.entries[j].alignedRoots?.get(n),source=aligned||arrays[j],start=(aligned?0:(maps[j]?.[n]??n)*10)+3,target=j===0?qa:qb;for(let k=0;k<4;k++)target[k]=source[start+k];}
          slerpPair(q,qa,qb,state.entries[1].weight);
        }else{
          let x=0,y=0,z=0,w=0,rx=0,ry=0,rz=0,rw=1,first=true;
          for(let j=0;j<arrays.length;j++){
            const weight=state.entries[j].weight;if(weight<=0)continue;
            const aligned=state.entries[j].alignedRoots?.get(n),source=aligned||arrays[j],start=(aligned?0:(maps[j]?.[n]??n)*10)+3;
            const qx=source[start],qy=source[start+1],qz=source[start+2],qw=source[start+3];
            if(first){rx=qx;ry=qy;rz=qz;rw=qw;first=false;}
            const sign=rx*qx+ry*qy+rz*qz+rw*qw<0?-1:1;x+=qx*weight*sign;y+=qy*weight*sign;z+=qz*weight*sign;w+=qw*weight*sign;
          }
          const length=Math.hypot(x,y,z,w);if(length<EPS)fail('Invalid zero quaternion.');q[0]=x/length;q[1]=y/length;q[2]=z/length;q[3]=w/length;
        }
        for(let k=0;k<4;k++)out[offset+3+k]=q[k];
      }
      if(state.idleBase){
        const native=this.transforms(state.idleBase),mapping=this.compatibility(state.idleBase.rig,state.rig).nodes;
        const head=rig.nodes.findIndex(n=>n.name==='Head'||n.name.startsWith('Head •'));
        for(let node=0;node<count;node++){
          let cursor=node,isHead=false;while(cursor!==null&&cursor!==undefined){if(cursor===head){isHead=true;break;}cursor=rig.nodes[cursor].parent;}
          if(!isHead)for(let k=0;k<10;k++)out[node*10+k]=native[mapping[node]*10+k];
        }
      }
      return out;
    }
    positions(state,meshIndex,out,expanded=true){
      const rig=this.meta.rigs[state.rig],mesh=rig.meshes[meshIndex],triangles=this.array(mesh.triangles),count=expanded?triangles.length*3:mesh.vertexCount*3;
      out??=new Float32Array(count);if(out.length!==count)fail('Vertex output has wrong size.');
      const arrays=state.entries.map(e=>{const index=e.rig===state.rig?meshIndex:this.compatibility(e.rig,state.rig).meshes[meshIndex];return e.procedural?.geometries[index]||this.geometry(e.sample.geometry[index]);});
      if(arrays.some(a=>a.length!==mesh.vertexCount*3))fail('Animated local mesh topology changed.');
      if(expanded)for(let i=0;i<triangles.length;i++){
        const source=triangles[i]*3,target=i*3;let x=0,y=0,z=0;
        for(let j=0;j<arrays.length;j++){const weight=state.entries[j].weight,a=arrays[j];x+=a[source]*weight;y+=a[source+1]*weight;z+=a[source+2]*weight;}
        out[target]=x;out[target+1]=y;out[target+2]=z;
      }else for(let i=0;i<count;i++){
        let value=0;for(let j=0;j<arrays.length;j++)value+=arrays[j][i]*state.entries[j].weight;out[i]=value;
      }
      return out;
    }
  }

  class LiveRenderer{
    constructor({meta,binary,THREE,canvas,rendererFactory,maxPixelRatio=2}){
      if(!THREE)fail('Three.js has not loaded.');if(!canvas)fail('A canvas is required.');
      this.THREE=THREE;this.meta=meta;this.bank=new MotionBank(meta,binary);this.canvas=canvas;this.rigs=new Map();this.maxPixelRatio=clamp(maxPixelRatio,1,2);this.dirty=null;this.disposed=false;this.contextLost=false;
      this.stats={frames:0,drawMs:0,maxDrawMs:0,geometryMs:0,maxGeometryMs:0,renderSubmitMs:0,maxRenderSubmitMs:0,clearPixels:0,bufferBytes:binary.byteLength,positionBufferBytes:0,colorBufferBytes:0,triangles:0,drawCalls:0,contextLosses:0};
      try{this.renderer=rendererFactory?rendererFactory(canvas,THREE):new THREE.WebGLRenderer({canvas,alpha:true,antialias:true,premultipliedAlpha:true,preserveDrawingBuffer:false,powerPreference:'low-power'});}
      catch(e){fail('WebGL2 is unavailable ('+(e.message||e)+').');}
      this.renderer.outputColorSpace=THREE.SRGBColorSpace;this.renderer.toneMapping=THREE.NoToneMapping;this.renderer.setClearColor(0,0);this.renderer.autoClear=false;
      this.scene=new THREE.Scene();this.scene.up.set(0,0,1);this.camera=new THREE.OrthographicCamera(-1,1,1,-1,.001,10000);this.camera.up.set(0,0,1);
      this.material=new THREE.MeshBasicMaterial({color:0xffffff,vertexColors:true,side:THREE.DoubleSide,toneMapped:false});
      this.displayBrightness={value:1};
      this.material.onBeforeCompile=shader=>{shader.uniforms.ravenDisplayBrightness=this.displayBrightness;shader.fragmentShader='uniform float ravenDisplayBrightness;\n'+shader.fragmentShader;shader.fragmentShader=shader.fragmentShader.replace('#include <colorspace_fragment>','#include <colorspace_fragment>\n gl_FragColor.rgb *= ravenDisplayBrightness;');};
      this.material.customProgramCacheKey=()=> 'raven-display-brightness-v34';
      this.raycaster=new THREE.Raycaster();this.pointer=new THREE.Vector2();this.tmp=new THREE.Vector3();this.tmp2=new THREE.Vector3();this.matrix=new THREE.Matrix4();
      this.onContextLost=e=>{e.preventDefault?.();this.contextLost=true;this.stats.contextLosses++;canvas.dispatchEvent?.(typeof CustomEvent!=='undefined'?new CustomEvent('raven-live-error',{detail:{message:'WebGL context lost. Return to the v33 demo or reload.'}}):{type:'raven-live-error'});};
      this.onContextRestored=()=>{this.contextLost=false;this.dirty=null;this.renderer.setScissorTest(false);this.renderer.clear();};
      canvas.addEventListener?.('webglcontextlost',this.onContextLost);canvas.addEventListener?.('webglcontextrestored',this.onContextRestored);
      this.resize(canvas.clientWidth||canvas.width||1,canvas.clientHeight||canvas.height||1,typeof devicePixelRatio!=='undefined'?devicePixelRatio:1);
    }
    rig(id){
      if(this.rigs.has(id))return this.rigs.get(id);
      const THREE=this.THREE,source=this.meta.rigs[id],group=new THREE.Group(),nodes=source.nodes.map(n=>{const o=new THREE.Object3D();o.name=n.name;o.up.set(0,0,1);return o;});
      const seen=new Set(),active=new Set();function attach(i){if(seen.has(i))return;if(active.has(i))fail('Cyclic local node hierarchy.');active.add(i);const p=source.nodes[i].parent;if(p===null||p===undefined)group.add(nodes[i]);else{if(!Number.isInteger(p)||p<0||p>=nodes.length||p===i)fail('Invalid local node hierarchy.');attach(p);nodes[p].add(nodes[i]);}active.delete(i);seen.add(i);}
      for(let i=0;i<nodes.length;i++)attach(i);
      const meshes=source.meshes.map(m=>{
        const triangles=this.bank.array(m.triangles),colors=this.bank.array(m.colors,triangles.length*3);if(triangles.some(v=>v>=m.vertexCount))fail('Triangle index is outside its local mesh.');
        const geometry=new THREE.BufferGeometry(),positions=new Float32Array(triangles.length*3);
        geometry.setAttribute('position',new THREE.BufferAttribute(positions,3).setUsage(THREE.DynamicDrawUsage));
        geometry.setAttribute('color',new THREE.BufferAttribute(colors,3));
        const mesh=new THREE.Mesh(geometry,this.material);mesh.name=source.nodes[m.node].name+':mesh';mesh.frustumCulled=false;nodes[m.node].add(mesh);
        // Shared faceted vertices repeat in the color-expanded triangle buffer. Bounds only need each original vertex once.
        const seenVertices=new Set(),boundsOffsets=[];for(let i=0;i<triangles.length;i++)if(!seenVertices.has(triangles[i])){seenVertices.add(triangles[i]);boundsOffsets.push(i*3);}
        mesh.userData.boundsOffsets=new Uint32Array(boundsOffsets);
        this.stats.positionBufferBytes+=positions.byteLength;this.stats.colorBufferBytes+=colors.byteLength;
        return mesh;
      });
      const runtime={id,group,nodes,meshes,transforms:new Float32Array(nodes.length*10),stateEntries:null,alignmentKey:null};group.visible=false;this.scene.add(group);this.rigs.set(id,runtime);return runtime;
    }
    resize(width,height,ratio=1){
      if(this.disposed)fail('Renderer was disposed.');
      this.width=Math.max(1,finite(width,'Canvas width'));this.height=Math.max(1,finite(height,'Canvas height'));this.ratio=clamp(finite(ratio,'Pixel ratio'),1,this.maxPixelRatio);
      this.renderer.setPixelRatio(this.ratio);this.renderer.setSize(this.width,this.height,false);this.renderer.setScissorTest(false);this.renderer.clear();this.dirty=null;return this;
    }
    pose(clip,frame=0,options={}){return this.bank.pose(clip,frame,options);}
    prepare(state){
      const began=now(),runtime=this.rig(state.rig);
      for(const r of this.rigs.values())r.group.visible=r===runtime;
      const prior=runtime.stateEntries,entries=state.entries,alignmentKey=(state.alignmentKey||'')+(state.idleBase?':idle:'+state.frame:'');
      const unchanged=prior&&runtime.alignmentKey===alignmentKey&&prior.length===entries.length&&entries.every((e,i)=>e.sample===prior[i].sample&&e.rig===prior[i].rig&&e.weight===prior[i].weight);
      if(!unchanged){
        this.bank.transforms(state,runtime.transforms);
        for(let i=0;i<runtime.nodes.length;i++){
          const o=runtime.nodes[i],a=runtime.transforms,k=i*10;o.position.set(a[k],a[k+1],a[k+2]);o.quaternion.set(a[k+3],a[k+4],a[k+5],a[k+6]);o.scale.set(a[k+7],a[k+8],a[k+9]);
          o.visible=state.entries.some(e=>e.weight>EPS&&(e.sample.visible?.[e.rig===state.rig?i:this.bank.compatibility(e.rig,state.rig).nodes[i]]??true));
        }
        for(let i=0;i<runtime.meshes.length;i++){
          const mesh=runtime.meshes[i],attr=mesh.geometry.getAttribute('position');this.bank.positions(state,i,attr.array,true);attr.needsUpdate=true;mesh.geometry.boundingSphere=null;mesh.geometry.boundingBox=null;
        }
        runtime.stateEntries=entries.map(e=>({sample:e.sample,rig:e.rig,weight:e.weight}));runtime.alignmentKey=alignmentKey;
      }
      this.scene.updateMatrixWorld(true);const elapsed=now()-began;this.stats.geometryMs+=elapsed;this.stats.maxGeometryMs=Math.max(this.stats.maxGeometryMs,elapsed);this.activeRig=runtime;return runtime;
    }
    alignBlend(state,options){
      const blend=state.blendSources;if(!blend)return;
      const THREE=this.THREE,{old,current,weight:t,from}=blend,a=current.pose[options.anchor||'root']||current.pose.contact||current.pose.root,oa=old.pose[from.anchor||'root']||old.pose.contact||old.pose.root;
      const oldSize=from.size??options.size,oldPoint=from.point||options.point,ratio=oldSize/options.size,unit=options.size/current.camera.orthoScale;
      finite(oldSize,'Previous rendered size');if(oldSize<=0||!a||!oa)fail('Missing previous live placement.');
      const x=options.point.x-a.x*options.size,y=options.point.y-a.y*options.size,ox=oldPoint.x-oa.x*oldSize,oy=oldPoint.y-oa.y*oldSize;
      const scale=ratio*current.camera.orthoScale/old.camera.orthoScale;
      const tx=(current.camera.shiftX||0)*current.camera.orthoScale+(ox+oldSize*.5-x-options.size*.5)/unit-scale*(old.camera.shiftX||0)*old.camera.orthoScale;
      const ty=(current.camera.shiftY||0)*current.camera.orthoScale-(oy+oldSize*.5-y-options.size*.5)/unit-scale*(old.camera.shiftY||0)*old.camera.orthoScale;
      const position=new THREE.Vector3(),q=new THREE.Quaternion(),s=new THREE.Vector3(),matrix=new THREE.Matrix4();
      const worldCamera=c=>new THREE.Matrix4().compose(new THREE.Vector3().fromArray(c.position),new THREE.Quaternion().fromArray(c.quaternion),new THREE.Vector3(1,1,1));
      const alignment=worldCamera(current.camera).multiply(new THREE.Matrix4().makeTranslation(tx,ty,0)).multiply(new THREE.Matrix4().makeScale(scale,scale,scale)).multiply(worldCamera(old.camera).invert());
      const targetRig=this.meta.rigs[state.rig];
      for(const entry of state.entries)if(entry.fromPrevious){
        const previousRoots=entry.alignedRoots;entry.alignedRoots=new Map();const source=this.meta.rigs[entry.rig],values=entry.procedural?.transforms||this.bank.array(entry.sample.transforms,source.nodes.length*10),map=entry.rig===state.rig?null:this.bank.compatibility(entry.rig,state.rig).nodes;
        for(let n=0;n<targetRig.nodes.length;n++)if(targetRig.nodes[n].parent===null||targetRig.nodes[n].parent===undefined){
          const k=(map?.[n]??n)*10,rotated=previousRoots?.get(map?.[n]??n),sourceValues=rotated||values,offset=rotated?0:k;position.fromArray(sourceValues,offset);q.fromArray(sourceValues,offset+3);s.fromArray(sourceValues,offset+7);matrix.compose(position,q,s).premultiply(alignment);matrix.decompose(position,q,s);
          entry.alignedRoots.set(n,new Float32Array([...position.toArray(),...q.toArray(),...s.toArray()]));
        }
      }
      const pose={...state.pose};for(const key of ['root','contact','foot','head','beak'])if(current.pose[key]&&old.pose[key]){
        const p=current.pose[key],op=old.pose[key];pose[key]={x:(a.x+((op.x-oa.x)*oldSize+oldPoint.x-options.point.x)/options.size)*(1-t)+p.x*t,y:(a.y+((op.y-oa.y)*oldSize+oldPoint.y-options.point.y)/options.size)*(1-t)+p.y*t};
      }
      state.pose=pose;state.camera=current.camera;state.worldAnchors=null;state.placementAnchor=a;state.alignmentKey=(state.alignmentKey||'')+':blend:'+ [oldSize,oldPoint.x,oldPoint.y,options.size,options.point.x,options.point.y,from.flightRotation?.yaw??0,from.flightRotation?.bank??0].join(',');
    }
    nativeCamera(state,override){
      const c={...state.camera,...override},aspect=this.meta.rigs[state.rig].camera?.aspect||1;
      this.camera.position.fromArray(c.position);this.camera.quaternion.fromArray(c.quaternion);this.camera.scale.set(1,1,1);
      const ortho=c.orthoScale;finite(ortho,'Native camera scale');if(ortho<=0)fail('Native camera scale must be positive.');
      this.camera.left=((c.shiftX||0)-.5)*ortho;this.camera.right=((c.shiftX||0)+.5)*ortho;this.camera.top=((c.shiftY||0)+.5/aspect)*ortho;this.camera.bottom=((c.shiftY||0)-.5/aspect)*ortho;
      this.camera.near=c.near||.001;this.camera.far=c.far||10000;this.camera.updateProjectionMatrix();this.camera.updateMatrixWorld(true);return {c,aspect,ortho};
    }
    projectedPose(state){
      const pose={...state.pose};if(state.worldAnchors)for(const [key,point]of Object.entries(state.worldAnchors)){
        this.tmp.fromArray(point).project(this.camera);pose[key]={x:(this.tmp.x+1)*.5,y:(1-this.tmp.y)*.5};
      }
      return pose;
    }
    geometryBounds(){
      let left=Infinity,top=Infinity,right=-Infinity,bottom=-Infinity;
      for(const mesh of this.activeRig.meshes){
        let visible=true;for(let o=mesh;o&&o!==this.scene;o=o.parent)if(!o.visible){visible=false;break;}if(!visible)continue;
        const a=mesh.geometry.getAttribute('position').array;this.matrix.multiplyMatrices(this.camera.matrixWorldInverse,mesh.matrixWorld);
        const e=this.matrix.elements;
        for(const i of mesh.userData.boundsOffsets){const x=a[i],y=a[i+1],z=a[i+2],cx=e[0]*x+e[4]*y+e[8]*z+e[12],cy=e[1]*x+e[5]*y+e[9]*z+e[13];
          const px=(cx-this.camera.left)/(this.camera.right-this.camera.left)*this.width,py=(this.camera.top-cy)/(this.camera.top-this.camera.bottom)*this.height;
          left=Math.min(left,px);right=Math.max(right,px);top=Math.min(top,py);bottom=Math.max(bottom,py);
        }
      }
      if(!Number.isFinite(left))fail('The live rig has no visible mesh.');
      return {left,top,right,bottom};
    }
    clearRect(bounds){
      const left=Math.max(0,Math.floor(bounds.left)-3),top=Math.max(0,Math.floor(bounds.top)-3),right=Math.min(this.width,Math.ceil(bounds.right)+3),bottom=Math.min(this.height,Math.ceil(bounds.bottom)+3);
      if(right<=left||bottom<=top)return null;
      this.renderer.setScissor(left,this.height-bottom,right-left,bottom-top);this.renderer.setScissorTest(true);
      return {left,top,right,bottom};
    }
    render(options){
      if(this.disposed)fail('Renderer was disposed.');if(this.contextLost)fail('The WebGL context was lost.');
      const began=now(),state=this.bank.resolve(options),size=finite(options.size,'Rendered size'),point=options.point;
      if(size<=0||!point)fail('Render needs a positive size and a screen point.');finite(point.x,'Screen x');finite(point.y,'Screen y');
      this.alignBlend(state,options);this.prepare(state);const {c,aspect,ortho}=this.nativeCamera(state,options.camera),pose=this.projectedPose(state),a=state.placementAnchor||(typeof options.anchor==='object'?options.anchor:pose[options.anchor||'root']||pose.contact||pose.root);
      if(!a||!Number.isFinite(a.x)||!Number.isFinite(a.y))fail('Missing screen anchor.');
      const pixelsPerUnit=size/ortho,sourceHeight=size/aspect,x=point.x-a.x*size,y=point.y-a.y*sourceHeight;
      const cx=(c.shiftX||0)*ortho,cy=(c.shiftY||0)*ortho;
      this.camera.left=cx-(x+size*.5)/pixelsPerUnit;this.camera.right=this.camera.left+this.width/pixelsPerUnit;
      this.camera.top=cy+(y+sourceHeight*.5)/pixelsPerUnit;this.camera.bottom=this.camera.top-this.height/pixelsPerUnit;this.camera.updateProjectionMatrix();
      const bounds=this.geometryBounds(),prior=this.dirty||bounds,union={left:Math.min(prior.left,bounds.left),top:Math.min(prior.top,bounds.top),right:Math.max(prior.right,bounds.right),bottom:Math.max(prior.bottom,bounds.bottom)};
      const clear=this.clearRect(union);if(clear){this.renderer.clear();this.stats.clearPixels+=(clear.right-clear.left)*(clear.bottom-clear.top)*this.ratio*this.ratio;}
      const draw=this.clearRect(bounds),submit=now();
      // Keep the accepted .82 darker switch in display sRGB, after color conversion.
      this.displayBrightness.value=typeof options.darker==='object'&&options.darker?(options.darker.enabled===false?1:options.darker.factor??.82):(options.darker ? .82 : 1);
      if(draw)this.renderer.render(this.scene,this.camera);
      const submitMs=now()-submit;this.stats.renderSubmitMs+=submitMs;this.stats.maxRenderSubmitMs=Math.max(this.stats.maxRenderSubmitMs,submitMs);
      this.dirty=bounds;this.lastState=state;this.lastOptions={...options};this.lastPose=pose;
      const markers={};for(const key of ['root','contact','foot','head','beak'])if(pose[key])markers[key]={x:x+pose[key].x*size,y:y+pose[key].y*sourceHeight};
      const elapsed=now()-began;this.stats.frames++;this.stats.drawMs+=elapsed;this.stats.maxDrawMs=Math.max(this.stats.maxDrawMs,elapsed);this.stats.triangles=draw?(this.renderer.info?.render?.triangles||0):0;this.stats.drawCalls=draw?(this.renderer.info?.render?.calls||0):0;
      const result={ready:true,pose,markers,bounds,size,sourceRect:{x,y,width:size,height:sourceHeight},frame:state.frame,clip:state.clip,attentionNeighbors:options.attentionPose?state.entries.length:0,geometrySamples:state.entries.length,drawMs:elapsed};
      this.lastResult=result;return result;
    }
    hitTest(x,y){
      if(!this.activeRig||!this.lastResult||this.contextLost)return false;
      const b=this.lastResult.bounds;if(x<b.left||x>b.right||y<b.top||y>b.bottom)return false;
      this.pointer.set(x/this.width*2-1,1-y/this.height*2);this.raycaster.setFromCamera(this.pointer,this.camera);
      return this.raycaster.intersectObjects(this.activeRig.meshes,false).length>0;
    }
    getStats(){const s=this.stats;return Object.freeze({...s,averageDrawMs:s.drawMs/Math.max(1,s.frames),averageGeometryMs:s.geometryMs/Math.max(1,s.frames),averageRenderSubmitMs:s.renderSubmitMs/Math.max(1,s.frames),pixelRatio:this.ratio,loadedRigs:this.rigs.size,geometries:this.renderer.info?.memory?.geometries||0,programs:this.renderer.info?.programs?.length||0,renderer:'Three.js '+this.THREE.REVISION,live3D:true});}
    async warm(clip='idle'){
      const state=this.bank.resolve({clip,frame:0});this.prepare(state);this.nativeCamera(state);if(this.renderer.compileAsync)await this.renderer.compileAsync(this.scene,this.camera);else this.renderer.compile(this.scene,this.camera);return this;
    }
    dispose(){
      if(this.disposed)return;this.disposed=true;this.canvas.removeEventListener?.('webglcontextlost',this.onContextLost);this.canvas.removeEventListener?.('webglcontextrestored',this.onContextRestored);
      for(const rig of this.rigs.values())for(const mesh of rig.meshes)mesh.geometry.dispose();this.material.dispose();this.renderer.dispose();this.scene.clear();this.rigs.clear();this.activeRig=null;this.lastState=null;this.lastResult=null;this.bank.arrayCache.clear();this.bank.geometryCache.clear();this.bank.petCache.clear();this.bank.raisedHeadCache.clear();this.bank.attentionBasis=null;this.bank.binary=null;
    }
  }
  async function load(options={}){
    const url=options.url||new URL('live-raven-v34.json',baseURL||location.href).href,fetcher=options.fetch||host.fetch?.bind(host);
    if(!fetcher)fail('Fetch is unavailable.');const response=await fetcher(url,{signal:options.signal});if(!response.ok)fail('Could not load motion metadata ('+response.status+').');
    const meta=await response.json(),absolute=new URL(url,baseURL||(typeof location!=='undefined'?location.href:'http://localhost/'));
    const binaryURL=new URL(options.binaryUrl||meta.binary?.uri||'live-raven-v34.bin',absolute);if(!binaryURL.search&&absolute.search)binaryURL.search=absolute.search;
    options.onProgress?.({stage:'geometry',bytes:meta.binary?.byteLength||0});
    const vendorURL=options.threeURL||new URL('vendor-v34/three.module.js',baseURL||absolute).href;
    if(!options.THREE)threePromise??=import(vendorURL);
    const [binaryResponse,THREE]=await Promise.all([fetcher(binaryURL.href,{signal:options.signal}),options.THREE?Promise.resolve(options.THREE):threePromise]);
    if(!binaryResponse.ok)fail('Could not load local geometry ('+binaryResponse.status+').');
    const binary=await binaryResponse.arrayBuffer(),renderer=new LiveRenderer({...options,meta,binary,THREE});await renderer.warm(options.warmClip||'idle');options.onProgress?.({stage:'ready',bytes:binary.byteLength});return renderer;
  }
  const api={load,create:options=>new LiveRenderer(options),MotionBank,LiveRenderer,attentionWeights,slerpPair,blendQuaternion,version:38};
  host.RavenLive=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})();
