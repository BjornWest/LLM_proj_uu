"""Native v24 Send-button rig: idle, petting and whole-body hopping caw.

Blender --background --threads 2 --python build_chat_perch.py
Pass -- --scout to render the inspection poses; --timeline-only saves the
complete editable timeline and normalized anchors without rendering PNGs.
This module also supplies the exact same rig to build_chat_attention.py.
"""
import bpy, math, json, hashlib, sys, argparse, shutil
from pathlib import Path
from mathutils import Vector, Matrix
from bpy_extras.object_utils import world_to_camera_view

P=Path(__file__).resolve().parent
chat_base_source=(P/'build_raven.py').read_text(encoding='utf-8').split("manifest={'frameWidth'")[0]
CHAT_BASE_SHA=hashlib.sha256(chat_base_source.encode('utf-8')).hexdigest()
exec(compile(chat_base_source,str(P/'build_raven.py'),'exec'),globals())
scene.render.resolution_x=scene.render.resolution_y=512
scene.render.fps=8;scene.cycles.samples=16
scene.render.threads_mode='FIXED';scene.render.threads=2
set_palette(False)
pose('idle',0)
CHAT_CAMERA=(camera.location.copy(),camera.rotation_euler.copy(),3.75)
CHAT_ROOT_BASE=root.location.copy()
CHAT_HEADING=root.rotation_euler.z
CHAT_FRONT=math.atan2(camera.location.y,camera.location.x+.03)
CHAT_ANGLES=[CHAT_HEADING,CHAT_FRONT,2*CHAT_FRONT-CHAT_HEADING,CHAT_FRONT]
CHAT_CONTACT_LOCAL=Vector((.08,0,-.07))
CHAT_CONTACT_ROOT=sum((leg.location+base[foot.name][0]+CHAT_CONTACT_LOCAL for leg,foot in zip(legs,feet)),Vector())/2

# Native toe-tip curling; no composited toe patches. Keep the ankle and toe
# roots unchanged and let the tips wrap just below the blue button edge.
grips=[]
for part in bpy.data.objects:
    if part.type!='MESH' or not part.name.startswith(('Curved toe','Hooked claw','Curved rear toe')):continue
    if not part.data.shape_keys:part.shape_key_add(name='Basis')
    grip=part.shape_key_add(name='Button edge grip')
    for vertex,original in zip(grip.data,part.data.vertices):
        p=original.co.copy()
        if part.name.startswith('Curved rear toe'):
            curl=smooth((.15-p.x)/.22);p.z-=.028*curl
        else:
            curl=smooth((p.x-.33)/.21);p.z-=.042*curl;p.x-=.015*curl
        vertex.co=p
    grip.value=1;grips.append(grip)

sockets=[bpy.data.objects['Eye socket '+str(side)] for side in [-1,1]]
lids=[eye_patch('Soft closed eyelid '+str(side),side,.034,.0022,black,.0075) for side in [-1,1]]
for lid in lids:lid.scale=(0,0,0)
HEAD_PIVOT=base[head.name][0].copy()
live_neck=body.shape_key_add(name='Live native chat neck')
leg_paths=[]
HIP=Vector((-.12,0,.85));REST_KNEE=Vector((-.10,0,.55));REST_ANKLE=Vector((.27,0,.15))
UPPER_LENGTH=(REST_KNEE-HIP).length;LOWER_LENGTH=(REST_ANKLE-REST_KNEE).length
for leg in legs:
    for prefix in ['Feathered thigh','Continuous ankle']:
        part=next(o for o in leg.children if o.name.startswith(prefix))
        key=part.shape_key_add(name='Live native chat brace')
        leg_paths.append((leg,part,key,prefix))

CALL=[0,0,.28,.80,1,.92,.50,.10,0,0,0,0,0,.30,.85,1,.90,.55,.10,0,0,0,0,0]
CAW_LABELS=['First side','Full front','Mirrored side','Full front again']
CLIP_DEFS={'perch':(1,True),'idle':(200,True),'pet':(32,False),'caw':(144,True)}
INSPECTION={'perch':[0],'idle':[0,26,40,80,120,160],
            'pet':[0,8,14,21,31],'caw':[0,4,25,28,30,36,40,72,76,112,143]}
head_yaws=[-1.4+i*.2 for i in range(9)]
head_pitches=[-.24+i*.12 for i in range(5)]
head_tilts=[-.24+i*.12 for i in range(5)]

def eye_closure(amount):
    for eye,socket,lid in zip(eyes,sockets,lids):
        eye.scale=(1-.98*amount,1,1-.995*amount)
        socket.scale=(1,1,1-.94*amount);lid.scale=(amount,amount,amount)

def reset_pose(t=0):
    # Prototype shape keys from previous poses must not leak into this one.
    for obj in [body,*[part for owner,part,key,prefix in leg_paths]]:
        for key in obj.data.shape_keys.key_blocks[1:]:key.value=0
    pose('idle',t)
    eye_closure(0)
    for key in grips:key.value=1
    camera.location=CHAT_CAMERA[0].copy();camera.rotation_euler=CHAT_CAMERA[1].copy();camera.data.ortho_scale=CHAT_CAMERA[2]

def neck_coordinates(stretched=False):
    if not stretched:return deform_neck()
    rotation=head.rotation_euler.to_matrix();displacement=head.location-HEAD_PIVOT
    return [p.lerp(HEAD_PIVOT+rotation@(p-HEAD_PIVOT)+displacement,smooth((p.z-.53)/.29)) for p in body_basis]

def ring_coordinates(path,radii):
    result=[]
    for i,p in enumerate(path):
        p=Vector(p);tangent=Vector(path[min(i+1,len(path)-1)])-Vector(path[max(0,i-1)])
        tangent.normalize();a=Vector((0,1,0));b=tangent.cross(a).normalized()
        for j in range(5):
            angle=math.tau*j/5;result.append(p+radii[i]*(a*math.cos(angle)+b*math.sin(angle)))
    return result

def knee_for_ankle(ankle):
    delta=ankle-HIP;distance=delta.length
    assert distance<UPPER_LENGTH+LOWER_LENGTH+.002,('Overextended hop leg',distance)
    axis=delta.normalized();along=(UPPER_LENGTH**2-LOWER_LENGTH**2+distance**2)/(2*distance)
    height=math.sqrt(max(0,UPPER_LENGTH**2-along**2))
    return HIP+axis*along+Vector((axis.z,0,-axis.x))*height

def leg_shape(key,prefix,knee,ankle):
    if prefix=='Feathered thigh':
        path=[HIP,HIP.lerp(knee,.6)+Vector((-.012,0,0)),knee];radii=[.070,.053,.042]
    else:
        path=[knee+Vector((0,0,.06)),knee.lerp(ankle,.22)+Vector((-.0164,0,-.012)),
              knee.lerp(ankle,.77)+Vector((-.0849,0,-.042)),ankle]
        radii=[.047,.044,.039,.042]
    for vertex,co in zip(key.data,ring_coordinates(path,radii)):vertex.co=co

def caw_values(index):
    section=index//36;phase=index%36
    if phase<24:return CHAT_ANGLES[section],CALL[phase],CAW_LABELS[section],False,False,0,None,0
    step=phase-24
    height=[0,-.14,.018,.30,.42,.30,.018,-.09,-.045,0,0,0][step]
    progress=[0,0,0,.18,.50,.82,1,1,1,1,1,1][step]
    heading=CHAT_ANGLES[section]*(1-progress)+CHAT_ANGLES[(section+1)%4]*progress
    label=['Brace','Crouch','Push','Hop rise','Hop apex','Hop fall','Touch down','Land crouch','Recover','Settled','Settled','Settled'][step]
    return heading,0,label,True,3<=step<=5,height,step,progress

def apply_pose(clip,index):
    reset_pose(index/200 if clip=='idle' else 0)
    info={'cawOpen':0,'airborne':False,'hopping':False,'label':clip,'eyeClosure':0,'neckStretch':0}
    stretched=False
    if clip=='idle':
        seconds=index/8
        shut=max(bump(seconds,start,.375)**2 for start in [3.0625,8.6875,14.1875,21.3125])
        eye_closure(shut);info['eyeClosure']=shut;info['label']='Held multi-axis gaze'
    elif clip=='pet':
        neck=smooth((index-2)/8)*(1-smooth((index-22)/9))
        shut=smooth((index-1)/4)*(1-smooth((index-26)/5))
        nuzzle=math.sin((index-7)*math.pi/9)*bump(index,7,18)
        head.location=HEAD_PIVOT+Vector((.022*neck,0,.140*neck))
        head.rotation_euler=(-.080*neck+.070*nuzzle,-.120*neck-.025*nuzzle,-.095*neck+.055*nuzzle)
        eye_closure(shut);stretched=True
        info.update(eyeClosure=shut,neckStretch=.140*neck,nuzzle=nuzzle,label='Enjoying petting')
    elif clip=='caw':
        heading,amount,label,hopping,airborne,height,step,progress=caw_values(index)
        root.rotation_euler.z=heading;root.location.z=1.3+height
        head.rotation_euler.z=0;head.rotation_euler.y=-.055*amount
        closed_bill.value=1-amount;bill.rotation_euler.y=.055*amount;torso.scale.z=1+.004*amount
        lean=.065 if hopping and step==1 else .025 if hopping and step==7 else 0
        torso.rotation_euler.y=lean;head.rotation_euler.y-=lean*.45
        for leg,foot in zip(legs,feet):
            ankle=REST_ANKLE-Vector((0,0,height if not airborne else .045))
            if airborne:ankle+=Vector((-.055,0,.07))
            knee=knee_for_ankle(ankle);foot.location=ankle;foot.rotation_euler.y=.22 if airborne else 0
            for owner,part,key,prefix in leg_paths:
                if owner==leg:
                    leg_shape(key,prefix,knee,ankle)
                    # Keep neutral native legs exactly canonical at all holds.
                    key.value=1 if height!=0 or airborne else 0
        info.update(cawOpen=amount,label=label,hopping=hopping,airborne=airborne,hopStep=step,turnProgress=progress)
    coords=neck_coordinates(stretched)
    for vertex,co in zip(live_neck.data,coords):vertex.co=co
    live_neck.value=1;bpy.context.view_layer.update()
    return info

def apply_attention(index):
    reset_pose(0)
    yaw_index=index%9;pitch_index=(index//9)%5;tilt_index=(index//45)%5;blink=index//225
    head.rotation_euler=(head_tilts[tilt_index],head_pitches[pitch_index],head_yaws[yaw_index])
    eye_closure(blink)
    for vertex,co in zip(live_neck.data,neck_coordinates()):vertex.co=co
    live_neck.value=1;bpy.context.view_layer.update()
    return {'cawOpen':0,'airborne':False,'hopping':False,'eyeClosure':blink,'neckStretch':0,
            'label':'Near-head cursor attention','indices':{'blink':blink,'tilt':tilt_index,'pitch':pitch_index,'yaw':yaw_index}}

def screen(point):
    q=world_to_camera_view(scene,camera,point);return {'x':round(q.x,6),'y':round(1-q.y,6)}

def pose_metadata(info):
    bpy.context.view_layer.update()
    contacts=[foot.matrix_world@CHAT_CONTACT_LOCAL for foot in feet]
    contact_world=CHAT_ROOT_BASE+Matrix.Rotation(root.rotation_euler.z,4,'Z')@CHAT_CONTACT_ROOT
    amount=info.get('cawOpen',0)
    tip=from_reference(464,140+44*(1-amount));local=Vector((tip[0]-bill_origin[0],0,tip[1]-bill_origin[1]))
    beak_world=upper.matrix_world@local;beak=screen(beak_world)
    axis=(head.matrix_world.to_3x3()@Vector((1,0,0))).normalized();ahead=screen(beak_world+axis*.35)
    direction=Vector((ahead['x']-beak['x'],ahead['y']-beak['y']))
    if direction.length<.004:direction=Vector((0,1))
    direction.normalize()
    result={'root':screen(root.matrix_world.translation),'rootZ':round(root.location.z,6),
            'head':screen(head.matrix_world@Vector((.11,0,.22))),'beak':beak,
            'foot':screen(sum(contacts,Vector())/2),'contact':screen(contact_world),
            'feetEach':[screen(p) for p in contacts],'contacts':[list(p) for p in contacts],
            'groundContactWorld':list(contact_world),'orthoScale':camera.data.ortho_scale,
            'heading':round(root.rotation_euler.z,6),'headTilt':[round(v,6) for v in head.rotation_euler],
            'soundDirection':{'x':round(direction.x,6),'y':round(direction.y,6)},
            'frontness':round(1-abs(math.sin(root.rotation_euler.z+head.rotation_euler.z-CHAT_FRONT)),6),
            'grip':1}
    result.update(info);return result

def bake_frame(frame,name):
    baked=body.shape_key_add(name=name+' neck')
    for vertex,co in zip(baked.data,live_neck.data):vertex.co=co.co
    for at,amount in [(frame-1,0),(frame,1),(frame+1,0)]:baked.value=amount;baked.keyframe_insert(data_path='value',frame=at)
    live_neck.value=0;baked.value=1
    for owner,part,key,prefix in leg_paths:
        target=key.data if key.value else part.data.shape_keys.key_blocks['Basis'].data
        shape=part.shape_key_add(name=name+' leg')
        for vertex,co in zip(shape.data,target):vertex.co=co.co
        for at,amount in [(frame-1,0),(frame,1),(frame+1,0)]:shape.value=amount;shape.keyframe_insert(data_path='value',frame=at)
        key.value=0;shape.value=1
    for obj in [*animated,*sockets,*lids]:
        for prop in ['location','rotation_euler','scale']:obj.keyframe_insert(data_path=prop,frame=frame)
    for key in [closed_bill,*grips,*wing_spreads,*wing_flexes,*wing_roll_tucks,*leg_tucks,*leg_swings]:key.keyframe_insert(data_path='value',frame=frame)

def render_fingerprint():
    # Actual evaluated geometry prevents accidental reuse of a stale head,
    # eyelid, toe curl or connected knee pose.
    depsgraph=bpy.context.evaluated_depsgraph_get();values=[]
    for obj in sorted((o for o in scene.objects if o.type=='MESH' and not o.hide_render),key=lambda o:o.name):
        values.append(obj.name);values.extend(float(v) for row in obj.matrix_world for v in row)
        evaluated=obj.evaluated_get(depsgraph);mesh=evaluated.to_mesh()
        try:values.extend(float(v) for vertex in mesh.vertices for v in vertex.co)
        finally:evaluated.to_mesh_clear()
    return tuple(values)

def finalise_timeline(path,frames,description):
    body.shape_key_remove(live_neck)
    for owner,part,key,prefix in leg_paths:part.shape_key_remove(key)
    for datablock in [*bpy.data.objects,*[o.data.shape_keys for o in scene.objects if o.type=='MESH' and o.data.shape_keys]]:
        animation=getattr(datablock,'animation_data',None)
        if not animation or not animation.action:continue
        for layer in animation.action.layers:
            for strip in layer.strips:
                for bag in strip.channelbags:
                    for curve in bag.fcurves:
                        for point in curve.keyframe_points:point.interpolation='CONSTANT'
    scene.frame_start=1;scene.frame_end=frames;scene.render.fps=8;scene.frame_set(1);scene.camera=camera
    scene['README']=description;scene['Base source SHA256']=CHAT_BASE_SHA
    for area in bpy.context.screen.areas:
        if area.type=='VIEW_3D':
            area.spaces.active.region_3d.view_perspective='CAMERA';area.spaces.active.camera=camera
            area.spaces.active.shading.type='MATERIAL';area.spaces.active.overlay.show_overlays=False
    bpy.ops.wm.save_as_mainfile(filepath=str(path))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--scout',action='store_true');parser.add_argument('--timeline-only',action='store_true')
    args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else [])
    destination=P/'chat-perch-frames';destination.mkdir(exist_ok=True)
    metadata={'version':24,'baseSourceSha256':CHAT_BASE_SHA,'frameWidth':512,'frameHeight':512,'columns':8,'fps':8,
              'defaultHeading':CHAT_HEADING,'perchHeading':CHAT_HEADING,'startHeading':CHAT_HEADING,'frontHeading':CHAT_FRONT,
              'camera':{'location':list(CHAT_CAMERA[0]),'rotation':list(CHAT_CAMERA[1]),'orthoScale':3.75},
              'contactDescription':'Actual grip anchor is foot-local (.08,0,-.07). contact is the virtual grounded grip anchor at the current heading; its height excludes caw hops. Anchor contact to Send, retaining native airborne foot travel.',
              'clips':{}}
    cache={};frame=0
    for clip,(count,loop) in CLIP_DEFS.items():
        start=frame+1;scene.timeline_markers.new(clip,frame=start)
        item={'frames':count,'fps':8,'loop':loop,'duration':count/8,'startFrame':start,'poses':[],
              'inspection':[{'frame':f,'label':clip+' '+str(f)} for f in INSPECTION[clip]],
              'sourcePattern':'chat-perch-frames/'+clip+'-%03d.png'}
        if clip=='caw':
            item['sections']=[{'start':i*36,'callFrames':24,'hopFrames':12,'heading':a,'label':CAW_LABELS[i]} for i,a in enumerate(CHAT_ANGLES)]
            item['startHeading']=CHAT_HEADING;item['frontHeading']=CHAT_FRONT
        for index in range(count):
            frame+=1;scene.frame_set(frame);info=apply_pose(clip,index)
            item['poses'].append(pose_metadata(info));bake_frame(frame,f'{clip} {index:03d}')
            if not args.timeline_only and (not args.scout or index in INSPECTION[clip]):
                path=destination/f'{clip}-{index:03d}.png';key=render_fingerprint()
                if key in cache:shutil.copyfile(cache[key],path)
                else:
                    scene.render.filepath=str(path);bpy.ops.render.render(write_still=True);cache[key]=path
                print('CHAT_PERCH',clip,index+1,'/',count,flush=True)
        metadata['clips'][clip]=item
    metadata['renderedUniquePoses']=len(cache)
    if not args.scout:
        finalise_timeline(P/'raven-chat-perch-v24.blend',frame,'v24 native button perch, multi-axis idle gazes, subtle blinking, approved petting and whole-body hopping caw. 8 fps; one fixed camera at 3.75; continuously connected neck/legs; native 3D curled toes. contact anchors retain actual hops.')
        (P/'chat-perch.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    else:(P.parent.parent/'work'/'chat-perch-scout-v24.json').write_text(json.dumps(metadata,indent=2),encoding='utf-8')
    print('CHAT_PERCH_COMPLETE',frame,'logical frames;',len(cache),'native renders',flush=True)

if __name__=='__main__':main()
