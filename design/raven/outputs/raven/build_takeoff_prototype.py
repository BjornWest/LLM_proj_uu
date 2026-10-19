"""Grounded leg-driven takeoff study, separate from the approved chat clips.
Blender --background --threads 2 --python build_takeoff_prototype.py
"""
import bpy, math, json, sys, hashlib
from pathlib import Path
from mathutils import Vector, Matrix
from bpy_extras.object_utils import world_to_camera_view

P=Path(__file__).resolve().parent
prototype_base_source_text=(P/'build_raven.py').read_text(encoding='utf-8').split("manifest={'frameWidth'")[0]
prototype_base_sha256=hashlib.sha256(prototype_base_source_text.encode('utf-8')).hexdigest()
exec(compile(prototype_base_source_text,str(P/'build_raven.py'),'exec'),globals())
SCOUT='--scout-v23' in sys.argv
study_directory=P.parents[1]/'work'/'takeoff-v23-scout'
if SCOUT:study_directory.mkdir(parents=True,exist_ok=True)
destination=(study_directory/'frames') if SCOUT else P/'takeoff-prototype-frames';destination.mkdir(exist_ok=True)
scene.render.resolution_x=scene.render.resolution_y=512
scene.cycles.samples=16
set_palette(False)
COUNT=40;FPS=8;PUSH_START=7;PUSH_END=10;RELEASE=11;FLAP_START=10
CROUCH_DEPTH=.36;PUSH_HEIGHT=.022
heading=base[root.name][1].z
turn=Matrix.Rotation(heading,4,'Z')
target=Vector((.3,-.18,2.3))
camera.location=turn@Vector((1,-12,3.1))
camera.rotation_euler=(target-camera.location).to_track_quat('-Z','Y').to_euler()
camera.data.ortho_scale=6.9
fixed_camera=(camera.location.copy(),camera.rotation_euler.copy())
leg_paths=[]
wing_strokes=[]
SPINE_OPEN_ANGLE=math.atan2(.45,.79)
for wing in wings:
    mesh_object=next(o for o in wing.children if o.type=='MESH')
    live=mesh_object.shape_key_add(name='Fixed shoulder collar and powered elbow')
    wing_strokes.append((mesh_object,live))

def ring_coordinates(path,radii):
    verts=[]
    for i,p in enumerate(path):
        p=Vector(p)
        tangent=Vector(path[min(i+1,len(path)-1)])-Vector(path[max(0,i-1)])
        tangent.normalize();a=Vector((0,1,0));b=tangent.cross(a).normalized()
        for j in range(5):
            angle=math.tau*j/5
            verts.append(p+radii[i]*(a*math.cos(angle)+b*math.sin(angle)))
    return verts

for leg in legs:
    thigh=next(p for p in leg.children if p.name.startswith('Feathered thigh'))
    shin=next(p for p in leg.children if p.name.startswith('Continuous ankle'))
    for part in [thigh,shin]:
        part.shape_key_add(name='Basis') if not part.data.shape_keys else None
        key=part.shape_key_add(name='Grounded brace and extension')
        key.value=1
        leg_paths.append((leg,part,key))

hip=Vector((-.12,0,.85));rest_knee=Vector((-.035,0,.45));rest_ankle=Vector((.27,0,.15))
upper_length=(rest_knee-hip).length;lower_length=(rest_ankle-rest_knee).length

def knee_for_ankle(ankle,upper_hip=hip):
    delta=ankle-upper_hip;distance=delta.length
    assert distance<upper_length+lower_length+.002,('Overextended planted leg',distance)
    axis=delta.normalized()
    along=(upper_length**2-lower_length**2+distance**2)/(2*distance)
    height=math.sqrt(max(0,upper_length**2-along**2))
    perpendicular=Vector((axis.z,0,-axis.x))
    return upper_hip+axis*along+perpendicular*height

def leg_shape(part,key,knee,ankle,upper_hip=hip,radius_scale=1):
    if part.name.startswith('Feathered thigh'):
        path=[upper_hip,upper_hip.lerp(knee,.48),knee];radii=[.070,.053,.042]
    else:
        path=[knee+Vector((0,0,.052)),knee.lerp(ankle,.22),knee.lerp(ankle,.77),ankle]
        radii=[.047,.044,.039,.042]
    for vertex,point in zip(key.data,ring_coordinates(path,[r*radius_scale for r in radii])):vertex.co=point

def snapshot():
    return {o.name:(o.location.copy(),o.rotation_euler.to_quaternion(),o.scale.copy()) for o in animated}

pose('soar_intro',0)
goal=snapshot();goal_keys={k.name:k.value for k in wing_spreads+wing_flexes+wing_roll_tucks+leg_tucks+leg_swings}
pose('idle',0)
standing=snapshot()
foot_contacts=[]
bpy.context.view_layer.update()
for foot in feet:foot_contacts.append(foot.matrix_world@Vector((.13,0,-.141)))
foot_targets=[foot.matrix_world.translation.copy() for foot in feet]
ankle_targets=[leg.matrix_world@rest_ankle for leg in legs]
hip_in_torso=[torso.matrix_world.inverted()@(leg.matrix_world@hip) for leg in legs]
hip_pivot=sum(hip_in_torso,Vector())/len(hip_in_torso)
all_keys=wing_spreads+wing_flexes+wing_roll_tucks+leg_tucks+leg_swings+[closed_bill]
poses=[];checks=[]
streamline=0
canonical_body_delta=None

def takeoff_body_shape():
    """Gently align the dorsal shell while retaining neutral breast depth.

    The canonical correction rotates with the torso. It preserves the
    actual hanging underside and full width, and leaves the skull/bill
    attachment unchanged; only the dorsal neck/back contour is smoothed.
    """
    global canonical_body_delta,flight_compression
    original=deform_neck()
    if streamline==0:return original
    if canonical_body_delta is not None:
        return [p+delta*streamline for p,delta in zip(original,canonical_body_delta)]
    # Construct one anatomical correction in the completed flight pose.
    # Its torso-local coordinates then rotate naturally with the actual
    # torso through takeoff. A partly upright launch is never remapped to
    # an already horizontal world-space silhouette.
    saved_head_rotation=head.rotation_euler.copy();saved_compression=flight_compression
    head.rotation_euler=goal[head.name][1].to_euler();flight_compression=0
    canonical_original=deform_neck()
    head.rotation_euler=saved_head_rotation;flight_compression=saved_compression
    parent=Matrix.LocRotScale(*goal[torso.name])
    inverse=parent.inverted()
    shell=[parent@p for p in canonical_original]
    shaped=[]
    for basis,p in zip(body_basis,shell):
        weight=(1-smooth((basis.z-1.04)/.12))*(1-smooth((p.x-.45)/.50))
        amount=weight
        if amount==0:shaped.append(inverse@p);continue
        heights=[]
        for polygon in body.data.polygons:
            vertices=[shell[i] for i in polygon.vertices]
            for a,b in zip(vertices,vertices[1:]+vertices[:1]):
                if min(a.x,b.x)-1e-7<=p.x<=max(a.x,b.x)+1e-7:
                    if abs(a.x-b.x)<1e-7:heights.extend([a.z,b.z])
                    else:heights.append(a.z+(b.z-a.z)*(p.x-a.x)/(b.x-a.x))
        low,high=min(heights),max(heights)
        relative=(p.z-low)/(high-low) if high-low>.001 else .5
        # Keep the actual neutral hanging underside and width. Only smooth
        # the dorsal back/neck contour; no shallower lower envelope and no
        # cross-body compression can make the launch visibly shrink.
        lower=low
        upper=max(low+.02,high+.75*((.42+.31*p.x)-high))
        target=Vector((p.x,p.y,lower+relative*(upper-lower)))
        shaped.append(inverse@p.lerp(target,amount))
    canonical_body_delta=[target-source for source,target in zip(canonical_original,shaped)]
    return [p+delta*streamline for p,delta in zip(original,canonical_body_delta)]

def prototype_pose(frame):
    global flight_compression,streamline
    seconds=frame/FPS
    # The deep brace loads the legs before the extension. The chest pitches
    # around the hip attachment, rather than the bird drifting into the air.
    if frame<=6:
        offset=-CROUCH_DEPTH*smooth(frame/6)
    elif frame<=PUSH_START:
        offset=-CROUCH_DEPTH
    elif frame<=PUSH_END:
        offset=-CROUCH_DEPTH+(CROUCH_DEPTH+PUSH_HEIGHT)*smooth((frame-PUSH_START)/(PUSH_END-PUSH_START))
    else:
        offset=PUSH_HEIGHT+1.27*(1-math.exp(-(frame-PUSH_END)/7.5))
    brace=smooth(frame/6)*(1-smooth((frame-PUSH_START)/(PUSH_END-PUSH_START)))
    flight_blend=smooth((frame-PUSH_END)/15)
    leg_blend=smooth((frame-PUSH_END)/10)
    for o in animated:
        l,q,s=standing[o.name];gl,gq,gs=goal[o.name]
        weight=leg_blend if o in legs+feet else flight_blend
        o.location=l.lerp(gl,weight)
        o.rotation_euler=q.slerp(gq,weight).to_euler()
        o.scale=s.lerp(gs,weight)
    # A fixed heading makes the leg action and the ground easy to inspect.
    drift=turn@Vector((.65*flight_blend,0,0))
    root.location=(drift.x,drift.y,1.3+offset);root.rotation_euler=(0,0,heading)
    # Both hips stay attached to their original points in the torso. The
    # mean hip is the lean pivot, avoiding a translation caused by pitching
    # about the sprite root near the feet.
    prior_torso_rotation=torso.rotation_euler.to_matrix()
    torso.rotation_euler.y+=.28*brace
    torso.location+=prior_torso_rotation@hip_pivot-torso.rotation_euler.to_matrix()@hip_pivot
    flight_compression=0
    streamline=smooth((frame-RELEASE)/12)
    tail.rotation_euler.y+=.055*streamline
    head.rotation_euler.y=.24*brace-.045*(1-flight_blend)-.12*flight_blend-torso.rotation_euler.y*flight_blend
    closed_bill.value=1
    for eye_object in eyes:eye_object.scale=base[eye_object.name][2].copy()
    for key in wing_spreads+wing_flexes+wing_roll_tucks+leg_tucks+leg_swings:key.value=0
    # Wings spread during the three-frame push. They are raised at full leg
    # extension; the first downstroke starts as the claws release.
    unfold=smooth((frame-PUSH_START)/(PUSH_END-PUSH_START))
    flap_gate=unfold*(1-smooth((frame-32)/5))
    flap_phase=max(0,(frame-FLAP_START)/8)*math.tau
    powered=math.cos(flap_phase)
    for wing,side in zip(wings,[-1,1]):
        wing.location.y=side*(.31-.07*flight_blend)
        flap=side*(.24*unfold+.87*flap_gate*powered)
        # Local chord Z opens along the anatomical spine. The body supplies
        # its own pitch, so a raised wing leans with the bird instead of
        # being locked vertically against the global ground plane.
        wing.rotation_euler=(0,SPINE_OPEN_ANGLE*unfold,0)
    for key in wing_spreads:key.value=unfold
    for key,side in zip(wing_flexes,[-1,1]):key.value=.58*flap_gate*math.sin(flap_phase)+.18*math.sin(side*.6)*(1-flap_gate)*unfold
    for key in wing_roll_tucks:key.value=0
    for (mesh_object,key),side in zip(wing_strokes,[-1,1]):
        shapes=mesh_object.data.shape_keys.key_blocks
        basis=shapes['Basis'];spread=shapes['Flight spread'];flex=shapes['Feather flex'];tuck=shapes['Roll elbow tuck']
        flap=side*(.24*unfold+.87*flap_gate*powered)
        for index,vertex in enumerate(key.data):
            b=basis.data[index].co
            current=b+(spread.data[index].co-b)*unfold+(flex.data[index].co-b)*flex.value+(tuck.data[index].co-b)*tuck.value
            # All six collar vertices stay fixed. Stroke amplitude then
            # grows continuously toward the elbow and outer primaries.
            span=abs(spread.data[index].co.y)
            motion=smooth((span-.18)/.62)
            moved=Matrix.Rotation(flap*motion,4,'Z')@current
            vertex.co=b+(moved-current)
        key.value=1
    # Feet and ankles remain anchored through the completed push. After
    # release they smoothly fold into the existing hanging flight pose.
    bpy.context.view_layer.update()
    leg_states=[]
    for index,(leg,foot) in enumerate(zip(legs,feet)):
        if frame<=PUSH_END:
            ankle=leg.matrix_world.inverted()@ankle_targets[index]
            upper_hip=leg.matrix_world.inverted()@(torso.matrix_world@hip_in_torso[index])
            knee=knee_for_ankle(ankle,upper_hip)
            foot.location=ankle
            foot.rotation_euler=(0,0,0);foot.scale=(1,1,1)
            for owner,part,key in leg_paths:
                if owner==leg:leg_shape(part,key,knee,ankle,upper_hip);key.value=1
        else:
            # Interpolate the connected paths into the approved flight leg
            # form. Using the same ankle coordinate for the foot and shin
            # keeps their endpoints joined throughout the release.
            side=[-1,1][index];adjustment=math.sin(side*.7)
            release_ankle=rest_ankle-Vector((0,0,PUSH_HEIGHT))
            ankle=release_ankle.lerp(goal[foot.name][0],leg_blend)
            flight_hip=Vector((-.40+side*.04,side*.24*(1-.27*streamline),-.05+.075*streamline))
            flight_knee=Vector((-.16+side*.04+.018*adjustment,side*.24,-.45+.0105*adjustment))
            attached_hip=leg.matrix_world.inverted()@(torso.matrix_world@hip_in_torso[index])
            upper_hip=attached_hip.lerp(flight_hip,leg_blend)
            knee=knee_for_ankle(release_ankle).lerp(flight_knee,leg_blend)
            foot.location=ankle
            for owner,part,key in leg_paths:
                if owner==leg:
                    leg_shape(part,key,knee,ankle,upper_hip,1-.20*leg_blend);key.value=1
        bpy.context.view_layer.update()
        leg_states.append({'hip':list(leg.matrix_world@upper_hip),'knee':list(leg.matrix_world@knee),
                           'ankle':list(leg.matrix_world@ankle),'footOrigin':list(foot.matrix_world.translation),
                           'kneeAngle':math.degrees((upper_hip-knee).angle(ankle-knee))})
    camera.location=fixed_camera[0].copy();camera.rotation_euler=fixed_camera[1].copy();camera.data.ortho_scale=6.9
    bpy.context.view_layer.update()
    planted=[foot.matrix_world@Vector((.13,0,-.141)) for foot in feet]
    checks.append({'frame':frame,'rootZ':root.location.z,'streamline':streamline,'torsoPitch':torso.rotation_euler.y,
                   'headPitch':head.rotation_euler.y,'wingSpread':unfold,'flapGate':flap_gate,
                   'contacts':[list(p) for p in planted],'brace':frame<=PUSH_END,
                   'legs':leg_states,
                   'hipAttachments':[list(leg.matrix_world.inverted()@(torso.matrix_world@hip_in_torso[index])) for index,leg in enumerate(legs)]})

def screen(point):
    v=world_to_camera_view(scene,camera,point);return {'x':round(v.x,7),'y':round(1-v.y,7)}

for frame in range(COUNT):
    scene.frame_set(frame+1);prototype_pose(frame)
    shape=body.shape_key_add(name='Takeoff body and neck %02d'%frame)
    for vertex,co in zip(shape.data,takeoff_body_shape()):vertex.co=co
    for at,value in [(frame,0),(frame+1,1),(frame+2,0)]:shape.value=value;shape.keyframe_insert(data_path='value',frame=at)
    # Brace paths use one keyed target per frame so the Blender file contains
    # the same connected deformation that is rendered into each sprite.
    for owner,part,key in leg_paths:
        baked=part.shape_key_add(name='Brace pose %02d'%frame)
        for vertex,co in zip(baked.data,key.data):vertex.co=co.co
        for at,value in [(frame,0),(frame+1,key.value),(frame+2,0)]:baked.value=value;baked.keyframe_insert(data_path='value',frame=at)
        key.value=0
    for mesh_object,key in wing_strokes:
        baked=mesh_object.shape_key_add(name='Shoulder collar and elbow pose %02d'%frame)
        for vertex,co in zip(baked.data,key.data):vertex.co=co.co
        for at,value in [(frame,0),(frame+1,1),(frame+2,0)]:baked.value=value;baked.keyframe_insert(data_path='value',frame=at)
        key.value=0
    for obj in animated:
        for prop in ['location','rotation_euler','scale']:obj.keyframe_insert(data_path=prop,frame=frame+1)
    for key in all_keys:key.keyframe_insert(data_path='value',frame=frame+1)
    closed_tip=from_reference(464,184)
    tip=Vector((closed_tip[0]-bill_origin[0],0,closed_tip[1]-bill_origin[1]))
    poses.append({'head':screen(head.matrix_world@Vector((.11,0,.22))),
                  'beak':screen(upper.matrix_world@tip),'foot':screen(sum((Vector(c) for c in checks[-1]['contacts']),Vector())/2),
                  'root':screen(root.matrix_world.translation),'rootZ':checks[-1]['rootZ'],
                  'orthoScale':6.9,'stage':'brace' if frame<8 else 'push-and-spread' if frame<=10 else 'release' if frame<13 else 'powered-flap' if frame<37 else 'glide'})

scene.frame_start=1;scene.frame_end=COUNT;scene.render.fps=FPS
for frame,label in [(0,'Perched'),(6,'Deep brace'),(7,'Load held'),(9,'Push and spread'),(10,'Full extension'),(11,'Release and downstroke'),(14,'First stroke complete'),(39,'Nose-up glide')]:scene.timeline_markers.new(label,frame=frame+1)
scene['README']='Separate 8 fps grounded takeoff study: .36 m deep forward-leaning brace, .125 s weight hold, .375 s connected knee extension and simultaneous wing spread, toe release at 1.375 s during the first powered downstroke, then three flap cycles into a nose-up glide. The slimmer neutral torso retains its actual hanging breast underside and width throughout flight; there is no flight compression, only a gentle canonical dorsal alignment. The anatomical wing plane follows the torso and its spinal axis. A fixed inboard collar remains embedded front-to-rear while powered stroke amplitude grows toward the angular elbow and primaries. Broader leading arches create the distinct reference elbow without obscuring head/neck. All body, collar and elbow geometry is baked into editable per-frame shape keys. Ground motion, launch timing and fixed camera remain unchanged.'
scene['Base source SHA256']=prototype_base_sha256
scene.frame_set(1)
bpy.ops.wm.save_as_mainfile(filepath=str((study_directory if SCOUT else P)/'raven-takeoff-prototype-v23.blend'))
manifest={'frameWidth':512,'frameHeight':512,'columns':8,'fps':FPS,'frames':COUNT,'loop':False,'clip':'takeoff-push','baseSourceSha256':prototype_base_sha256,
          'poses':poses,'inspection':[{'frame':f,'label':label} for f,label in [(0,'Perched'),(6,'Deep brace'),(10,'Extended'),(11,'Release'),(14,'Downstroke'),(18,'Raised elbow'),(24,'Flight'),(39,'Glide')]],
          'description':'Retained neutral hanging breast and width, zero flight compression, and gentle dorsal alignment. The anatomical wing plane follows the torso; a fixed embedded root collar grades into the powered elbow/primaries. A stronger angular leading-edge arch keeps the head/neck exposed. Established brace, push, flap and flight timings, camera and scale are preserved.',
          'anatomy':{'flightCompression':0,'wingPlaneAngle':SPINE_OPEN_ANGLE,'collarStrokeWeight':0,'strokeRampSpan':[.18,.80],'bodyCorrection':'Dorsal contour only; neutral underside and width retained'},
          'ground':{'y':poses[0]['foot']['y'],'launchFrame':RELEASE,'flapStartFrame':FLAP_START,'spreadStartFrame':PUSH_START+1,'firstPoweredStroke':RELEASE},'checks':checks}
((study_directory if SCOUT else P)/'takeoff-prototype.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
for item in checks[:PUSH_END+1]:
    for initial,actual in zip(foot_contacts,item['contacts']):assert (initial-Vector(actual)).length<1e-6,(item['frame'],initial,actual)
assert checks[6]['rootZ']<checks[0]['rootZ']-.35
assert checks[PUSH_END]['rootZ']>checks[0]['rootZ']+.020
assert checks[6]['torsoPitch']>.27 and checks[6]['headPitch']>.19
assert 0<checks[8]['wingSpread']<checks[9]['wingSpread']<checks[10]['wingSpread']==1
print('TAKEOFF_KINEMATICS_PASS: fixed toes through frame 10, .36 m deep brace and forward lean, .382 m leg extension while wings spread, release frame 11 during downstroke.',flush=True)
scouts=[10,11,14,18,24,39]
order=[39] if '--glide-only' in sys.argv else scouts if SCOUT or '--scout-only' in sys.argv else [f for f in range(COUNT) if f not in scouts] if '--render-rest' in sys.argv else scouts+[f for f in range(COUNT) if f not in scouts]
for frame in order:
    scene.frame_set(frame+1)
    scene.render.filepath=str(destination/('takeoff-push-%02d.png'%frame))
    bpy.ops.render.render(write_still=True)
    print('TAKEOFF_RENDER',frame,flush=True)
print('TAKEOFF_RENDER_COMPLETE',flush=True)
