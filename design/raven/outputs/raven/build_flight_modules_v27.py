"""Independent, composable native 60fps steady soar and gentle swerve studies.

Blender --background --threads 6 --python build_flight_modules_v27.py -- --scout
Remove --scout to render all 840 native frames. --render-existing opens the
saved compact native animation instead of rebuilding it; --clips selects a
comma-separated subset. Earlier model, flight and chat assets stay immutable.
--reuse-cache accepts an exact evaluated-geometry cache to preserve previously
rendered identical pixels while rerendering only changed native edge poses.
"""
import bpy,math,json,sys,hashlib,struct,time,shutil
from pathlib import Path
from mathutils import Vector,Matrix
from bpy_extras.object_utils import world_to_camera_view

P=Path(__file__).resolve().parent
WORK=P.parents[1]/'work'
SCOUT='--scout' in sys.argv
STUDY=WORK/'flight-modules-v27-scout';STUDY.mkdir(parents=True,exist_ok=True)
DEST=(STUDY/'frames') if SCOUT else P/'flight-module-frames-v27';DEST.mkdir(exist_ok=True)
NATIVE=(STUDY if SCOUT else P)/'raven-flight-modules-v27.blend'
MANIFEST=(STUDY if SCOUT else P)/'flight-modules-v27.json'
DEFINITIONS={'steady_soar':(360,6),'swerve':(480,8)}
SCOUT_FRAMES={'steady_soar':[0,3,60,90,135,180,225,270,356,359],
              'swerve':[0,3,60,90,120,180,240,300,360,420,476,479]}

def quintic(x):
    x=max(0,min(1,x));return x*x*x*(10+x*(-15+6*x))

def quintic_derivative(x):
    return 30*x*x*(1-x)**2 if 0<x<1 else 0

def fingerprint():
    bpy.context.view_layer.update();graph=bpy.context.evaluated_depsgraph_get();digest=hashlib.sha256()
    digest.update(str((scene.cycles.samples,scene.cycles.seed,scene.cycles.use_animated_seed,scene.render.resolution_x,
                       scene.render.resolution_y,scene.view_settings.view_transform,scene.view_settings.look,
                       scene.view_settings.exposure,scene.view_settings.gamma)).encode())
    for obj in sorted(scene.objects,key=lambda obj:obj.name):
        if obj.type=='MESH' and not obj.hide_render:
            evaluated=obj.evaluated_get(graph);mesh=evaluated.to_mesh();digest.update(obj.name.encode())
            for vertex in mesh.vertices:digest.update(struct.pack('<3f',*(evaluated.matrix_world@vertex.co)))
            evaluated.to_mesh_clear()
        elif obj.type=='LIGHT':
            digest.update(obj.name.encode());digest.update(struct.pack('<16f',*(value for row in obj.matrix_world for value in row)))
            digest.update(str((obj.data.energy,obj.data.color[:],obj.data.size)).encode())
    digest.update(struct.pack('<16f',*(value for row in scene.camera.matrix_world for value in row)))
    digest.update(struct.pack('<f',scene.camera.data.ortho_scale))
    return digest.hexdigest()

if '--render-existing' not in sys.argv:
    source=(P/'build_chat_flight.py').read_text(encoding='utf-8').split('\nstart=1\nfor name,')[0]
    exec(compile(source,str(P/'build_chat_flight.py'),'exec'),globals())
    exec(compile((P/'flight_junction_v27.py').read_text(encoding='utf-8'),str(P/'flight_junction_v27.py'),'exec'),globals())
    # Frozen helpers define legacy output globals. Restore only this study's
    # own destinations after loading their live rig, before writing anything.
    SCOUT='--scout' in sys.argv
    DEST=(STUDY/'frames') if SCOUT else P/'flight-module-frames-v27';DEST.mkdir(exist_ok=True)
    NATIVE=(STUDY if SCOUT else P)/'raven-flight-modules-v27.blend'
    MANIFEST=(STUDY if SCOUT else P)/'flight-modules-v27.json'
    neutral_flight_junction();CANONICAL_HEADING=root.rotation_euler.z
    FIXED_CAMERA=(camera.location.copy(),camera.rotation_euler.copy(),camera.data.ortho_scale)

    def module_pose(name,f,count):
        global body_coordinates
        neutral_flight_junction()
        if f<=3 or f>=count-4:
            return {'x':0,'y':0},0,0,0
        duration=DEFINITIONS[name][1];seconds=f/60;u=f/(count-1)
        exit_start=duration-.85
        if name=='swerve':exit_start=(count-4)/60-.8
        enter=(seconds-.05)/.8;exit=(seconds-exit_start)/.8
        envelope=quintic(enter)*(1-quintic(exit))
        scan=envelope*math.sin(math.tau*2*u)
        wind=envelope*math.sin(math.tau*u)
        trim=envelope*math.sin(math.tau*3*u)
        heading_offset=0;bank=0
        if name=='swerve':
            course=math.tau*2*u
            # The heading follows the tangent of the lateral weave, while
            # inward bank grows with its curvature. All enter/exit derivatives
            # vanish through the same envelope used by the browser path.
            heading_offset=.75*envelope*math.cos(course)
            envelope_rate=(quintic_derivative(enter)/.8*(1-quintic(exit))-
                           quintic(enter)*quintic_derivative(exit)/.8)
            reference_turn_rate=math.tau*2/((count-1)/60)
            bank=.28*(envelope*math.sin(course)-
                      envelope_rate/reference_turn_rate*math.cos(course))
            motion={'x':.24*envelope*math.sin(course),
                    'y':-.038*envelope*math.sin(course)**2}
        else:
            motion={'x':0,'y':-.030*wind}
        root.rotation_euler=(Matrix.Rotation(CANONICAL_HEADING+heading_offset,4,'Z')@
                             Matrix.Rotation(bank,4,'X')).to_euler()
        torso.rotation_euler.y=.90+.012*wind
        head.rotation_euler=(Matrix.Rotation(-torso.rotation_euler.y,4,'Y')@
                             Matrix.Rotation(1.10+.20*scan*scan,4,'Y')@
                             Matrix.Rotation(-.50*scan,4,'Z')@
                             Matrix.Rotation(.045*scan,4,'X')).to_euler()
        tail.rotation_euler.y=-.515+.009*wind
        tail.rotation_euler.z=.010*trim
        for key,side in zip(wing_flexes,[-1,1]):
            key.value=.18*math.sin(side*.6)+.065*envelope*math.sin(math.tau*u+side*.6)
        distal=[]
        for side in [-1,1]:
            distal.append(Matrix.Rotation(side*(.24+.010*wind+side*.006*trim),3,'Z')@
                          Matrix.Rotation(side*.010*trim,3,'X'))
        shared_flight_wings(1,distal)
        for foot,side in zip(feet,[-1,1]):
            foot.location.z+=.008*envelope*math.sin(math.tau*u+side*.7)
            foot.rotation_euler.y+=.030*wind
        body_coordinates=shared_flight_body(1)
        shared_flight_legs(0)
        assert (root.location-LOCAL_ROOT).length<1e-7
        assert (camera.location-FIXED_CAMERA[0]).length<1e-7
        assert sum(abs(a-b) for row_a,row_b in zip(camera.rotation_euler.to_matrix(),FIXED_CAMERA[1].to_matrix()) for a,b in zip(row_a,row_b))<1e-7
        return motion,heading_offset,bank,scan

    def metadata(motion,heading_offset,bank,scan):
        bpy.context.view_layer.update()
        foot_points=[foot.matrix_world@Vector((.08,0,-.07)) for foot in feet]
        closed_tip=from_reference(464,184)
        tip=Vector((closed_tip[0]-bill_origin[0],0,closed_tip[1]-bill_origin[1]))
        result={'foot':screen(sum(foot_points,Vector())/2),
                'head':screen(head.matrix_world@Vector((.11,0,.22))),
                'beak':screen(upper.matrix_world@tip),'root':screen(LOCAL_ROOT),
                'orthoScale':camera.data.ortho_scale,'cawOpen':0,
                'motion':{key:round(value,9) for key,value in motion.items()},
                'headingOffset':round(heading_offset,9),'bank':round(bank,9),
                'scan':round(scan,9)}
        result['contact']=result['foot'].copy()
        return result

    def coordinates_hash(coords):
        return hashlib.sha256(b''.join(struct.pack('<3f',*point) for point in coords)).hexdigest()

    # Compact banks retain each unique deformation only once. Geometry keys
    # are switched at native frames, rather than storing redundant mutable
    # live rig keys for every logical frame or reusing lower-rate raster cells.
    banks={};usage={};records=[];expected_fingerprints={};start=1
    data={'version':27,'fps':60,'frameWidth':512,'frameHeight':512,
          'baseSourceSha256':prototype_base_sha256,
          'junction':{'id':'neutral-flight-v27','source':'v26 patrol phase0 with root bank removed before connected-leg evaluation',
                      'rootBank':0,'camera':'fixed','localRoot':list(LOCAL_ROOT),
                      'heading':CANONICAL_HEADING,'endpointHoldFrames':4},
          'composition':{'motionUnits':'fraction of full usable viewport width/height',
                         'spriteRoot':'fixed','endpointMotion':{'x':0,'y':0},
                         'randomizable':True,'compatibleJunction':'neutral-flight-v27'},
          'clips':{},'sampling':{'kind':'genuine continuous Blender pose evaluations','fps':60}}

    def bank_key(obj,coords,label,frame,value):
        digest=coordinates_hash(coords);key_id=(obj.name,digest)
        if key_id not in banks:
            key=obj.shape_key_add(name='v27 %s %04d'%(label,len(banks)))
            for vertex,co in zip(key.data,coords):vertex.co=co
            key.value=0;banks[key_id]=key;usage[key_id]={}
        usage[key_id][frame]=value
        return key_id

    for name,(count,duration) in DEFINITIONS.items():
        clip={'frames':count,'fps':60,'duration':duration,'loop':False,'startFrame':start,
              'entryJunction':'neutral-flight-v27','exitJunction':'neutral-flight-v27',
              'startJunction':'neutral-flight-v27','endJunction':'neutral-flight-v27',
              'sourcePattern':'flight-module-frames-v27/'+name+'-%04d.png','poses':[]}
        data['clips'][name]=clip;scene.timeline_markers.new('v27 '+name,frame=start)
        for f in range(count):
            frame=start+f;scene.frame_set(frame)
            motion,heading_offset,bank,scan=module_pose(name,f,count)
            current=[bank_key(body,body_coordinates,'neck',frame,1)]
            for owner,part,key in leg_paths:
                current.append(bank_key(part,[v.co.copy() for v in key.data],'connected-leg',frame,key.value));key.value=0
            for obj,key in wing_strokes:
                current.append(bank_key(obj,[v.co.copy() for v in key.data],'wing-collar',frame,key.value));key.value=0
            for key_id in current:banks[key_id].value=usage[key_id][frame]
            expected_fingerprints[(name,f)]=fingerprint()
            for key_id in current:banks[key_id].value=0
            for obj in animated:
                for prop in ['location','rotation_euler','scale']:obj.keyframe_insert(data_path=prop,frame=frame)
            for key in all_keys:key.keyframe_insert(data_path='value',frame=frame)
            clip['poses'].append(metadata(motion,heading_offset,bank,scan))
        print('FLIGHT_MODULE_V27_BAKE_CLIP',name,count,'native frames;',len(banks),'compact shapes',flush=True)
        start+=count+20
    for key_id,key in banks.items():
        values=usage[key_id]
        events={}
        for frame,value in values.items():
            if frame-1 not in values:events[frame-1]=0
            events[frame]=value
            if frame+1 not in values:events[frame+1]=0
        for frame,value in sorted(events.items()):
            key.value=value;key.keyframe_insert(data_path='value',frame=frame)
        key.value=0
    for owner,part,key in leg_paths:key.value=0
    for obj,key in wing_strokes:key.value=0
    scene.frame_start=1;scene.frame_end=start-20;scene.render.fps=60;scene.frame_set(1)
    scene['README']='v27 composable native60fps draft. Six-second steady soar has no sideways motion, gentle browser bob and continuous ground scan. Eight-second swerve uses tangent heading, inward bank, two swerves, mild rises away from the midpoint. Every module returns to the same four-frame neutralized acceptedv26 phase0 junction; root/camera fixed, browser motion metadata separate. Accepted v23 connected collar, angular wings, hanging breast, continuous hip/knee/ankle geometry retained. Compact exact deformation banks. No repeated8fps raster interpolation.'
    scene['Base source SHA256']=prototype_base_sha256
    data['sampling'].update(nativeFrames=sum(item[0] for item in DEFINITIONS.values()),compactGeometryShapes=len(banks))
    checked=0
    for name,(count,_) in DEFINITIONS.items():
        for f in range(count):
            scene.frame_set(data['clips'][name]['startFrame']+f)
            assert fingerprint()==expected_fingerprints[(name,f)],('Native/live geometry mismatch',name,f)
            checked+=1
        assert expected_fingerprints[(name,0)]==expected_fingerprints[(name,count-1)]
    assert expected_fingerprints[('steady_soar',0)]==expected_fingerprints[('swerve',0)]
    data['sampling']['liveGeometryMatchesNativeFrames']=checked
    scene.frame_set(1)
    bpy.ops.wm.save_as_mainfile(filepath=str(NATIVE))
    MANIFEST.write_text(json.dumps(data,indent=2),encoding='utf-8')
else:
    bpy.ops.wm.open_mainfile(filepath=str(NATIVE));scene=bpy.context.scene
    data=json.loads(MANIFEST.read_text(encoding='utf-8'))

cache={};rendered=0;reused=0;started=time.perf_counter();audit=[]
if '--reuse-cache' in sys.argv:
    cache_source=Path(sys.argv[sys.argv.index('--reuse-cache')+1])
    cache=json.loads(cache_source.read_text(encoding='utf-8'))['entries']
    assert all(Path(value).exists() for value in cache.values()),'Incomplete exact-raster reuse cache'
for name,(count,_) in DEFINITIONS.items():
    if '--clips' in sys.argv and name not in sys.argv[sys.argv.index('--clips')+1].split(','):continue
    indices=SCOUT_FRAMES[name] if SCOUT else range(count)
    for f in indices:
        scene.frame_set(data['clips'][name]['startFrame']+f);target=DEST/('%s-%04d.png'%(name,f));key=fingerprint()
        if key in cache:
            if Path(cache[key]).resolve()!=target.resolve():shutil.copyfile(cache[key],target)
            reused+=1;kind='EXACT_GEOMETRY_REUSE'
        else:
            scene.render.filepath=str(target);bpy.ops.render.render(write_still=True)
            cache[key]=str(target);rendered+=1;kind='FRESH_RENDER'
        audit.append({'clip':name,'frame':f,'fingerprint':key,'kind':kind})
        print('FLIGHT_MODULE_V27_RENDER',name,f,kind,flush=True)
    print('FLIGHT_MODULE_V27_CLIP_COMPLETE',name,flush=True)
report={'frames':len(audit),'freshRenderedFrames':rendered,'exactGeometryReusedFrames':reused,
        'seconds':time.perf_counter()-started,'backend':scene.cycles.device,'poses':audit}
(STUDY if SCOUT else WORK).joinpath('flight-modules-v27-render-audit.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
available_frames=sum(sum((P/clip['sourcePattern'].replace('%04d',f'{f:04d}')).exists() for f in range(clip['frames'])) for clip in data['clips'].values()) if not SCOUT else len(audit)
data['sampling'].update(renderedFrames=available_frames,availableRasterFrames=available_frames,
                        renderedThisJobFrames=len(audit),renderedFramesThisRun=len(audit),
                        freshRenderedFrames=rendered,exactGeometryReusedFrames=reused,
                        preservedRasterFrames=available_frames-len(audit),renderBackend=scene.cycles.device)
MANIFEST.write_text(json.dumps(data,indent=2),encoding='utf-8')
print('FLIGHT_MODULE_V27_COMPLETE',len(audit),'frames;',rendered,'fresh;',reused,'exact repeats',flush=True)
