"""Native 60 fps v26 perch/idle/pet/hopping-caw, preserving older assets.

Blender --background --threads 6 --python build_chat_perch_v26.py
Use -- --scout for inspected poses plus an exact-state render estimate.
--timeline-only saves the complete native timeline without rendering.
Dependencies: the approved build_chat_perch.py rig and build_raven.py.
If the verified v25 Blend/metadata/PNGs are present, only exact evaluated
geometry + camera/material/light/render-setting matches may reuse pixels.
Otherwise every missing state renders natively. Editable shape keys are
deduplicated by exact local coordinates, never by animation frame rate.
"""
import bpy, math, json, sys, argparse, shutil, importlib.util, hashlib, struct
from pathlib import Path
from mathutils import Vector

P=Path(__file__).resolve().parent
WORK=P.parent.parent/'work'
FPS=60;LEGACY_SCALE=FPS/8
BASE_SHA='4fa42b8172433fea1bf31ff4a3eb0d5da08126ff2d62c750055b2ad77670f42b'
CLIP_DEFS={'perch':(1,True),'idle':(1500,True),'pet':(240,False),'caw':(1080,True)}
INSPECTION={'perch':[0],'idle':[0,185,186,187,188,195,278,279,280,281,282,300,600,900,1200,1498,1499],
            'pet':[0,15,16,17,18,19,20,60,105,157,238,239],
            'caw':[0,8,9,10,11,12,30,187,195,196,197,198,199,200,210,224,225,270,300,540,570,840,1079]}
HOP_HEIGHT=[0,-.14,.018,.30,.42,.30,.018,-.09,-.045,0,0,0]
HOP_PROGRESS=[0,0,0,.18,.50,.82,1,1,1,1,1,1]
HOP_LEAN=[0,.065,0,0,0,0,0,.025,0,0,0,0]
HOP_LABELS=['Brace','Crouch','Push','Hop rise','Hop apex','Hop fall','Touch down',
            'Land crouch','Recover','Settled','Settled','Settled']

def geometry_digest():
    depsgraph=bpy.context.evaluated_depsgraph_get();digest=hashlib.sha256()
    for obj in sorted((o for o in bpy.context.scene.objects if o.type=='MESH' and not o.hide_render),key=lambda o:o.name):
        digest.update(obj.name.encode('utf-8')+b'\0')
        values=[float(v) if v else 0.0 for row in obj.matrix_world for v in row]
        evaluated=obj.evaluated_get(depsgraph);mesh=evaluated.to_mesh()
        try:values.extend(float(v) if v else 0.0 for vertex in mesh.vertices for v in vertex.co)
        finally:evaluated.to_mesh_clear()
        digest.update(struct.pack('<'+str(len(values))+'d',*values))
    return digest.hexdigest()

def plain(value):
    if isinstance(value,(str,bool,int,float)):return value
    try:return [float(v) for v in value]
    except TypeError:return str(value)

def node_signature(tree):
    if not tree:return None
    return {'nodes':[{'name':n.name,'type':n.bl_idname,
                     'inputs':[(s.name,plain(s.default_value)) for s in n.inputs if hasattr(s,'default_value')]}
                    for n in sorted(tree.nodes,key=lambda n:n.name)],
            'links':sorted((l.from_node.name,l.from_socket.name,l.to_node.name,l.to_socket.name) for l in tree.links)}

def render_provenance():
    s=bpy.context.scene;c=s.camera
    assert not s.cycles.use_animated_seed,'Animated sampling seeds prohibit cross-frame cache reuse'
    assert not getattr(s.render,'use_motion_blur',False),'Motion blur prohibits pose-only cache reuse'
    used_materials={m.name:m for o in s.objects if o.type=='MESH' and not o.hide_render for m in o.data.materials if m}
    result={'blenderVersion':list(bpy.app.version),'blenderBuild':bpy.app.build_hash.decode(),
            'engine':s.render.engine,'resolution':[s.render.resolution_x,s.render.resolution_y,s.render.resolution_percentage],
            'filmTransparent':s.render.film_transparent,'dither':s.render.dither_intensity,
            'border':[s.render.use_border,s.render.use_crop_to_border,s.render.border_min_x,s.render.border_max_x,s.render.border_min_y,s.render.border_max_y],
            'image':[s.render.image_settings.file_format,s.render.image_settings.color_mode,s.render.image_settings.color_depth],
            'view':[s.view_settings.view_transform,s.view_settings.look,s.view_settings.exposure,s.view_settings.gamma,s.display_settings.display_device],
            'cycles':{k:plain(getattr(s.cycles,k)) for k in ['samples','use_denoising','denoiser','seed','use_animated_seed','use_adaptive_sampling','adaptive_threshold','adaptive_min_samples','device']},
            'threads':[s.render.threads_mode,s.render.threads],
            'camera':{'matrix':[list(row) for row in c.matrix_world],'type':c.data.type,'orthoScale':c.data.ortho_scale,
                      'lens':c.data.lens,'shift':[c.data.shift_x,c.data.shift_y],'clip':[c.data.clip_start,c.data.clip_end],
                      'dof':[c.data.dof.use_dof,c.data.dof.aperture_fstop]},
            'materials':{name:{'diffuse':list(m.diffuse_color),'nodes':node_signature(m.node_tree)} for name,m in sorted(used_materials.items())},
            'topology':{o.name:{'materials':[m.name if m else None for m in o.data.materials],
                                  'faces':[(list(f.vertices),f.material_index,f.use_smooth) for f in o.data.polygons]}
                        for o in sorted((o for o in s.objects if o.type=='MESH' and not o.hide_render),key=lambda o:o.name)},
            'lights':[{'name':o.name,'type':o.data.type,'energy':o.data.energy,'color':list(o.data.color),
                       'size':getattr(o.data,'size',None),'shape':getattr(o.data,'shape',None),'matrix':[list(row) for row in o.matrix_world]}
                      for o in sorted((o for o in s.objects if o.type=='LIGHT' and not o.hide_render),key=lambda o:o.name)],
            'world':node_signature(s.world.node_tree),
            'compositor':node_signature(getattr(s,'compositing_node_group',getattr(s,'node_tree',None)))}
    return result,hashlib.sha256(json.dumps(result,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def verified_v25_seed():
    path=P/'raven-chat-perch-v25.blend';metadata_path=P/'chat-perch-v25.json'
    if not path.exists() or not metadata_path.exists():return {},None,None
    bpy.ops.wm.open_mainfile(filepath=str(path));s=bpy.context.scene
    m=json.loads(metadata_path.read_text(encoding='utf-8'))
    assert m['baseSourceSha256']==s['Base source SHA256']==BASE_SHA and s.render.fps==24
    s.frame_set(1);bpy.context.view_layer.update();provenance,sha=render_provenance();cache={}
    for item in m['clips'].values():
        for index in range(item['frames']):
            s.frame_set(item['startFrame']+index);bpy.context.view_layer.update();key=geometry_digest()
            image=P/(item['sourcePattern']%index)
            if image.exists() and key not in cache:
                cache[key]={'path':str(image),'pngSha256':hashlib.sha256(image.read_bytes()).hexdigest(),'origin':'v25'}
    print('V26_VERIFIED_V25_SEED',len(cache),'native evaluated states',flush=True)
    bpy.ops.wm.read_factory_settings(use_empty=False)
    return cache,provenance,sha

def monotone_pose(values,x):
    x=max(0,min(len(values)-1,float(x)));i=min(int(x),len(values)-2);t=x-i
    diffs=[b-a for a,b in zip(values,values[1:])];slopes=[0.0]
    for a,b in zip(diffs,diffs[1:]):slopes.append(2*a*b/(a+b) if a*b>0 else 0.0)
    slopes.append(0.0)
    return ((2*t**3-3*t*t+1)*values[i]+(t**3-2*t*t+t)*slopes[i]
            +(-2*t**3+3*t*t)*values[i+1]+(t**3-t*t)*slopes[i+1])

def apply_caw(index):
    rig.reset_pose(0);section=index//270;phase=index%270
    heading=rig.CHAT_ANGLES[section];amount=0;height=0;lean=0;progress=0
    hopping=phase>=180;airborne=False;step=None;label=rig.CAW_LABELS[section]
    if not hopping:amount=monotone_pose(rig.CALL,phase/LEGACY_SCALE)
    else:
        step=(phase-180)/LEGACY_SCALE;height=monotone_pose(HOP_HEIGHT,step)
        progress=monotone_pose(HOP_PROGRESS,step);lean=monotone_pose(HOP_LEAN,step)
        heading=heading*(1-progress)+rig.CHAT_ANGLES[(section+1)%4]*progress
        label=HOP_LABELS[min(int(step),11)];airborne=2<step<6
    rig.root.rotation_euler.z=heading;rig.root.location.z=1.3+height
    rig.head.rotation_euler.z=0;rig.head.rotation_euler.y=-.055*amount-lean*.45
    rig.closed_bill.value=1-amount;rig.bill.rotation_euler.y=.055*amount
    rig.torso.scale.z=1+.004*amount;rig.torso.rotation_euler.y=lean
    for leg,foot in zip(rig.legs,rig.feet):
        if not airborne:ankle=rig.REST_ANKLE-Vector((0,0,height));curl=0
        else:
            release=rig.REST_ANKLE-Vector((0,0,.018));tucked=rig.REST_ANKLE+Vector((-.055,0,.025))
            weight=rig.smooth(step-2) if step<3 else 1-rig.smooth(step-5) if step>5 else 1
            ankle=release.lerp(tucked,weight);curl=.22*weight
        knee=rig.knee_for_ankle(ankle);foot.location=ankle;foot.rotation_euler.y=curl
        for owner,part,key,prefix in rig.leg_paths:
            if owner==leg:rig.leg_shape(key,prefix,knee,ankle);key.value=1 if height!=0 or airborne else 0
    for vertex,co in zip(rig.live_neck.data,rig.neck_coordinates()):vertex.co=co
    rig.live_neck.value=1;bpy.context.view_layer.update()
    return {'cawOpen':amount,'label':label,'hopping':hopping,'airborne':airborne,
            'hopStep':None if step is None else phase-180,'legacyHopStep':step,
            'hopPhase':None if step is None else (phase-180)/90,
            'turnProgress':progress,'eyeClosure':0,'neckStretch':0}

def apply_pose(clip,index):
    if clip=='caw':return apply_caw(index)
    return rig.apply_pose(clip,200 if clip=='idle' and index==1499 else index/LEGACY_SCALE)

def compact_shape(obj,target,frame,label,bank):
    coords=tuple(float(v) for point in target for v in point.co)
    key=bank['poses'].get(coords)
    if key is None:
        key=obj.shape_key_add(name=f'Native60 {label} {len(bank["poses"]):04d}')
        for vertex,point in zip(key.data,target):vertex.co=point.co
        key.value=0;key.keyframe_insert(data_path='value',frame=0);bank['poses'][coords]=key
    previous=bank['active']
    if previous!=key:
        if previous:previous.value=0;previous.keyframe_insert(data_path='value',frame=frame)
        key.value=1;key.keyframe_insert(data_path='value',frame=frame);bank['active']=key
    else:key.value=1
    return key.name

def bake_timeline(metadata,path=None):
    body_bank={'poses':{},'active':None};leg_banks={part.name:{'poses':{},'active':None} for owner,part,key,prefix in rig.leg_paths}
    frame=0
    for clip,item in metadata['clips'].items():
        scene.timeline_markers.new(clip,frame=item['startFrame'])
        for index in range(item['frames']):
            frame+=1;scene.frame_set(frame);apply_pose(clip,index)
            name=compact_shape(rig.body,rig.live_neck.data,frame,'neck',body_bank);rig.live_neck.value=0
            item['poses'][index]['nativeNeckShape']=name;leg_keys={}
            for owner,part,key,prefix in rig.leg_paths:
                target=key.data if key.value else part.data.shape_keys.key_blocks['Basis'].data
                leg_keys[part.name]=compact_shape(part,target,frame,'leg',leg_banks[part.name]);key.value=0
            item['poses'][index]['nativeLegShapes']=leg_keys
            for obj in [*rig.animated,*rig.sockets,*rig.lids]:
                for prop in ['location','rotation_euler','scale']:obj.keyframe_insert(data_path=prop,frame=frame)
            for key in [rig.closed_bill,*rig.grips,*rig.wing_spreads,*rig.wing_flexes,*rig.wing_roll_tucks,*rig.leg_tucks,*rig.leg_swings]:key.keyframe_insert(data_path='value',frame=frame)
    rig.body.shape_key_remove(rig.live_neck)
    for owner,part,key,prefix in rig.leg_paths:part.shape_key_remove(key)
    for datablock in [*bpy.data.objects,*[o.data.shape_keys for o in scene.objects if o.type=='MESH' and o.data.shape_keys]]:
        animation=getattr(datablock,'animation_data',None)
        if not animation or not animation.action:continue
        for layer in animation.action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        for point in curve.keyframe_points:point.interpolation='CONSTANT'
    scene.frame_start=1;scene.frame_end=frame;scene.render.fps=FPS;scene.frame_set(1);scene.camera=rig.camera
    scene['README']='v26 native60fps: approved geometry, fixed camera, native gripping claws and continuous fractional-time idle/blink/pet/caw/hop evaluation. Shape bank deduplicates exact local geometry while transforms retain every60fps sample. Exact-render cache requires evaluated meshes, world matrices, topology, materials, camera, lights and render provenance to match.'
    scene['Base source SHA256']=BASE_SHA;scene['Temporal evaluation FPS']=FPS
    scene['Render provenance SHA256']=metadata['renderProvenanceSha256']
    for area in bpy.context.screen.areas:
        if area.type=='VIEW_3D':
            area.spaces.active.region_3d.view_perspective='CAMERA';area.spaces.active.camera=rig.camera
            area.spaces.active.shading.type='MATERIAL';area.spaces.active.overlay.show_overlays=False
    metadata['nativeShapeBanks']={'neck':len(body_bank['poses']),'legs':{name:len(bank['poses']) for name,bank in leg_banks.items()}}
    bpy.ops.wm.save_as_mainfile(filepath=str(path or P/'raven-chat-perch-v26.blend'))
    print('V26_NATIVE_BAKE_COMPLETE',frame,metadata['nativeShapeBanks'],flush=True)

def main():
    global rig,scene
    parser=argparse.ArgumentParser();parser.add_argument('--scout',action='store_true');parser.add_argument('--timeline-only',action='store_true');parser.add_argument('--bake-native',action='store_true')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    seed,old_provenance,old_sha=verified_v25_seed()
    spec=importlib.util.spec_from_file_location('approved_chat_perch_v24',P/'build_chat_perch.py')
    rig=importlib.util.module_from_spec(spec);spec.loader.exec_module(rig)
    assert rig.CHAT_BASE_SHA==BASE_SHA
    scene=rig.scene;scene.render.fps=FPS;scene.render.threads_mode='FIXED';scene.render.threads=6
    rig.apply_pose('perch',0);provenance,provenance_sha=render_provenance()
    if old_sha!=provenance_sha:
        print('V26_SEED_DISABLED: rendering provenance differs',old_sha,provenance_sha,flush=True);seed={}
    cache=seed.copy();seed_states=len(seed);receipt_path=WORK/'chat-perch-cache-v26.json'
    if receipt_path.exists():
        receipts=json.loads(receipt_path.read_text(encoding='utf-8'))
        if receipts.get('baseSourceSha256')==BASE_SHA and receipts.get('renderProvenanceSha256')==provenance_sha:
            for key,value in receipts['states'].items():
                path=Path(value['path'])
                if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()==value['pngSha256']:cache.setdefault(key,value)
    destination=P/'chat-perch-frames-v26';destination.mkdir(exist_ok=True)
    metadata={'version':26,'baseSourceSha256':BASE_SHA,'frameWidth':512,'frameHeight':512,'columns':8,'fps':FPS,
              'temporalEvaluation':'Native continuous pose evaluation at60fps. Only exact evaluated-state and render-provenance matches reuse pixels; new intermediate states are rendered natively.',
              'renderProvenanceSha256':provenance_sha,'verifiedV25SeedStates':seed_states,
              'defaultHeading':rig.CHAT_HEADING,'perchHeading':rig.CHAT_HEADING,'startHeading':rig.CHAT_HEADING,'frontHeading':rig.CHAT_FRONT,
              'camera':{'location':list(rig.CHAT_CAMERA[0]),'rotation':list(rig.CHAT_CAMERA[1]),'orthoScale':3.75},
              'contactDescription':'Native grip anchor foot-local (.08,0,-.07). contact is the virtual grounded anchor at current heading excluding hop height; anchor contact to Send, retaining airborne foot motion.',
              'dependencies':['build_chat_perch.py','build_raven.py'],'clips':{}}
    fresh=0;reused_v25=0;reused_v26=0;seen=set();missing=set();frame=0
    for clip,(count,loop) in CLIP_DEFS.items():
        item={'frames':count,'fps':FPS,'loop':loop,'duration':count/FPS,'startFrame':frame+1,'poses':[],
              'inspection':[{'frame':f,'label':clip+' '+str(f)} for f in INSPECTION[clip]],
              'sourcePattern':'chat-perch-frames-v26/'+clip+'-%04d.png'}
        if clip=='idle':item.update(pauseSeconds=[4.5,9.5,14.5,19.5,24.5],pauseFrames=[270,570,870,1170,1470])
        if clip=='caw':
            item['sections']=[{'start':i*270,'callFrames':180,'hopFrames':90,'heading':a,'label':rig.CAW_LABELS[i]} for i,a in enumerate(rig.CHAT_ANGLES)]
            item['startHeading']=rig.CHAT_HEADING;item['frontHeading']=rig.CHAT_FRONT
        for index in range(count):
            frame+=1;scene.frame_set(frame);info=apply_pose(clip,index);pose=rig.pose_metadata(info)
            key=geometry_digest();pose['evaluatedGeometrySha256']=key;item['poses'].append(pose);seen.add(key)
            if key not in seed:missing.add(key)
            if not args.timeline_only and (not args.scout or index in INSPECTION[clip]):
                path=destination/f'{clip}-{index:04d}.png';cached=cache.get(key)
                if cached:
                    source=Path(cached['path'])
                    assert hashlib.sha256(source.read_bytes()).hexdigest()==cached['pngSha256']
                    if path.resolve()!=source.resolve():shutil.copyfile(source,path)
                    if cached['origin']=='v25':reused_v25+=1
                    else:reused_v26+=1
                else:
                    scene.render.filepath=str(path);bpy.ops.render.render(write_still=True);fresh+=1
                    cache[key]={'path':str(path),'pngSha256':hashlib.sha256(path.read_bytes()).hexdigest(),'origin':'v26'}
                print('CHAT_PERCH_V26',clip,index+1,'/',count,flush=True)
        metadata['clips'][clip]=item;print('CHAT_PERCH_V26_CLIP_COMPLETE',clip,count,flush=True)
    metadata.update(evaluatedUniquePoses=len(seen),estimatedNewUniquePoses=len(missing),freshNativeRenders=fresh,
                    renderedUniquePoses=len(seen),reusedVerifiedV25Cells=reused_v25,reusedVerifiedV26Cells=reused_v26)
    WORK.mkdir(exist_ok=True)
    receipt_path.write_text(json.dumps({'baseSourceSha256':BASE_SHA,'renderProvenanceSha256':provenance_sha,'states':cache},indent=2),encoding='utf-8')
    (WORK/'chat-perch-provenance-v26.json').write_text(json.dumps(provenance,indent=2),encoding='utf-8')
    if not args.scout:
        bake_timeline(metadata);(P/'chat-perch-v26.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    else:
        if args.bake_native:bake_timeline(metadata,WORK/'raven-chat-perch-scout-v26.blend')
        (WORK/'chat-perch-scout-v26.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    print('CHAT_PERCH_V26_COMPLETE',frame,'logicalframes;',len(seen),'evaluated unique states;',fresh,'fresh renders;',reused_v25,'verifiedv25cells;',reused_v26,'verifiedv26cells; estimated missing unique',len(missing),flush=True)

if __name__=='__main__':main()
