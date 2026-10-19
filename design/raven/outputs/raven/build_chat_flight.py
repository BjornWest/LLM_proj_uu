"""v24 local chat flight, with approved v23 push-off and common anatomy.
Blender --background --threads 2 --python build_chat_flight.py [--scout-v24]
"""
import bpy,math,json,sys,hashlib
from pathlib import Path
from mathutils import Vector,Matrix
from bpy_extras.object_utils import world_to_camera_view
P=Path(__file__).resolve().parent
exec(compile((P/'flight_anatomy_v24.py').read_text(encoding='utf-8'),str(P/'flight_anatomy_v24.py'),'exec'),globals())
SCOUT='--scout-v24' in sys.argv
study=P.parents[1]/'work'/'chat-flight-v24-scout';study.mkdir(parents=True,exist_ok=True)
destination=(study/'frames') if SCOUT else P/'chat-flight-frames';destination.mkdir(exist_ok=True)
scene.render.resolution_x=scene.render.resolution_y=512;scene.cycles.samples=16
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
    grips.append(grip)
all_keys=wing_spreads+wing_flexes+wing_roll_tucks+leg_tucks+leg_swings+grips+[closed_bill]
TARGET=Vector((-.03,0,1.35));LOCAL_ROOT=Vector((0,0,1.3))
def camera_local(rotation,scale):
    camera.rotation_euler=rotation.to_euler();camera.location=TARGET-(rotation@Vector((0,0,-1)))*12.337
    camera.data.ortho_scale=scale
def localize(scale=8):
    rotation=camera.rotation_euler.to_quaternion();root.location=LOCAL_ROOT.copy();camera_local(rotation,scale)
def capture():return {o.name:(o.location.copy(),o.rotation_euler.to_quaternion(),o.scale.copy()) for o in animated}
pose('idle',0);idle_camera=camera.rotation_euler.to_quaternion();idle_rotation=camera.rotation_euler.copy();idle_location=camera.location.copy()
bpy.context.view_layer.update()
grip_ground_point=sum((foot.matrix_world@Vector((.08,0,-.07)) for foot in feet),Vector())/2
pose('soaring',110/160);localize();entry=capture();entry_camera=camera.rotation_euler.to_quaternion()
entry_keys=[key.value for key in all_keys];flight_camera_rotation=entry_camera.copy()
takeoff_final=None;takeoff_final_keys=None;takeoff_final_body=None;takeoff_final_legs=None;takeoff_final_wings=None
body_coordinates=[]
contact_point=grip_ground_point.copy();native_root_delta=Vector()

def inherited_wings(name,t):
    """Retain approved distal articulation while keeping the collar fixed."""
    unfold=wing_spreads[0].value;rotations=[]
    if name in ['patrol','glide']:
        phase=t*2;wind=math.sin(math.tau*phase);trim=math.sin(math.tau*phase*2)
        for side in [-1,1]:rotations.append(Matrix.Rotation(side*(.24+.016*wind+side*.008*trim),3,'Z')@Matrix.Rotation(side*.013*trim,3,'X'))
    elif name=='patrol_roll':
        phase=t*39/160*2;wind=math.sin(math.tau*phase);trim=math.sin(math.tau*phase*2)
        old_plane=1.35-torso.rotation_euler.y+.010*trim
        plane=old_plane+(.45-old_plane)*wing_roll_tucks[0].value
        for wing in wings:rotations.append(Matrix.Rotation(-plane,3,'Y')@wing.rotation_euler.to_matrix())
    elif name=='diving':
        brake=smooth((t-.22)/.24);fold=smooth((t-.62)/.28)
        for side in [-1,1]:rotations.append(Matrix.Rotation(side*(.95-.73*brake)*(1-fold),3,'Z'))
    shared_flight_wings(unfold,rotations)

def local_pose(name,f,count):
    global flight_compression,streamline,body_coordinates,takeoff_final,takeoff_final_keys,takeoff_final_body,takeoff_final_legs,takeoff_final_wings,contact_point,native_root_delta
    t=f/(count-1) if count>1 else 0
    for owner,part,key in leg_paths:key.value=0
    for mesh,key in wing_strokes:key.value=0
    for key in grips:key.value=0
    native_root_delta=Vector();contact_point=None
    if name=='takeoff':
        body_coordinates=shared_takeoff_pose(f)
        for key in grips:key.value=1-smooth((f-7)/3)
        native_root_delta=root.location-LOCAL_ROOT;contact_point=grip_ground_point-native_root_delta
        rotation=idle_camera.slerp(flight_camera_rotation,smooth((f-10)/21))
        scale=3.75+(8-3.75)*smooth((f-7)/3)
        root.location=LOCAL_ROOT.copy();camera_local(rotation,scale)
        if f==0:
            pose('idle',0)
            for key in grips:key.value=1
            for owner,part,key in leg_paths:key.value=0
            for mesh,key in wing_strokes:key.value=0
            body_coordinates=shared_flight_body(0)
            camera.location=idle_location.copy();camera.rotation_euler=idle_rotation.copy()
        if f==39:
            takeoff_final=capture();takeoff_final_keys=[k.value for k in all_keys];takeoff_final_body=[p.copy() for p in body_coordinates]
            takeoff_final_legs=[(part,[v.co.copy() for v in key.data],key.value) for owner,part,key in leg_paths]
            takeoff_final_wings=[(mesh,[v.co.copy() for v in key.data]) for mesh,key in wing_strokes]
    elif name=='glide_right':
        for obj in animated:
            l,r,s=takeoff_final[obj.name];obj.location=l.copy();obj.rotation_euler=r.to_euler();obj.scale=s.copy()
        for key,value in zip(all_keys,takeoff_final_keys):key.value=value
        for (owner,part,key),(_,coords,value) in zip(leg_paths,takeoff_final_legs):
            for vertex,p in zip(key.data,coords):vertex.co=p
            key.value=value
        for (mesh,key),(_,coords) in zip(wing_strokes,takeoff_final_wings):
            for vertex,p in zip(key.data,coords):vertex.co=p
            key.value=1
        body_coordinates=[p.copy() for p in takeoff_final_body];camera_local(flight_camera_rotation,8)
    elif name in ['glide','patrol']:
        phase=f/160 if name=='patrol' else .5
        pose('soaring',phase);localize();tail.rotation_euler.y+=.055;inherited_wings(name,phase);body_coordinates=shared_flight_body(1);shared_flight_legs(phase)
    elif name=='patrol_roll':
        pose('soaring',f/160);base_location=root.location.copy();pose('patrol_roll',t);shift=root.location-base_location
        localize();root.location+=shift;tail.rotation_euler.y+=.055;inherited_wings(name,t);body_coordinates=shared_flight_body(1);shared_flight_legs(f/160)
    elif name=='diving':
        gate=smooth(t/.18);u=max(0,min(1,(t-.15)/.85));pose('diving',u)
        crouch=root.location.z-(1.30+2.9*(1-smooth(u/.65)));root.location=LOCAL_ROOT+Vector((0,0,crouch))
        rotation=camera.rotation_euler.to_quaternion()
        for obj in animated:
            l,r,s=entry[obj.name];obj.location=l.lerp(obj.location,gate);obj.rotation_euler=r.slerp(obj.rotation_euler.to_quaternion(),gate).to_euler();obj.scale=s.lerp(obj.scale,gate)
        for key,value in zip(all_keys,entry_keys):key.value=value+(key.value-value)*gate
        tail.rotation_euler.y+=.055*(1-smooth((u-.46)/.29))
        camera_local(entry_camera.slerp(rotation,gate),8+(3.75-8)*smooth((u-.72)/.20))
        for key in grips:key.value=smooth((u-.78)/.14)
        inherited_wings(name,u)
        if gate<1:
            phase=110/160;wind=math.sin(math.tau*phase*2);trim=math.sin(math.tau*phase*4);unfold=wing_spreads[0].value;brake=smooth((u-.22)/.24);fold=smooth((u-.62)/.28);distal=[]
            for side in [-1,1]:
                a=(Matrix.Rotation(side*(.24+.016*wind+side*.008*trim),3,'Z')@Matrix.Rotation(side*.013*trim,3,'X')).to_quaternion()
                b=Matrix.Rotation(side*(.95-.73*brake)*(1-fold),3,'Z').to_quaternion();distal.append(a.slerp(b,gate).to_matrix())
            shared_flight_wings(unfold,distal)
        body_coordinates=shared_flight_body(1-smooth((u-.46)/.29))
        shared_flight_legs(110/160,1-smooth((u-.43)/.23))
        if f>=28:
            heading_matrix=Matrix.Rotation(root.rotation_euler.z,4,'Z')
            ground_local=Matrix.Rotation(-heading,4,'Z')@(grip_ground_point-LOCAL_ROOT)
            contact_point=LOCAL_ROOT+heading_matrix@ground_local
        if f==count-1:
            pose('idle',0)
            for key in grips:key.value=1
            for owner,part,key in leg_paths:key.value=0
            for mesh,key in wing_strokes:key.value=0
            body_coordinates=shared_flight_body(0);contact_point=grip_ground_point.copy()
            camera.location=idle_location.copy();camera.rotation_euler=idle_rotation.copy();camera.data.ortho_scale=3.75
    else:raise ValueError(name)
    flight_compression=0

def screen(point):
    v=world_to_camera_view(scene,camera,point);return {'x':round(v.x,7),'y':round(1-v.y,7)}
def metadata(name,f):
    bpy.context.view_layer.update();foot_points=[foot.matrix_world@Vector((.08,0,-.07)) for foot in feet]
    closed_tip=from_reference(464,184);tip=Vector((closed_tip[0]-bill_origin[0],0,closed_tip[1]-bill_origin[1]))
    result={'foot':screen(sum(foot_points,Vector())/2),'head':screen(head.matrix_world@Vector((.11,0,.22))),'beak':screen(upper.matrix_world@tip),'root':screen(LOCAL_ROOT),'orthoScale':camera.data.ortho_scale,'cawOpen':0}
    result['contact']=screen(contact_point) if contact_point is not None else result['foot'].copy()
    if name in ['patrol','patrol_roll']:
        path=json.loads((P/'patrol-path.json').read_text())['screen'][f];result['path']={'x':path[0]/256,'y':path[1]/256}
    if name=='takeoff':result.update(grounded=f<=10,nativeRootDelta=list(native_root_delta))
    if name=='diving':result['landed']=f>=28
    return result

definitions={'takeoff':(40,False),'glide_right':(1,True),'glide':(1,True),'patrol':(160,True),'patrol_roll':(40,False),'diving':(40,False)}
scout_frames={'takeoff':[0,6,10,11,18,39],'glide_right':[0],'glide':[0],'patrol':[0,40,80,110,159],'patrol_roll':[0,10,18,28,39],'diving':[0,8,18,28,39]}
data={'version':24,'frameWidth':512,'frameHeight':512,'columns':12,'baseSourceSha256':prototype_base_sha256,'clips':{},'timeline':{'replyMs':10000,'takeoffMs':5000,'braceThroughFrame':10,'outsideMs':375,'enterMs':875,'patrolStartFrame':80,'diveStartPatrolFrame':110,'diveMs':5000,'landingFrame':28},'anatomy':{'flightCompression':0,'wingPlaneAngle':SPINE_OPEN_ANGLE,'collarStrokeWeight':0,'strokeRampSpan':[.18,.80],'bodyCorrection':'Same v23 canonical dorsal-only correction; neutral breast underside and width retained in takeoff and soaring'}}
start=1
for name,(count,loop) in definitions.items():
    clip={'frames':count,'fps':8,'loop':loop,'startFrame':start,'poses':[],'baseSourceSha256':prototype_base_sha256}
    if name=='diving':clip.update(entryFrame=110,landingFrame=28)
    data['clips'][name]=clip;scene.timeline_markers.new('Chat '+name,frame=start);previous=None
    for f in range(count):
        frame=start+f;scene.frame_set(frame);local_pose(name,f,count)
        if previous is not None:root.rotation_euler=root.rotation_euler.to_matrix().to_euler('XYZ',previous)
        previous=root.rotation_euler.copy();shape=body.shape_key_add(name='Chat %s %03d'%(name,f))
        for vertex,co in zip(shape.data,body_coordinates):vertex.co=co
        for at,value in [(frame-1,0),(frame,1),(frame+1,0)]:shape.value=value;shape.keyframe_insert(data_path='value',frame=at)
        for owner,part,key in leg_paths:
            baked=part.shape_key_add(name='Chat %s brace %03d'%(name,f))
            for vertex,co in zip(baked.data,key.data):vertex.co=co.co
            for at,value in [(frame-1,0),(frame,key.value),(frame+1,0)]:baked.value=value;baked.keyframe_insert(data_path='value',frame=at)
            key.value=0
        for mesh,key in wing_strokes:
            baked=mesh.shape_key_add(name='Chat %s collar %03d'%(name,f))
            for vertex,co in zip(baked.data,key.data):vertex.co=co.co
            for at,value in [(frame-1,0),(frame,key.value),(frame+1,0)]:baked.value=value;baked.keyframe_insert(data_path='value',frame=at)
            key.value=0
        for obj in animated:
            for prop in ['location','rotation_euler','scale']:obj.keyframe_insert(data_path=prop,frame=frame)
        for key in all_keys:key.keyframe_insert(data_path='value',frame=frame)
        for prop in ['location','rotation_euler']:camera.keyframe_insert(data_path=prop,frame=frame)
        camera.data.keyframe_insert(data_path='ortho_scale',frame=frame);clip['poses'].append(metadata(name,f))
    start+=count+4
scene.frame_start=1;scene.frame_end=start-4;scene.render.fps=8;scene.frame_set(1)
scene['README']='v24 complete chat flight, frozen v23 model: identical grounded push-off and canonical dorsal-only anatomy throughout soaring, roll and landing. Neutral hanging breast and width stay intact; torso-following angular wings use a pinned inboard collar and distal elbow/primary articulation. Normalized root/foot metadata supplies browser travel. Takeoff40, patrol160, roll40, dive40 at8fps. Dive begins exactpatrol110, lands28, ends real curled idle. All deformations, transforms and cameras are baked/editable.'
scene['Base source SHA256']=prototype_base_sha256
bpy.ops.wm.save_as_mainfile(filepath=str((study if SCOUT else P)/'raven-chat-flight-v24.blend'))
((study if SCOUT else P)/'chat-flight.json').write_text(json.dumps(data,indent=2),encoding='utf-8')
for name,(count,_) in definitions.items():
    indices=scout_frames[name] if SCOUT else list(range(count))
    if '--clips' in sys.argv and name not in sys.argv[sys.argv.index('--clips')+1].split(','):continue
    for f in indices:
        scene.frame_set(data['clips'][name]['startFrame']+f);scene.render.filepath=str(destination/('%s-%02d.png'%(name,f)))
        bpy.ops.render.render(write_still=True);print('CHAT_FLIGHT',name,f,flush=True)
print('CHAT_FLIGHT_RENDER_COMPLETE',flush=True)
