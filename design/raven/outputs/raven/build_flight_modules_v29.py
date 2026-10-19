"""Physical right/left flight banks with exact directional junctions.

Blender --background --threads 6 --python build_flight_modules_v29.py -- --scout
Omit --scout for all genuine native60fps frames. --render-existing opens the
saved compact bank; --clips and --range select independent render jobs.
Frozen v23/v24 anatomy and every existing raster/source remain unchanged.
"""
import bpy,math,json,sys,hashlib,struct,time,shutil,ast
from pathlib import Path
from mathutils import Vector,Matrix

P=Path(__file__).resolve().parent
V29_WORK=P.parents[1]/'work';V29_STUDY=V29_WORK/'flight-modules-v29-scout';V29_STUDY.mkdir(parents=True,exist_ok=True)
V29_SCOUT='--scout' in sys.argv
V29_DEST=(V29_STUDY/'frames') if V29_SCOUT else P/'flight-module-frames-v29';V29_DEST.mkdir(exist_ok=True)
V29_NATIVE=(V29_STUDY if V29_SCOUT else P)/'raven-flight-modules-v29.blend'
V29_MANIFEST=(V29_STUDY if V29_SCOUT else P)/'flight-modules-v29.json'
V29_DEFINITIONS={'steady_right':(360,6),'steady_left':(360,6),
                 'swerve_right':(600,10),'swerve_left':(600,10),
                 'wingbeats_right':(240,4),'wingbeats_left':(240,4),
                 'turn_right_to_left':(180,3),'turn_left_to_right':(180,3),
                 'roll_right':(300,5),'roll_left':(300,5),
                 'exit_right':(36,.6),'exit_left':(36,.6)}
V29_SCOUT_FRAMES={name:sorted(set([0,3,count//8,count//4,count//2,3*count//4,count-4,count-1]))
                  for name,(count,_) in V29_DEFINITIONS.items()}
V29_SCOUT_FRAMES['wingbeats_right']=V29_SCOUT_FRAMES['wingbeats_left']=[0,48,72,96,144,168,192,239]
V29_SCOUT_FRAMES['roll_right']=V29_SCOUT_FRAMES['roll_left']=[0,60,120,150,180,240,296,299]

def v29_quintic(x):
    x=max(0,min(1,x));return x*x*x*(10+x*(-15+6*x))

def v29_fast_scan(seconds,interval,start=0):
    """Original target cadence; half-duration movement, then a real hold."""
    u=max(0,(seconds-start)/interval);index=math.floor(u);fraction=u-index
    targets=(0,1,0,-1);a=targets[index%4];b=targets[(index+1)%4]
    return a+(b-a)*v29_quintic(fraction*2)

def v29_start_direction(name):
    if name.startswith('turn_'):return -1 if name=='turn_left_to_right' else 1
    return -1 if name.endswith('_left') else 1

def v29_swerve_clock(frame):
    if frame<=3:return float(frame),0
    if frame>=596:return float(476+frame-596),0
    active=593/60;source=473/60;scale=source/(active-1.75)
    t=(frame-3)/60
    def integral(t):
        if t>active/2:return active-1.75-integral(active-t)
        if t<=1.5:return .5*t
        if t<=2:
            u=(t-1.5)/.5;return .75+.5*(.5*u+.5*(2.5*u**4-3*u**5+u**6))
        return t-.875
    def rate(t):
        if t>active/2:return rate(active-t)
        if t<=1.5:return .5*scale
        if t>=2:return scale
        return (.5+.5*v29_quintic((t-1.5)/.5))*scale
    return 3+60*scale*integral(t),rate(t)

if '--render-existing' not in sys.argv:
    # Only load the accepted procedural live rig. Adjust the private legacy
    # dive capture to its actual v26 phase975/1200; no old file is modified.
    v29_old_source=(P/'build_flight_modules_v27.py').read_text(encoding='utf-8')
    v29_prefix=v29_old_source.split('    # Compact banks retain each unique deformation')[0]
    old_assignment="source=(P/'build_chat_flight.py').read_text(encoding='utf-8').split('\\nstart=1\\nfor name,')[0]"
    new_assignment=old_assignment+".replace('110/160','(975/1200)')"
    assert old_assignment in v29_prefix
    v29_prefix=v29_prefix.replace(old_assignment,new_assignment)
    exec(compile(v29_prefix,str(P/'build_flight_modules_v27.py'),'exec'),globals())
    v29_old_pose=module_pose;v29_old_metadata=metadata;v29_fingerprint=fingerprint
    V29_SCOUT='--scout' in sys.argv
    V29_DEST=(V29_STUDY/'frames') if V29_SCOUT else P/'flight-module-frames-v29';V29_DEST.mkdir(exist_ok=True)
    V29_NATIVE=(V29_STUDY if V29_SCOUT else P)/'raven-flight-modules-v29.blend'
    V29_MANIFEST=(V29_STUDY if V29_SCOUT else P)/'flight-modules-v29.json'
    scene.render.fps=60;scene.render.threads_mode='FIXED';scene.render.threads=6
    scene.cycles.use_animated_seed=False
    V29_CAMERA=(camera.location.copy(),camera.rotation_euler.copy(),camera.data.ortho_scale)

    def v29_capture():
        return {'objects':[(obj,obj.location.copy(),obj.rotation_euler.to_quaternion(),obj.scale.copy()) for obj in animated],
                'rotations':{obj.name:obj.rotation_euler.copy() for obj in animated},
                'keys':[(key,key.value) for key in all_keys],
                'body':[co.copy() for co in body_coordinates],
                'legs':[(part,[vertex.co.copy() for vertex in key.data],key.value) for owner,part,key in leg_paths],
                'wings':[(mesh,[vertex.co.copy() for vertex in key.data],key.value) for mesh,key in wing_strokes],
                'camera':(camera.location.copy(),camera.rotation_euler.to_quaternion(),camera.data.ortho_scale),
                'cameraEuler':camera.rotation_euler.copy()}

    local_pose('diving',0,40);V29_DIVE_STATE=v29_capture()
    V29_DIVE_CAMERA=(camera.location.copy(),camera.rotation_euler.copy(),camera.data.ortho_scale)
    neutral_flight_junction()
    # The two canonical poses differ by an actual model yaw of180degrees.
    # The fixed camera and lights show the far side naturally, without a
    # pixel mirror or a direction flip during a visible frame.
    V29_HEADING=root.rotation_euler.z

    def v29_head(scan,pitch=.20,yaw=-.50,roll=.045):
        head.rotation_euler=(Matrix.Rotation(-torso.rotation_euler.y,4,'Y')@
                             Matrix.Rotation(1.10+pitch*scan*scan,4,'Y')@
                             Matrix.Rotation(yaw*scan,4,'Z')@
                             Matrix.Rotation(roll*scan,4,'X')).to_euler()

    def v29_direction(direction):
        if direction==-1:
            root.rotation_euler=(Matrix.Rotation(math.pi,4,'Z')@root.rotation_euler.to_matrix().to_4x4()).to_euler()

    def v29_wingbeats(frame):
        global body_coordinates
        neutral_flight_junction();seconds=frame/60
        u=max(0,min(1,(seconds-.4)/3.2));gate=smooth(u/.055)*(1-smooth((u-.945)/.055));phase=math.tau*2*u
        if gate:
            flap=.80*gate*math.sin(phase)
            for key,side in zip(wing_flexes,[-1,1]):key.value=.18*math.sin(side*.6)-.44*gate*math.cos(phase)
            shared_flight_wings(1,[Matrix.Rotation(side*(.24+flap),3,'Z') for side in [-1,1]])
            root.location.z+=.018*gate*(1-math.cos(phase));torso.rotation_euler.y+=.009*gate*math.sin(phase)
            scan=v29_fast_scan(seconds,.8,.4);v29_head(scan,.06,-.30,.025)
            body_coordinates=shared_flight_body(1);shared_flight_legs(0)
        else:scan=0
        return {'x':0,'y':-.018*gate*math.sin(phase)**2},scan,gate,phase

    def v29_turn(frame,count,direction):
        neutral_flight_junction();q=v29_quintic((frame-3)/(count-7))
        if frame<=3 or frame>=count-4:
            v29_direction(direction if frame<=3 else -direction)
            return {'x':0,'y':0},-math.pi*q,0,0,q
        # Continue turning in one direction. Positive bank raises the outer
        # wing for a clockwise yaw, lowering the wing toward the turn center.
        yaw=V29_HEADING+(math.pi if direction==-1 else 0)-math.pi*q
        bank=.36*math.sin(math.pi*q)**2
        root.rotation_euler=(Matrix.Rotation(yaw,4,'Z')@Matrix.Rotation(bank,4,'X')).to_euler()
        scan=0
        if 3<frame<count-4:scan=v29_fast_scan(frame/60,1.5);v29_head(scan)
        return {'x':direction*.042*math.sin(math.pi*q),'y':-.025*math.sin(math.pi*q)**2},-math.pi*q,bank,scan,q

    def v29_roll(frame,count,direction):
        global body_coordinates
        neutral_flight_junction();t=max(0,min(1,(frame-3)/(count-7)))
        if t<.40:angle=math.pi*v29_quintic(t/.40)
        elif t<.58:angle=math.pi
        else:angle=math.pi+math.pi*v29_quintic((t-.58)/.28)
        tuck=v29_quintic(t/.24)*(1-v29_quintic((t-.82)/.18))
        hold=v29_quintic((t-.36)/.04)*(1-v29_quintic((t-.58)/.06));tuck*=1-.32*hold
        axis=Matrix.Rotation(.90,4,'Y')@Vector((.45,0,.79)).normalized()
        if 0<t<1:
            rotation=Matrix.Rotation(angle,4,axis);heading_matrix=root.rotation_euler.to_matrix().to_4x4()
            root.rotation_euler=(heading_matrix@rotation).to_euler()
            pivot=Vector((0,0,.12));root.location+=heading_matrix@(pivot-rotation@pivot)
            drift=math.sin(math.pi*t)**2;root.location+=heading_matrix@Vector((-.16*drift,0,.09*drift))
            for key in wing_roll_tucks:key.value=tuck
            for key in wing_flexes:key.value-=.26*tuck
            distal=[Matrix.Rotation(-.20*tuck,3,'Y')@Matrix.Rotation(side*(.24+.18*tuck),3,'Z')@
                    Matrix.Rotation(-side*.12*tuck,3,'X') for side in [-1,1]]
            shared_flight_wings(1,distal)
            for foot in feet:foot.rotation_euler.y+=.25*tuck
            scan=v29_fast_scan(frame/60,1.25);v29_head(scan)
            body_coordinates=shared_flight_body(1);shared_flight_legs(0)
        else:scan=0
        v29_direction(direction)
        return {'x':0,'y':-.015*math.sin(math.pi*t)**2},scan,angle,tuck

    def v29_exit(frame,count,direction):
        global body_coordinates
        neutral_flight_junction();v29_direction(direction);a=v29_capture();b=V29_DIVE_STATE
        q=v29_quintic((frame-3)/(count-7))
        for (obj,la,ra,sa),(_,lb,rb,sb) in zip(a['objects'],b['objects']):
            obj.location=la.lerp(lb,q);obj.rotation_euler=ra.slerp(rb,q).to_euler();obj.scale=sa.lerp(sb,q)
            if q==0:obj.location=la.copy();obj.rotation_euler=a['rotations'][obj.name];obj.scale=sa.copy()
            elif q==1:obj.location=lb.copy();obj.rotation_euler=b['rotations'][obj.name];obj.scale=sb.copy()
        for (key,ka),(_,kb) in zip(a['keys'],b['keys']):key.value=ka if q==0 else kb if q==1 else ka+(kb-ka)*q
        body_coordinates=[pa.copy() if q==0 else pb.copy() if q==1 else pa.lerp(pb,q) for pa,pb in zip(a['body'],b['body'])]
        for (part,ca,va),(_,cb,vb),(owner,live_part,key) in zip(a['legs'],b['legs'],leg_paths):
            for vertex,pa,pb in zip(key.data,ca,cb):vertex.co=pa.copy() if q==0 else pb.copy() if q==1 else pa.lerp(pb,q)
            key.value=va if q==0 else vb if q==1 else va+(vb-va)*q
        for (mesh,ca,va),(_,cb,vb),(live_mesh,key) in zip(a['wings'],b['wings'],wing_strokes):
            for vertex,pa,pb in zip(key.data,ca,cb):vertex.co=pa.copy() if q==0 else pb.copy() if q==1 else pa.lerp(pb,q)
            key.value=va if q==0 else vb if q==1 else va+(vb-va)*q
        la,ra,sa=a['camera'];lb,rb,sb=b['camera'];camera.location=la.lerp(lb,q)
        camera.rotation_euler=ra.slerp(rb,q).to_euler();camera.data.ortho_scale=sa+(sb-sa)*q
        if q==0:camera.location=la.copy();camera.rotation_euler=a['cameraEuler'];camera.data.ortho_scale=sa
        elif q==1:camera.location=lb.copy();camera.rotation_euler=b['cameraEuler'];camera.data.ortho_scale=sb
        return q

    def v29_pose(name,frame,count):
        global body_coordinates
        direction=v29_start_direction(name)
        heading_offset=bank=scan=0;extra={}
        camera.location,camera.rotation_euler,camera.data.ortho_scale=V29_CAMERA
        if name.startswith(('steady_','swerve_')):
            original='steady_soar' if name.startswith('steady_') else 'swerve';old_count=360 if original=='steady_soar' else 480
            source_frame,rate=(frame,1) if original=='steady_soar' else v29_swerve_clock(frame)
            motion,heading_offset,bank,old_scan=v29_old_pose(original,source_frame,old_count)
            if 3<frame<count-4:
                scan=v29_fast_scan(frame/60,.75 if original=='steady_soar' else 1);v29_head(scan)
                body_coordinates=shared_flight_body(1)
            v29_direction(direction)
            extra.update(sourceFrame=round(source_frame,9),sourceClockRate=round(rate,9),previousScan=round(old_scan,9))
            motion={'x':motion['x']*direction,'y':motion['y']}
        elif name.startswith('wingbeats_'):
            motion,scan,gate,phase=v29_wingbeats(frame);v29_direction(direction)
            extra.update(wingbeatGate=round(gate,9),wingbeatPhase=round(phase,9))
        elif name.startswith('turn_'):
            motion,heading_offset,bank,scan,q=v29_turn(frame,count,direction);extra['turnProgress']=round(q,9)
        elif name.startswith('roll_'):
            motion,scan,angle,tuck=v29_roll(frame,count,direction)
            extra.update(rollAngle=round(angle,9),wingTuck=round(tuck,9))
        elif name.startswith('exit_'):
            q=v29_exit(frame,count,direction);motion={'x':0,'y':0};extra['bridgeProgress']=round(q,9)
        else:raise ValueError(name)
        if not name.startswith('exit_'):
            assert (camera.location-V29_CAMERA[0]).length<1e-7
            assert abs(camera.data.ortho_scale-V29_CAMERA[2])<1e-7
        return motion,heading_offset,bank,scan,extra

    data={'version':29,'fps':60,'frameWidth':512,'frameHeight':512,'baseSourceSha256':prototype_base_sha256,
          'v27ProceduralSourceSha256':hashlib.sha256(v29_old_source.encode('utf-8')).hexdigest(),
          'junction':{'idRight':'neutral-flight-v29-right','idLeft':'neutral-flight-v29-left',
                      'headingRight':V29_HEADING,'headingLeft':V29_HEADING+math.pi,'endpointHoldFrames':4,
                      'physicalDirectionRotationDegrees':180,'camera':'fixed'},
          'headTurns':{'movementDurationMultiplier':.5,'targetCadenceMultiplier':1,
                       'interpolation':'quintic first half; exact target hold second half',
                       'steadyTargetIntervalSeconds':.75,'swerveTargetIntervalSeconds':1,
                       'wingbeatTargetIntervalSeconds':.8,'headClockIndependentOfSwerveRetiming':True},
          'retiming':{'steadyRestoredSeconds':6,'swerveSourceSeconds':8,'swerveSeconds':10,
                      'swerveEdgeClockRate':(473/60)/(593/60-1.75)*.5,
                      'swerveMiddleClockRate':(473/60)/(593/60-1.75),
                      'swerveEdgeSeconds':1.5,'swerveClockTransitionSeconds':.5},
          'clips':{},'sampling':{'kind':'genuine continuous Blender rig poses','fps':60}}
    banks={};usage={};expected={};start=1;canonical={}

    def v29_bank(obj,coords,label,frame,value):
        digest=hashlib.sha256(b''.join(struct.pack('<3f',*point) for point in coords)).hexdigest();key_id=(obj.name,digest)
        if key_id not in banks:
            key=obj.shape_key_add(name='v29 %s %04d'%(label,len(banks)))
            for vertex,co in zip(key.data,coords):vertex.co=co
            key.value=0;banks[key_id]=key;usage[key_id]={}
        usage[key_id][frame]=value;return key_id

    for name,(count,duration) in V29_DEFINITIONS.items():
        direction=v29_start_direction(name)
        entry='neutral-flight-v29-'+('left' if direction==-1 else 'right')
        exit=entry
        if name.startswith('turn_'):exit='neutral-flight-v29-'+('right' if direction==-1 else 'left')
        if name.startswith('exit_'):exit='legacy-dive-v26-phase975'
        clip={'frames':count,'fps':60,'duration':duration,'loop':False,'startFrame':start,
              'direction':direction,'endDirection':-direction if name.startswith('turn_') else direction,
              'startJunction':entry,'endJunction':exit,'entryJunction':entry,'exitJunction':exit,
              'sourcePattern':'flight-module-frames-v29/'+name+'-%04d.png','poses':[]}
        data['clips'][name]=clip;scene.timeline_markers.new('v29 '+name,frame=start)
        for f in range(count):
            frame=start+f;scene.frame_set(frame)
            motion,heading_offset,bank,scan,extra=v29_pose(name,f,count)
            current=[v29_bank(body,body_coordinates,'neck',frame,1)]
            for owner,part,key in leg_paths:
                current.append(v29_bank(part,[v.co.copy() for v in key.data],'leg',frame,key.value));key.value=0
            for mesh,key in wing_strokes:
                current.append(v29_bank(mesh,[v.co.copy() for v in key.data],'collar',frame,key.value));key.value=0
            for key_id in current:banks[key_id].value=usage[key_id][frame]
            expected[(name,f)]=v29_fingerprint()
            pose_info=v29_old_metadata(motion,heading_offset,bank,scan);pose_info.update(extra)
            pose_info.update(modelHeading=round(root.rotation_euler.z,9),headTurnProgress=float(scan),
                             evaluatedGeometrySha256=expected[(name,f)])
            for key_id in current:banks[key_id].value=0
            for obj in animated:
                for prop in ['location','rotation_euler','scale']:obj.keyframe_insert(data_path=prop,frame=frame)
            for key in all_keys:key.keyframe_insert(data_path='value',frame=frame)
            for prop in ['location','rotation_euler']:camera.keyframe_insert(data_path=prop,frame=frame)
            camera.data.keyframe_insert(data_path='ortho_scale',frame=frame)
            clip['poses'].append(pose_info)
        print('V29_BAKED',name,count,'frames;',len(banks),'compact shapes',flush=True);start+=count+20
    for key_id,key in banks.items():
        values=usage[key_id];events={}
        for frame,value in values.items():
            if frame-1 not in values:events[frame-1]=0
            events[frame]=value
            if frame+1 not in values:events[frame+1]=0
        for frame,value in sorted(events.items()):key.value=value;key.keyframe_insert(data_path='value',frame=frame)
        key.value=0
    for owner,part,key in leg_paths:key.value=0
    for mesh,key in wing_strokes:key.value=0
    checked=0
    for name,(count,_) in V29_DEFINITIONS.items():
        for f in range(count):
            scene.frame_set(data['clips'][name]['startFrame']+f)
            assert v29_fingerprint()==expected[(name,f)],('Native/live geometry mismatch',name,f)
            checked+=1
    right=expected[('steady_right',0)];left=expected[('steady_left',0)];dive=expected[('exit_right',35)]
    for name,(count,_) in V29_DEFINITIONS.items():
        clip=data['clips'][name]
        for endpoint,indices in [(clip['startJunction'],range(4)),(clip['endJunction'],range(count-4,count))]:
            target={'neutral-flight-v29-right':right,'neutral-flight-v29-left':left,'legacy-dive-v26-phase975':dive}[endpoint]
            for f in indices:assert expected[(name,f)]==target,('Noncanonical endpoint',name,f,endpoint)
    scene.frame_start=1;scene.frame_end=start-20;scene.render.fps=60;scene.frame_set(1)
    scene['README']='v29 composable physical-direction flight: restored6s steady,10s swerve with slower first/last bends and unchanged middle,4s controlled beats,3s actual180degree turns,5s neutral rolls,0.6s exact legacy dive bridges. Fixed flight camera and unchanged accepted anatomy. Head targets retain cadence, reach them in half the interval and hold. Exact four-frame directional endpoints; no raster mirroring or body deformation interpolation.'
    scene['Base source SHA256']=prototype_base_sha256
    data['sampling'].update(nativeFrames=checked,liveGeometryMatchesNativeFrames=checked,
                            uniqueGeometryPoses=len(set(expected.values())),compactGeometryShapes=len(banks))
    data['geometryJunctions']={'right':right,'left':left,'legacyDive':dive}
    bpy.ops.wm.save_as_mainfile(filepath=str(V29_NATIVE));V29_MANIFEST.write_text(json.dumps(data,indent=2),encoding='utf-8')
else:
    bpy.ops.wm.open_mainfile(filepath=str(V29_NATIVE));scene=bpy.context.scene
    data=json.loads(V29_MANIFEST.read_text(encoding='utf-8'))
    v29_source=(P/'build_flight_modules_v27.py').read_text(encoding='utf-8')
    node=next(node for node in ast.parse(v29_source).body if isinstance(node,ast.FunctionDef) and node.name=='fingerprint')
    exec(compile(ast.get_source_segment(v29_source,node),str(P/'build_flight_modules_v27.py'),'exec'),globals());v29_fingerprint=fingerprint

if '--render-threads' in sys.argv:
    scene.render.threads_mode='FIXED';scene.render.threads=int(sys.argv[sys.argv.index('--render-threads')+1])

cache={};fresh=reused=0;audit=[];started=time.perf_counter()
if '--reuse-cache' in sys.argv:
    cache=json.loads(Path(sys.argv[sys.argv.index('--reuse-cache')+1]).read_text(encoding='utf-8'))['entries']
for name,(count,_) in V29_DEFINITIONS.items():
    if '--clips' in sys.argv and name not in sys.argv[sys.argv.index('--clips')+1].split(','):continue
    indices=V29_SCOUT_FRAMES[name] if V29_SCOUT else range(count)
    if '--bake-only' in sys.argv:indices=[]
    if '--range' in sys.argv:
        ranges={part.split(':')[0]:(int(part.split(':')[1]),int(part.split(':')[2])) for part in sys.argv[sys.argv.index('--range')+1].split(',')}
        if name not in ranges:continue
        lo,hi=ranges[name];indices=[f for f in indices if lo<=f<hi]
    for f in indices:
        scene.frame_set(data['clips'][name]['startFrame']+f);key=v29_fingerprint();target=V29_DEST/f'{name}-{f:04d}.png'
        if key in cache:
            if Path(cache[key]).resolve()!=target.resolve():shutil.copyfile(cache[key],target)
            reused+=1;kind='EXACT_GEOMETRY_REUSE'
        else:
            scene.render.filepath=str(target);bpy.ops.render.render(write_still=True)
            cache[key]=str(target);fresh+=1;kind='FRESH_RENDER'
        audit.append({'clip':name,'frame':f,'fingerprint':key,'kind':kind})
        print('V29_RENDER',name,f,kind,flush=True)
available=sum(sum((P/clip['sourcePattern'].replace('%04d',f'{f:04d}')).exists() for f in range(clip['frames'])) for clip in data['clips'].values()) if not V29_SCOUT else len(audit)
data['sampling'].update(renderedFrames=available,freshRenderedFrames=fresh,exactGeometryReusedFrames=reused,
                        renderedThisJobFrames=len(audit),renderBackend=scene.cycles.device)
if '--no-manifest-write' not in sys.argv:V29_MANIFEST.write_text(json.dumps(data,indent=2),encoding='utf-8')
tag=sys.argv[sys.argv.index('--report-tag')+1] if '--report-tag' in sys.argv else 'complete'
(V29_STUDY if V29_SCOUT else V29_WORK).joinpath(f'flight-modules-v29-render-audit-{tag}.json').write_text(json.dumps({
    'frames':len(audit),'fresh':fresh,'reused':reused,'seconds':time.perf_counter()-started,'poses':audit},indent=2),encoding='utf-8')
(V29_STUDY if V29_SCOUT else V29_WORK).joinpath(f'flight-modules-v29-cache-{tag}.json').write_text(json.dumps({'entries':cache}),encoding='utf-8')
print('V29_NATIVE_COMPLETE',len(audit),'frames;',fresh,'fresh;',reused,'exact repeats',flush=True)
