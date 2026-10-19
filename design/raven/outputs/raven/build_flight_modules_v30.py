"""Native fixed-camera flight for the bounded, depth-aware v30 patrol.

The route tangent and Blender yaw use the SAME numerical course. No sprite
rotation or mirroring is used. Run --scout, then --bake-only, then parallel
--render-existing --clips jobs. All accepted v29/earlier sources are immutable.
"""
import bpy, math, json, sys, hashlib, struct, time, shutil, ast, re
from pathlib import Path
from mathutils import Vector, Matrix

P=Path(__file__).resolve().parent
sys.path.insert(0,str(P))
from flight_bounds_v30 import projected_mesh_bounds
WORK30=(P.parents[1]/'work') if P.parent.name=='outputs' else P/'work'
STUDY30=WORK30/'flight-modules-v30-scout'; STUDY30.mkdir(parents=True,exist_ok=True)
SCOUT30='--scout' in sys.argv
DEST30=(STUDY30/'frames') if SCOUT30 else P/'flight-module-frames-v30'; DEST30.mkdir(exist_ok=True)
NATIVE30=(STUDY30 if SCOUT30 else P)/'raven-flight-modules-v30.blend'
MANIFEST30=(STUDY30 if SCOUT30 else P)/'flight-modules-v30.json'
A=math.radians(25)
HEADINGS30={'r':0.,'ra':A,'rt':-A,'l':math.pi,'la':math.pi-A,'lt':math.pi+A}
DEFS30={}
for h in HEADINGS30: DEFS30['steady_'+h]={'frames':360,'duration':6.,'action':'soar_forward','a':h,'b':h}
for a,b in [('r','ra'),('ra','r'),('r','rt'),('rt','r'),('l','la'),('la','l'),('l','lt'),('lt','l')]:
    DEFS30['connect_'+a+'_'+b]={'frames':90,'duration':1.5,'action':'connect','a':a,'b':b}
for a,b,suffix,delta in [('r','l','away',math.pi),('r','l','toward',-math.pi),
                         ('l','r','away',-math.pi),('l','r','toward',math.pi)]:
    DEFS30['turn_'+a+'_to_'+b+'_'+suffix]={'frames':180,'duration':3.,'action':'turn','a':a,'b':b,'delta':delta}
for h in ['r','l']:
    for action,count,duration in [('wingbeats',240,4.),('roll',300,5.),('exit',36,.6)]:
        DEFS30[action+'_'+h]={'frames':count,'duration':duration,'action':action,'a':h,'b':h if action!='exit' else 'dive'}
DEFS30['entry_l']={'frames':36,'duration':.6,'action':'entry','a':'v29_left','b':'l'}

def q30(x):
    x=max(0.,min(1.,x)); return x*x*x*(10+x*(-15+6*x))

def dq30(x):
    return 30*x*x*(1-x)**2 if 0<x<1 else 0.

def scan30(seconds,duration,sign=1):
    # Common center-down junction. A 0.375-second snap is independent of
    # long holds; each six-second bank surveys one side for about2.4seconds.
    if duration>=5.5:
        return sign*q30((seconds-2.60)/.375)*(1-q30((seconds-(duration-.45))/.375))
    if duration>=3.5:
        return sign*q30((seconds-1.15)/.375)*(1-q30((seconds-(duration-.45))/.375))
    return 0.

def course30(spec,f):
    n=spec['frames']; duration=spec['duration']; t=f/(n-1)*duration
    a=HEADINGS30.get(spec['a'],HEADINGS30['l']); b=HEADINGS30.get(spec['b'],a)
    if spec['action']=='entry': a=b
    delta=spec.get('delta',b-a)
    u=(f-3)/(n-7); theta=a+delta*q30(u)
    rate=delta*dq30(u)/(duration*(n-7)/(n-1))
    speed=1.
    if spec['action']=='wingbeats':
        # Two bounded powered surges, with exact neutral speed at joins.
        speed+=1.25*dq30((t-.80)/.80)+1.25*dq30((t-2.40)/.80)
    if spec['action']=='exit': speed=1-q30((f-3)/(n-7))
    return t,theta,rate,speed

def routes30(spec):
    n=spec['frames']; duration=spec['duration']; dt=duration/(n-1); x=z=0.; result=[]
    for f in range(n):
        t,theta,rate,speed=course30(spec,f)
        if f:
            # Dense midpoint integration makes endpoints and derivative checks
            # independent of render rate; actual sprite headings use this theta.
            for k in range(32):
                _,angle,_,velocity=course30(spec,f-1+(k+.5)/32)
                x+=math.cos(angle)*velocity*dt/32; z+=math.sin(angle)*velocity*dt/32
        result.append({'x':round(x,12),'z':round(z,12),'yaw':round(theta,12),
                       'vx':round(math.cos(theta)*speed,12),'vz':round(math.sin(theta)*speed,12),
                       'speed':round(speed,12),'curvature':round(rate/max(speed,1e-8),12)})
    return result

def private_source30(path):
    """Keep old helper files immutable, but route all their scratch into this kit."""
    source=path.read_text(encoding='utf-8').replace("P.parents[1]/'work'",'WORK30')
    return re.sub(r"\(P/'([^']+\.py)'\)\.read_text\(encoding='utf-8'\)",
                  lambda found:"private_source30(P/'%s')"%found.group(1),source)

if '--render-existing' not in sys.argv:
    # Load only the accepted live rig and helpers, before its bake/output loop.
    source29=private_source30(P/'build_flight_modules_v29.py')
    prefix29=source29.split("    data={'version':29")[0]
    exec(compile(prefix29,str(P/'build_flight_modules_v29.py'),'exec'),globals())
    scene.render.fps=60; scene.render.threads_mode='FIXED'; scene.render.threads=6
    scene.cycles.use_animated_seed=False
    SOURCE_CAMERA30=(camera.location.copy(),camera.rotation_euler.copy(),camera.data.ortho_scale)
    bpy.context.view_layer.update()
    right=camera.matrix_world.to_3x3()@Vector((1,0,0))
    SIDE30=math.atan2(right.y,right.x)
    # Positive depth is away along the horizontal camera sightline.
    forward=camera.matrix_world.to_3x3()@Vector((0,0,-1))
    away=Vector((forward.x,forward.y,0)).normalized()
    right=Vector((right.x,right.y,0)).normalized()
    DEPTH_SIGN30=1 if right.cross(away).z>0 else -1
    # A small fixed lower elevation reveals the underside of the wings while
    # keeping their body heading genuinely broadside. Legacy bridges retain
    # the accepted camera at their outside endpoints.
    look30=away*math.cos(math.radians(8))+Vector((0,0,math.sin(math.radians(8))))
    rotation30=look30.to_track_quat('-Z','Y'); camera_local(rotation30,SOURCE_CAMERA30[2])
    CAMERA30=(camera.location.copy(),camera.rotation_euler.copy(),camera.data.ortho_scale)
    DEPTH_SCREEN_Y30=math.sin(math.radians(8))

    def neutral30(heading):
        global body_coordinates
        neutral_flight_junction()
        root.rotation_euler=(0,0,SIDE30+DEPTH_SIGN30*HEADINGS30[heading])
        body_coordinates=shared_flight_body(1); shared_flight_legs(0)
        camera.location,camera.rotation_euler,camera.data.ortho_scale=CAMERA30

    def bridge30(frame,count,a,b):
        global body_coordinates
        q=q30((frame-3)/(count-7))
        for (obj,la,ra,sa),(_,lb,rb,sb) in zip(a['objects'],b['objects']):
            obj.location=la.lerp(lb,q); obj.rotation_euler=ra.slerp(rb,q).to_euler(); obj.scale=sa.lerp(sb,q)
            if q==0: obj.location=la.copy(); obj.rotation_euler=a['rotations'][obj.name]; obj.scale=sa.copy()
            elif q==1: obj.location=lb.copy(); obj.rotation_euler=b['rotations'][obj.name]; obj.scale=sb.copy()
        for (key,ka),(_,kb) in zip(a['keys'],b['keys']): key.value=ka if q==0 else kb if q==1 else ka+(kb-ka)*q
        body_coordinates=[pa.copy() if q==0 else pb.copy() if q==1 else pa.lerp(pb,q) for pa,pb in zip(a['body'],b['body'])]
        for (_,ca,va),(_,cb,vb),(_,_,key) in zip(a['legs'],b['legs'],leg_paths):
            for vertex,pa,pb in zip(key.data,ca,cb): vertex.co=pa.copy() if q==0 else pb.copy() if q==1 else pa.lerp(pb,q)
            key.value=va if q==0 else vb if q==1 else va+(vb-va)*q
        for (_,ca,va),(_,cb,vb),(_,key) in zip(a['wings'],b['wings'],wing_strokes):
            for vertex,pa,pb in zip(key.data,ca,cb): vertex.co=pa.copy() if q==0 else pb.copy() if q==1 else pa.lerp(pb,q)
            key.value=va if q==0 else vb if q==1 else va+(vb-va)*q
        la,ra,sa=a['camera']; lb,rb,sb=b['camera']; camera.location=la.lerp(lb,q)
        camera.rotation_euler=ra.slerp(rb,q).to_euler(); camera.data.ortho_scale=sa+(sb-sa)*q
        if q==0: camera.location=la.copy(); camera.rotation_euler=a['cameraEuler']; camera.data.ortho_scale=sa
        elif q==1: camera.location=lb.copy(); camera.rotation_euler=b['cameraEuler']; camera.data.ortho_scale=sb
        return q

    neutral_flight_junction(); v29_direction(-1)
    camera.location,camera.rotation_euler,camera.data.ortho_scale=SOURCE_CAMERA30
    ENTRY_OLD30=v29_capture()
    STATES30={}
    for h in HEADINGS30:
        neutral30(h); STATES30[h]=v29_capture()
        # Preserve the exact camera quaternion used by the portable camera
        # patch, avoiding an Euler round-trip inside intermediate bridges.
        STATES30[h]['camera']=(CAMERA30[0].copy(),rotation30.copy(),CAMERA30[2])

    def pose30(name,f,spec,route):
        global body_coordinates
        n=spec['frames']; duration=spec['duration']; seconds=f/(n-1)*duration
        action=spec['action']; heading=spec['a']; extra={}; motion={'x':0,'y':0}; scan=bank=0.
        camera.location,camera.rotation_euler,camera.data.ortho_scale=CAMERA30
        if action=='entry':
            extra['bridgeProgress']=bridge30(f,n,ENTRY_OLD30,STATES30['l'])
        elif action=='exit':
            extra['bridgeProgress']=bridge30(f,n,STATES30[heading],V29_DIVE_STATE)
        elif action=='roll':
            motion,oldscan,angle,tuck=v29_roll(f,n,1)
            old_matrix=root.rotation_euler.to_matrix().to_4x4()
            rotation=Matrix.Rotation(SIDE30+DEPTH_SIGN30*HEADINGS30[heading]-V29_HEADING,4,'Z')
            root.rotation_euler=(rotation@old_matrix).to_euler()
            root.location=LOCAL_ROOT+rotation@(root.location-LOCAL_ROOT)
            scan=scan30(seconds,duration,1 if heading=='r' else -1); v29_head(scan)
            body_coordinates=shared_flight_body(1); shared_flight_legs(0)
            extra.update(rollAngle=round(angle,9),wingTuck=round(tuck,9))
        else:
            if action=='wingbeats':
                motion,oldscan,gate,phase=v29_wingbeats(f)
                extra.update(wingbeatGate=round(gate,9),wingbeatPhase=round(phase,9))
            else:
                neutral_flight_junction()
                if 3<f<n-4:
                    u=f/(n-1); envelope=q30((seconds-.05)/.7)*(1-q30((seconds-(duration-.8))/.7))
                    wind=envelope*math.sin(math.tau*u); trim=envelope*math.sin(math.tau*3*u)
                    torso.rotation_euler.y=.90+.012*wind; tail.rotation_euler.y=-.515+.009*wind
                    tail.rotation_euler.z=.010*trim
                    for key,side in zip(wing_flexes,[-1,1]): key.value=.18*math.sin(side*.6)+.065*envelope*math.sin(math.tau*u+side*.6)
                    shared_flight_wings(1,[Matrix.Rotation(side*(.24+.010*wind+side*.006*trim),3,'Z')@Matrix.Rotation(side*.010*trim,3,'X') for side in [-1,1]])
                    for foot,side in zip(feet,[-1,1]): foot.location.z+=.008*envelope*math.sin(math.tau*u+side*.7); foot.rotation_euler.y+=.030*wind
                    motion['y']=-.023*wind
            yaw=SIDE30+DEPTH_SIGN30*route['yaw']
            # Bank derives from yaw rate, with neutral zero curvature at joins.
            bank=-DEPTH_SIGN30*.30*math.tanh(route['curvature']/1.1)
            root.rotation_euler=(Matrix.Rotation(yaw,4,'Z')@Matrix.Rotation(bank,4,'X')).to_euler()
            if 3<f<n-4: scan=scan30(seconds,duration,-1 if heading in ['ra','lt','l'] else 1); v29_head(scan)
            body_coordinates=shared_flight_body(1); shared_flight_legs(0)
        if action not in ['entry','exit'] and (f<=3 or f>=n-4):
            # Use identical Euler values and exact geometry, including for
            # unwrapped360degree course endpoints; tiny matrixroundoff is not
            # allowed to turn a canonical junction into a different raster.
            neutral30(spec['a'] if f<=3 else spec['b']); motion={'x':0,'y':0}; scan=bank=0.
        if action not in ['entry','exit']:
            camera.location,camera.rotation_euler,camera.data.ortho_scale=CAMERA30
            assert (camera.location-CAMERA30[0]).length<1e-7 and abs(camera.data.ortho_scale-CAMERA30[2])<1e-7
        return motion,bank,scan,extra

    data={'version':30,'fps':60,'frameWidth':512,'frameHeight':512,'baseSourceSha256':prototype_base_sha256,
          'headings':{h:{'yaw':theta,'modelYaw':SIDE30+DEPTH_SIGN30*theta} for h,theta in HEADINGS30.items()},
          'camera':{'kind':'fixed orthographic native sprite camera','sideModelYaw':SIDE30,'depthYawSign':DEPTH_SIGN30,
                    'location':list(CAMERA30[0]),'rotation':list(CAMERA30[1]),'orthoScale':CAMERA30[2],
                    'depthScreenYPerUnit':DEPTH_SCREEN_Y30,'elevationBelowPlaneDegrees':8.},
          'composition':{'plane':{'minX':-8,'maxX':8,'minZ':-8,'maxZ':8},'neutralSpeed':1,'farScale':.8,
                         'projectionDepthSlope':DEPTH_SCREEN_Y30,
                         'motionUnits':'route.x/right and route.z/away in physical plane units; motion.y viewport-height wind bob',
                         'mainActions':['soar_forward','soar_backward','wingbeats'],'routeActions':['connect','turn'],
                         'canonicalVelocity':'one world unit/second along heading; zero junction curvature'},
          'headTurns':{'movementSeconds':.375,'steadyInitialHoldSeconds':2.60,'steadySideHoldSeconds':2.575,
                       'gaze':'downward center and alternate-eye side banks; center at all exact junctions'},
          'clips':{},'sampling':{'kind':'genuine Blender60fps evaluated poses','fps':60}}
    banks={}; usage={}; expected={}; start=1

    def bank30(obj,coords,label,frame,value):
        digest=hashlib.sha256(b''.join(struct.pack('<3f',*point) for point in coords)).hexdigest(); keyid=(obj.name,digest)
        if keyid not in banks:
            key=obj.shape_key_add(name='v30 %s %04d'%(label,len(banks)))
            for vertex,co in zip(key.data,coords): vertex.co=co
            key.value=0; banks[keyid]=key; usage[keyid]={}
        usage[keyid][frame]=value; return keyid

    for name,spec in DEFS30.items():
        n=spec['frames']; routes=routes30(spec)
        a='neutral-flight-v29-left' if spec['a']=='v29_left' else 'neutral-flight-v30-'+spec['a']
        b='legacy-dive-v26-phase975' if spec['b']=='dive' else 'neutral-flight-v30-'+spec['b']
        clip={'frames':n,'fps':60,'duration':spec['duration'],'loop':False,'action':spec['action'],
              'startFrame':start,'startHeading':spec['a'],'endHeading':spec['b'],'startJunction':a,'endJunction':b,
              'entryJunction':a,'exitJunction':b,'sourcePattern':'flight-module-frames-v30/'+name+'-%04d.png','poses':[],
              'displacement':{k:routes[-1][k] for k in ['x','z']},
              'endpointVelocity':{'start':{k:routes[0][k] for k in ['vx','vz']},'end':{k:routes[-1][k] for k in ['vx','vz']}}}
        data['clips'][name]=clip; scene.timeline_markers.new('v30 '+name,frame=start)
        for f in range(n):
            frame=start+f; scene.frame_set(frame); motion,bank,scan,extra=pose30(name,f,spec,routes[f])
            current=[bank30(body,body_coordinates,'body',frame,1)]
            for _,part,key in leg_paths: current.append(bank30(part,[v.co.copy() for v in key.data],'leg',frame,key.value)); key.value=0
            for mesh,key in wing_strokes: current.append(bank30(mesh,[v.co.copy() for v in key.data],'collar',frame,key.value)); key.value=0
            for keyid in current: banks[keyid].value=usage[keyid][frame]
            expected[(name,f)]=v29_fingerprint()
            pose_info30=v29_old_metadata(motion,routes[f]['yaw'],bank,scan); pose_info30.update(extra)
            pose_info30.update(route=routes[f],modelHeading=round(root.rotation_euler.z,9),evaluatedGeometrySha256=expected[(name,f)])
            pose_info30.update(bounds=projected_mesh_bounds(scene,camera),boundsKind='conservative native mesh projection plus2pixels')
            for keyid in current: banks[keyid].value=0
            for obj in animated:
                for prop in ['location','rotation_euler','scale']: obj.keyframe_insert(data_path=prop,frame=frame)
            for key in all_keys: key.keyframe_insert(data_path='value',frame=frame)
            for prop in ['location','rotation_euler']: camera.keyframe_insert(data_path=prop,frame=frame)
            camera.data.keyframe_insert(data_path='ortho_scale',frame=frame); clip['poses'].append(pose_info30)
        print('V30_BAKED',name,n,'compact_shapes',len(banks),flush=True); start+=n+20
    for keyid,key in banks.items():
        values=usage[keyid]; events={}
        for frame,value in values.items():
            if frame-1 not in values: events[frame-1]=0
            events[frame]=value
            if frame+1 not in values: events[frame+1]=0
        for frame,value in sorted(events.items()): key.value=value; key.keyframe_insert(data_path='value',frame=frame)
        key.value=0
    for _,_,key in leg_paths: key.value=0
    for _,key in wing_strokes: key.value=0
    checked=0
    for name,spec in DEFS30.items():
        for f in range(spec['frames']):
            scene.frame_set(data['clips'][name]['startFrame']+f)
            assert v29_fingerprint()==expected[(name,f)],('Native/live mismatch',name,f)
            checked+=1
    junctions={}
    for name,clip in data['clips'].items():
        n=clip['frames']
        for jid,indices in [(clip['startJunction'],range(4)),(clip['endJunction'],range(n-4,n))]:
            if jid not in junctions: junctions[jid]=expected[(name,next(iter(indices)))]
            for f in indices: assert expected[(name,f)]==junctions[jid],('Noncanonical endpoint',name,f,jid)
    data['geometryJunctions']=junctions
    data['sampling'].update(nativeFrames=checked,liveGeometryMatchesNativeFrames=checked,
                            uniqueGeometryPoses=len(set(expected.values())),compactGeometryShapes=len(banks))
    scene.frame_start=1; scene.frame_end=start-20; scene.render.fps=60; scene.frame_set(1)
    scene['README']='v30 square-airspace flight. Six physical true-side/shallow headings with fixed accepted camera/light elevation. Native yaw and bank derive from same route course and curvature that drives JS. Four smooth handed180 U-turns, eight shallow connectors, controlled wingbeats and rolls, precise accepted entry/return endpoints; longer downward scan holds and0.375s snaps.'
    bpy.ops.wm.save_as_mainfile(filepath=str(NATIVE30)); MANIFEST30.write_text(json.dumps(data,indent=2),encoding='utf-8')
else:
    bpy.ops.wm.open_mainfile(filepath=str(NATIVE30)); scene=bpy.context.scene
    data=json.loads(MANIFEST30.read_text(encoding='utf-8'))
    source27=(P/'build_flight_modules_v27.py').read_text(encoding='utf-8')
    node=next(n for n in ast.parse(source27).body if isinstance(n,ast.FunctionDef) and n.name=='fingerprint')
    exec(compile(ast.get_source_segment(source27,node),str(P/'build_flight_modules_v27.py'),'exec'),globals())
    v29_fingerprint=fingerprint

if '--render-threads' in sys.argv: scene.render.threads_mode='FIXED'; scene.render.threads=int(sys.argv[sys.argv.index('--render-threads')+1])
scene.render.use_persistent_data=True
cache={}; fresh=reused=0; audit=[]; begun=time.perf_counter()
if '--reuse-cache' in sys.argv: cache=json.loads(Path(sys.argv[sys.argv.index('--reuse-cache')+1]).read_text(encoding='utf-8'))['entries']
for name,spec in DEFS30.items():
    if '--clips' in sys.argv and name not in sys.argv[sys.argv.index('--clips')+1].split(','): continue
    n=spec['frames']; indices=sorted(set([0,3,n//8,n//4,n//2,3*n//4,n-4,n-1])) if SCOUT30 else range(n)
    if '--bake-only' in sys.argv: indices=[]
    if '--range' in sys.argv:
        ranges={p.split(':')[0]:(int(p.split(':')[1]),int(p.split(':')[2])) for p in sys.argv[sys.argv.index('--range')+1].split(',')}
        if name not in ranges: continue
        lo,hi=ranges[name]; indices=[f for f in indices if lo<=f<hi]
    for f in indices:
        scene.frame_set(data['clips'][name]['startFrame']+f); key=v29_fingerprint(); target=DEST30/f'{name}-{f:04d}.png'
        assert key==data['clips'][name]['poses'][f]['evaluatedGeometrySha256'],('Reopened geometry mismatch',name,f)
        if key in cache:
            if Path(cache[key]).resolve()!=target.resolve(): shutil.copyfile(cache[key],target)
            reused+=1; kind='EXACT_GEOMETRY_REUSE'
        else:
            scene.render.filepath=str(target); bpy.ops.render.render(write_still=True)
            cache[key]=str(target); fresh+=1; kind='FRESH_RENDER'
        audit.append({'clip':name,'frame':f,'fingerprint':key,'kind':kind}); print('V30_RENDER',name,f,kind,flush=True)
available=sum(sum((P/(clip['sourcePattern']%f)).exists() for f in range(clip['frames'])) for clip in data['clips'].values()) if not SCOUT30 else len(audit)
data['sampling'].update(renderedFrames=available,renderedThisJobFrames=len(audit),freshRenderedFrames=fresh,exactGeometryReusedFrames=reused)
if '--no-manifest-write' not in sys.argv: MANIFEST30.write_text(json.dumps(data,indent=2),encoding='utf-8')
tag=sys.argv[sys.argv.index('--report-tag')+1] if '--report-tag' in sys.argv else 'complete'
dest=STUDY30 if SCOUT30 else WORK30
dest.joinpath(f'flight-modules-v30-render-audit-{tag}.json').write_text(json.dumps({'frames':len(audit),'fresh':fresh,'reused':reused,'seconds':time.perf_counter()-begun,'poses':audit},indent=2),encoding='utf-8')
dest.joinpath(f'flight-modules-v30-cache-{tag}.json').write_text(json.dumps({'entries':cache}),encoding='utf-8')
print('V30_NATIVE_COMPLETE',len(audit),'frames',fresh,'fresh',reused,'exact repeats',flush=True)
