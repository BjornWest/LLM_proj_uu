"""Genuine continuous native 60fps chat poses; 2.5-second takeoff and 4-second dive.
Blender --background --threads 6 --python build_chat_flight_v26.py [--scout-v26]
Dependencies: frozen build_chat_flight.py, flight_anatomy_v24.py,
build_takeoff_prototype.py and build_raven.py in this directory.
--render-existing reuses the saved native scene instead of rebuilding it.
--clips takeoff,patrol and --range patrol:0:797 select independent render jobs.
Use --report-tag worker-a for private provenance/statistics in parallel jobs.
The optional exact-pose cache is an optimization; --no-cache renders fresh.
"""
import bpy,math,json,sys,hashlib,struct,shutil,time
from pathlib import Path
from mathutils import Vector,Matrix
from bpy_extras.object_utils import world_to_camera_view
P=Path(__file__).resolve().parent
NEW_FPS=60;TAKEOFF_FRAMES=150;PATROL_FRAMES=1200;ROLL_FRAMES=300;DIVE_FRAMES=240
BRACE_THROUGH=38;LANDING_FRAME=168;DIVE_ENTRY=975;DIVE_PHASE=DIVE_ENTRY/PATROL_FRAMES
SCOUT='--scout-v26' in sys.argv
RENDER_EXISTING='--render-existing' in sys.argv
study=P.parents[1]/'work'/'chat-flight-v26-scout';study.mkdir(parents=True,exist_ok=True)
destination=(study/'frames') if SCOUT else P/'chat-flight-frames-v26';destination.mkdir(exist_ok=True)
native=(study if SCOUT else P)/'raven-chat-flight-v26.blend'
manifest=(study if SCOUT else P)/'chat-flight-v26.json'
if not RENDER_EXISTING:
    # Reuse the frozen live rig, never its quantized rendered 8fps frames. Replace
    # only the dive's entry phase in a private runtime copy; no v24 file is edited.
    v24_runtime=(P/'build_chat_flight.py').read_text(encoding='utf-8').split('\nstart=1\nfor name,')[0].replace('110/160','DIVE_PHASE')
    exec(compile(v24_runtime,str(P/'build_chat_flight.py'),'exec'),globals())
    v24_local_pose=local_pose
    SCOUT='--scout-v26' in sys.argv
    study=P.parents[1]/'work'/'chat-flight-v26-scout';study.mkdir(parents=True,exist_ok=True)
    destination=(study/'frames') if SCOUT else P/'chat-flight-frames-v26';destination.mkdir(exist_ok=True)
    path_point=None

    def capture_patrol_path(phase):
        pose('soaring',phase);bpy.context.view_layer.update()
        return screen(root.location)

    def roll_gesture(t):
        """Original roll articulation, independently clocked along the patrol."""
        if t<.40:angle=math.pi*smooth(t/.40)
        elif t<.58:angle=math.pi
        else:angle=math.pi+math.pi*smooth((t-.58)/.28)
        axis=Matrix.Rotation(.90,4,'Y')@Vector((.45,0,.79)).normalized()
        rotation=Matrix.Rotation(angle,4,axis);heading_matrix=root.rotation_euler.to_matrix().to_4x4()
        root.rotation_euler=(heading_matrix@rotation).to_euler()
        pivot=Vector((0,0,.12));root.location+=heading_matrix@(pivot-rotation@pivot)
        drift=math.sin(math.pi*t)**2;root.location+=heading_matrix@Vector((-.16*drift,0,.09*drift))
        tuck=smooth(t/.24)*(1-smooth((t-.82)/.18));hold=smooth((t-.36)/.04)*(1-smooth((t-.58)/.06));tuck*=1-.32*hold
        for wing,side in zip(wings,[-1,1]):
            dihedral=side*(.24+.18*tuck)
            folded=(Matrix.Rotation(.45,4,'Y')@Matrix.Rotation(dihedral,4,'Z')@Matrix.Rotation(-side*.12*tuck,4,'X')).to_quaternion()
            wing.rotation_euler=wing.rotation_euler.to_quaternion().slerp(folded,tuck).to_euler()
        for key in wing_roll_tucks:key.value=tuck
        for key in wing_flexes:key.value-=.26*tuck
        for foot in feet:foot.rotation_euler.y+=.25*tuck

    def local_pose(name,f,count):
        global body_coordinates,contact_point,native_root_delta,path_point
        path_point=None
        if name=='takeoff':
            # 150 genuine samples of the accepted 0..39 pose range over 2.5 seconds.
            v24_local_pose(name,39*f/(count-1),40)
        elif name in ['glide_right','glide']:
            v24_local_pose(name,0,1)
        elif name=='diving':
            # Accelerate the continuous landing to four seconds, with genuine
            # sixth-frame source phases and a final canonical perch hold.
            v24_local_pose(name,min(39,f/6),40)
        else:
            for owner,part,key in leg_paths:key.value=0
            for mesh,key in wing_strokes:key.value=0
            for key in grips:key.value=0
            contact_point=None;native_root_delta=Vector()
            phase=f/PATROL_FRAMES
            path_point=capture_patrol_path(phase)
            if name=='patrol':
                localize();tail.rotation_euler.y+=.055;inherited_wings('patrol',phase)
            elif name=='patrol_roll':
                base_location=root.location.copy();roll_gesture(f/(count-1));shift=root.location-base_location
                localize();root.location+=shift;tail.rotation_euler.y+=.055
                wind=math.sin(math.tau*phase*2);trim=math.sin(math.tau*phase*4)
                old_plane=1.35-torso.rotation_euler.y+.010*trim
                plane=old_plane+(.45-old_plane)*wing_roll_tucks[0].value
                distal=[Matrix.Rotation(-plane,3,'Y')@wing.rotation_euler.to_matrix() for wing in wings]
                shared_flight_wings(wing_spreads[0].value,distal)
            else:raise ValueError(name)
            body_coordinates=shared_flight_body(1);shared_flight_legs(phase)

    def metadata(name,f):
        bpy.context.view_layer.update();foot_points=[foot.matrix_world@Vector((.08,0,-.07)) for foot in feet]
        closed_tip=from_reference(464,184);tip=Vector((closed_tip[0]-bill_origin[0],0,closed_tip[1]-bill_origin[1]))
        result={'foot':screen(sum(foot_points,Vector())/2),'head':screen(head.matrix_world@Vector((.11,0,.22))),'beak':screen(upper.matrix_world@tip),'root':screen(LOCAL_ROOT),'orthoScale':camera.data.ortho_scale,'cawOpen':0}
        result['contact']=screen(contact_point) if contact_point is not None else result['foot'].copy()
        if path_point is not None:result['path']=path_point.copy()
        if name=='takeoff':result.update(grounded=f<=BRACE_THROUGH,nativeRootDelta=list(native_root_delta),sourcePhase=39*f/(TAKEOFF_FRAMES-1))
        if name=='diving':result.update(landed=f>=LANDING_FRAME,sourcePhase=min(39,f/6))
        return result

    definitions={'takeoff':(TAKEOFF_FRAMES,False),'glide_right':(1,True),'glide':(1,True),'patrol':(PATROL_FRAMES,True),'patrol_roll':(ROLL_FRAMES,False),'diving':(DIVE_FRAMES,False)}
    scout_frames={'takeoff':[0,23,37,38,39,69,148,149],'glide_right':[0],'glide':[0],'patrol':[0,1,2,600,601,975,1199],'patrol_roll':[0,1,75,135,210,298,299],'diving':[0,1,48,108,168,234,239]}
    data={'version':26,'frameWidth':512,'frameHeight':512,'columns':12,'fps':NEW_FPS,'baseSourceSha256':prototype_base_sha256,'clips':{},
          'timeline':{'replyMs':10000,'takeoffMs':2500,'braceThroughFrame':BRACE_THROUGH,'outsideMs':375,'enterMs':875,'patrolStartFrame':600,'diveStartPatrolFrame':DIVE_ENTRY,'diveMs':4000,'landingFrame':LANDING_FRAME},
          'anatomy':{'flightCompression':0,'wingPlaneAngle':SPINE_OPEN_ANGLE,'collarStrokeWeight':0,'bodyCorrection':'Frozen v23/v24 anatomy; continuous native pose sampling'},
          'sampling':{'fps':NEW_FPS,'takeoffSourceRange':[0,39],'takeoffSeconds':2.5,'patrolSeconds':20,'rollSeconds':5,'diveSeconds':4,'intermediatePoses':'Evaluated from continuous Blender rig functions, not repeated 8fps images'}}
    start=1
    for name,(count,loop) in definitions.items():
        clip={'frames':count,'fps':NEW_FPS,'loop':loop,'startFrame':start,'poses':[],'baseSourceSha256':prototype_base_sha256,'sourcePattern':'chat-flight-frames-v26/'+name+'-%04d.png'}
        if name=='diving':clip.update(entryFrame=DIVE_ENTRY,landingFrame=LANDING_FRAME)
        if name=='patrol_roll':clip.update(entryFrame=0,lastPatrolFrame=ROLL_FRAMES-1,resumePatrolFrame=ROLL_FRAMES)
        data['clips'][name]=clip;scene.timeline_markers.new('60fps '+name,frame=start);previous=None
        for f in range(count):
            frame=start+f;scene.frame_set(frame);local_pose(name,f,count)
            if previous is not None:root.rotation_euler=root.rotation_euler.to_matrix().to_euler('XYZ',previous)
            previous=root.rotation_euler.copy();shape=body.shape_key_add(name='60fps %s %04d'%(name,f))
            for vertex,co in zip(shape.data,body_coordinates):vertex.co=co
            for at,value in [(frame-1,0),(frame,1),(frame+1,0)]:shape.value=value;shape.keyframe_insert(data_path='value',frame=at)
            for owner,part,key in leg_paths:
                baked=part.shape_key_add(name='60fps %s brace %04d'%(name,f))
                for vertex,co in zip(baked.data,key.data):vertex.co=co.co
                for at,value in [(frame-1,0),(frame,key.value),(frame+1,0)]:baked.value=value;baked.keyframe_insert(data_path='value',frame=at)
                key.value=0
            for mesh,key in wing_strokes:
                baked=mesh.shape_key_add(name='60fps %s collar %04d'%(name,f))
                for vertex,co in zip(baked.data,key.data):vertex.co=co.co
                for at,value in [(frame-1,0),(frame,key.value),(frame+1,0)]:baked.value=value;baked.keyframe_insert(data_path='value',frame=at)
                key.value=0
            for obj in animated:
                for prop in ['location','rotation_euler','scale']:obj.keyframe_insert(data_path=prop,frame=frame)
            for key in all_keys:key.keyframe_insert(data_path='value',frame=frame)
            for prop in ['location','rotation_euler']:camera.keyframe_insert(data_path=prop,frame=frame)
            camera.data.keyframe_insert(data_path='ortho_scale',frame=frame);clip['poses'].append(metadata(name,f))
        start+=count+30
    scene.frame_start=1;scene.frame_end=start-30;scene.render.fps=NEW_FPS;scene.frame_set(1)
    scene['README']='v26 true 60fps native flight using frozen v23/v24 anatomy. 2.5-second 150-frame grounded takeoff, 20-second 1200-frame continuous patrol, five-second 300-frame roll, four-second 240-frame dive. Every in-between body, wing collar, legs, camera and transform is baked. Patrol scans/banks/path use a continuous 20s clock; roll gesture uses its separate 5s clock and ends at patrol299. Reply10s enters dive from exact patrol975. Ground contact held0–38, release39; touchdown168 at2.8s. Canonical perch hold234–239. No interpolation of raster images.'
    scene['Base source SHA256']=prototype_base_sha256
    native=(study if SCOUT else P)/'raven-chat-flight-v26.blend';bpy.ops.wm.save_as_mainfile(filepath=str(native))
    manifest=(study if SCOUT else P)/'chat-flight-v26.json';manifest.write_text(json.dumps(data,indent=2),encoding='utf-8')
else:
    bpy.ops.wm.open_mainfile(filepath=str(native));scene=bpy.context.scene
    data=json.loads(manifest.read_text(encoding='utf-8'))
    prototype_base_sha256=data['baseSourceSha256']
    definitions={name:(clip['frames'],clip['loop']) for name,clip in data['clips'].items()}
    scout_frames={'takeoff':[0,23,37,38,39,69,148,149],'glide_right':[0],'glide':[0],'patrol':[0,1,2,600,601,975,1199],'patrol_roll':[0,1,75,135,210,298,299],'diving':[0,1,48,108,168,234,239]}
cache_path=P.parents[1]/'work/flight-v26-exact-cache.json';cache={}
if cache_path.exists() and '--no-cache' not in sys.argv:
    candidate=json.loads(cache_path.read_text())
    if candidate['baseSourceSha256']==prototype_base_sha256:cache=candidate['entries']

def fingerprint():
    bpy.context.view_layer.update();graph=bpy.context.evaluated_depsgraph_get();digest=hashlib.sha256()
    digest.update(str((scene.cycles.samples,scene.cycles.seed,scene.cycles.use_animated_seed,scene.render.resolution_x,scene.render.resolution_y,scene.view_settings.view_transform,scene.view_settings.look,scene.view_settings.exposure,scene.view_settings.gamma)).encode())
    for obj in sorted(scene.objects,key=lambda obj:obj.name):
        if obj.type=='MESH' and not obj.hide_render:
            ev=obj.evaluated_get(graph);mesh=ev.to_mesh();digest.update(obj.name.encode())
            for vertex in mesh.vertices:digest.update(struct.pack('<3f',*(ev.matrix_world@vertex.co)))
            ev.to_mesh_clear()
        elif obj.type=='LIGHT':
            digest.update(obj.name.encode());digest.update(struct.pack('<16f',*(value for row in obj.matrix_world for value in row)));digest.update(str((obj.data.energy,obj.data.color[:],obj.data.size)).encode())
    digest.update(struct.pack('<16f',*(value for row in scene.camera.matrix_world for value in row)));digest.update(struct.pack('<f',scene.camera.data.ortho_scale))
    return digest.hexdigest()

plan_started=time.perf_counter();plan_file=(study if SCOUT else P.parents[1]/'work')/'chat-flight-v26-render-plan.json'
native_sha=hashlib.sha256(native.read_bytes()).hexdigest();prior_plan=None
if RENDER_EXISTING and plan_file.exists():
    candidate=json.loads(plan_file.read_text(encoding='utf-8'))
    if candidate.get('nativeSha256')==native_sha and candidate['baseSourceSha256']==prototype_base_sha256:prior_plan=candidate
plan=[];known=set(cache);fresh_unique=0;cached_frames=0
if prior_plan:
    plan=prior_plan['poses']
    for item in plan:
        key=item['fingerprint'];available=key in known;item['cacheAvailable']=available
        if available:cached_frames+=1
        else:fresh_unique+=1;known.add(key)
else:
    for name,(count,_) in definitions.items():
        for f in range(count):
            scene.frame_set(data['clips'][name]['startFrame']+f);key=fingerprint();available=key in known
            if available:cached_frames+=1
            else:fresh_unique+=1;known.add(key)
            plan.append({'clip':name,'frame':f,'fingerprint':key,'cacheAvailable':available})
        print('CHAT_FLIGHT_V26_PLAN_CLIP',name,count,'poses;',round(time.perf_counter()-plan_started,2),'seconds',flush=True)
plan_lookup={(item['clip'],item['frame']):item['fingerprint'] for item in plan}
plan_result={'fps':NEW_FPS,'frames':len(plan),'freshUniquePoses':fresh_unique,'cachedOrIdenticalPoses':cached_frames,'fingerprintSeconds':time.perf_counter()-plan_started,'baseSourceSha256':prototype_base_sha256,'nativeSha256':native_sha,'poses':plan}
# Workers never mutate the shared plan or logical manifest.
report_tag=sys.argv[sys.argv.index('--report-tag')+1] if '--report-tag' in sys.argv else None
if report_tag:assert all(c.isalnum() or c in '-_' for c in report_tag)
if not report_tag:plan_file.write_text(json.dumps(plan_result,indent=2),encoding='utf-8')
print('CHAT_FLIGHT_V26_RENDER_PLAN',len(plan),'poses;',fresh_unique,'fresh unique;',cached_frames,'exact cached/identical;',round(plan_result['fingerprintSeconds'],2),'seconds',flush=True)
if '--plan-only' in sys.argv:sys.exit(0)
if '--persistent' in sys.argv:scene.render.use_persistent_data=True
clip_range=None
if '--range' in sys.argv:
    range_clip,range_start,range_end=sys.argv[sys.argv.index('--range')+1].split(':');clip_range=(range_clip,int(range_start),int(range_end))
render_started=time.perf_counter()
rendered=0;reused=0;render_audit=[]
for name,(count,_) in definitions.items():
    indices=scout_frames[name] if SCOUT else list(range(count))
    if clip_range and clip_range[0]==name:indices=[f for f in indices if clip_range[1]<=f<clip_range[2]]
    if '--clips' in sys.argv and name not in sys.argv[sys.argv.index('--clips')+1].split(','):continue
    clip_started=time.perf_counter();clip_fresh=rendered;clip_reused=reused
    for f in indices:
        scene.frame_set(data['clips'][name]['startFrame']+f);target=destination/('%s-%04d.png'%(name,f));key=plan_lookup[(name,f)];cached=cache.get(key)
        if cached and Path(cached).exists():
            shutil.copyfile(cached,target);reused+=1;kind='EXACT_CACHE'
        else:
            scene.render.filepath=str(target);bpy.ops.render.render(write_still=True);rendered+=1;kind='FRESH_RENDER'
        cache[key]=str(target);render_audit.append({'clip':name,'frame':f,'fingerprint':key,'kind':kind,'source':cached if kind=='EXACT_CACHE' else None})
        print('CHAT_FLIGHT_V26',name,f,kind,flush=True)
    print('CHAT_FLIGHT_V26_CLIP_COMPLETE',name,rendered-clip_fresh,'fresh;',reused-clip_reused,'exact reused;',round(time.perf_counter()-clip_started,2),'seconds',flush=True)
stats={'freshRenderedFrames':rendered,'exactGeometryCachedFrames':reused,'renderSeconds':time.perf_counter()-render_started,'renderBackend':scene.cycles.device,'persistentData':scene.render.use_persistent_data}
if not report_tag:
    data['sampling'].update(stats);manifest.write_text(json.dumps(data,indent=2),encoding='utf-8')
report_folder=study if SCOUT else P.parents[1]/'work'
suffix='-'+report_tag if report_tag else ''
(report_folder/('chat-flight-v26-render-audit'+suffix+'.json')).write_text(json.dumps(render_audit,indent=2),encoding='utf-8')
(report_folder/('chat-flight-v26-render-stats'+suffix+'.json')).write_text(json.dumps(stats,indent=2),encoding='utf-8')
print('CHAT_FLIGHT_V26_RENDER_COMPLETE',rendered,'fresh native renders;',reused,'exact geometry/camera matches',flush=True)
