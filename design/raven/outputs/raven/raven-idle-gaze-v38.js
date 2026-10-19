/* Continuous idle head poses. The motion clock, not display refresh, sets turn cadence. */
(function (host, factory) {
  'use strict';
  const IdleGaze=factory();
  if(typeof module!=='undefined'&&module.exports)module.exports=IdleGaze;
  host.RavenIdleGaze=IdleGaze;
})(typeof globalThis!=='undefined'?globalThis:this,function () {
  'use strict';
  const clamp=(value,min,max)=>Math.max(min,Math.min(max,value));
  const smooth=value=>{const t=clamp(value,0,1);return t*t*(3-2*t);};
  const limits=[[-.24,.24],[-.42,.24],[-1.4,.2]];
  const ranges=[[-.19,.19],[-.17,.17],[-1.28,.12]];
  const finite=(value,label)=>{if(!Number.isFinite(value))throw new Error('Idle gaze: '+label+' must be finite.');return value;};
  const pose=value=>{
    if(!Array.isArray(value)||value.length!==3)throw new Error('Idle gaze: pose needs [tilt,pitch,yaw].');
    return value.map((v,i)=>clamp(finite(v,'angle'),limits[i][0],limits[i][1]));
  };
  class IdleGaze {
    constructor({rng=Math.random,intervalMs=5000,turnMs=187.5,pointerResponseMs=119.067789}={}) {
      if(typeof rng!=='function')throw new Error('Idle gaze: rng must be a function.');
      this.rng=rng;this.intervalMs=finite(intervalMs,'interval');this.turnMs=finite(turnMs,'turn duration');this.pointerResponseMs=finite(pointerResponseMs,'pointer response');
      if(intervalMs<=0||turnMs<=0||turnMs>=intervalMs||pointerResponseMs<=0)throw new Error('Idle gaze: invalid timing.');
      this.reset(0);
    }
    reset(now,initialPose=[0,0,0]) {
      this.startedAt=finite(now,'clock');this.lastTime=now;this.pose=pose(initialPose);this.target=this.pose.slice();this.from=this.pose.slice();
      this.nextTurnAt=now+this.intervalMs;this.turnStartedAt=null;this.tracking=false;this.chosenTurns=0;this.skippedTicks=0;return this.pose.slice();
    }
    consumeTicks(now) {
      if(now<this.nextTurnAt)return null;
      const count=Math.floor((now-this.nextTurnAt)/this.intervalMs)+1,latest=this.nextTurnAt+(count-1)*this.intervalMs;
      this.nextTurnAt+=count*this.intervalMs;return {count,latest};
    }
    randomTarget() {
      let candidate;
      for(let attempt=0;attempt<32;attempt++){
        candidate=ranges.map(([min,max])=>min+(max-min)*clamp(finite(this.rng(),'random value'),0,1));
        if(Math.hypot((candidate[0]-this.pose[0])*.8,(candidate[1]-this.pose[1])*.8,(candidate[2]-this.pose[2])*.45)>=.16)return candidate;
      }
      // A constant test/custom random generator must not trap the controller in a rejection loop.
      const direction=this.pose[2]>-.58?-1:1;
      return [clamp(-this.pose[0],-.19,.19),clamp(-this.pose[1],-.17,.17),clamp(this.pose[2]+direction*.55,-1.28,.12)];
    }
    release(now=this.lastTime) {
      finite(now,'clock');
      if(this.tracking){const ticks=this.consumeTicks(now);if(ticks)this.skippedTicks+=ticks.count;}
      this.tracking=false;this.turnStartedAt=null;this.from=this.pose.slice();this.target=this.pose.slice();this.lastTime=Math.max(this.lastTime,now);
      return this.pose.slice();
    }
    sample(now,pointer=null,orbitTarget=null) {
      finite(now,'clock');const dt=Math.max(0,now-this.lastTime),trackingTarget=orbitTarget??pointer;
      if(trackingTarget!==null){
        const target=pose(trackingTarget),ticks=this.consumeTicks(now);if(ticks)this.skippedTicks+=ticks.count;
        this.tracking=true;this.turnStartedAt=null;
        const weight=1-Math.exp(-dt/this.pointerResponseMs);
        this.pose=pose(this.pose.map((value,i)=>value+(target[i]-value)*weight));this.from=this.pose.slice();this.target=this.pose.slice();
      }else{
        if(this.tracking)this.release(now);
        const ticks=this.consumeTicks(now);
        if(ticks){this.from=this.pose.slice();this.target=this.randomTarget();this.turnStartedAt=ticks.latest;this.chosenTurns++;this.skippedTicks+=ticks.count-1;}
        if(this.turnStartedAt!==null){
          const u=(now-this.turnStartedAt)/this.turnMs;
          if(u>=1){this.pose=this.target.slice();this.turnStartedAt=null;}
          else {const weight=smooth(u);this.pose=this.from.map((value,i)=>value+(this.target[i]-value)*weight);}
        }
      }
      this.lastTime=Math.max(this.lastTime,now);return this.pose.slice();
    }
    getState() {
      return {pose:this.pose.slice(),target:this.target.slice(),from:this.from.slice(),nextTurnAt:this.nextTurnAt,turnStartedAt:this.turnStartedAt,tracking:this.tracking,chosenTurns:this.chosenTurns,skippedTicks:this.skippedTicks};
    }
  }
  return IdleGaze;
});
