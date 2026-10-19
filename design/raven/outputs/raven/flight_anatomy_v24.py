"""Shared v23 anatomy for chat push-off, gliding, patrol, roll and landing.
Executed in build_chat_flight.py's Blender globals. Prototype files stay intact.
"""
takeoff_runtime_source=(P/'build_takeoff_prototype.py').read_text(encoding='utf-8').split('for frame in range(COUNT):')[0]
exec(compile(takeoff_runtime_source,str(P/'build_takeoff_prototype.py'),'exec'),globals())

def shared_flight_body(amount):
    global flight_compression,streamline
    flight_compression=0;streamline=amount
    return takeoff_body_shape()

def shared_flight_wings(unfold,distal_rotations):
    """Pinned inboard collar, motion ramp toward the elbow and primaries."""
    for wing,(mesh_object,key),rotation,side in zip(wings,wing_strokes,distal_rotations,[-1,1]):
        wing.location.y=side*(.31-.07*unfold)
        wing.rotation_euler=(0,SPINE_OPEN_ANGLE*unfold,0)
        shapes=mesh_object.data.shape_keys.key_blocks
        basis=shapes['Basis'];spread=shapes['Flight spread'];flex=shapes['Feather flex'];tuck=shapes['Roll elbow tuck']
        for index,vertex in enumerate(key.data):
            b=basis.data[index].co
            current=b+(spread.data[index].co-b)*unfold+(flex.data[index].co-b)*flex.value+(tuck.data[index].co-b)*tuck.value
            span=abs(spread.data[index].co.y);motion=smooth((span-.18)/.62)
            weighted=Matrix.Identity(3).to_quaternion().slerp(rotation.to_quaternion(),motion).to_matrix()
            moved=weighted@current;vertex.co=b+(moved-current)
        key.value=1

def shared_takeoff_pose(frame):
    """Approved connected leg push, sharing the collar used while soaring."""
    prototype_pose(frame)
    unfold=smooth((frame-PUSH_START)/(PUSH_END-PUSH_START));gate=unfold*(1-smooth((frame-32)/5))
    phase=max(0,(frame-FLAP_START)/8)*math.tau
    distal=[Matrix.Rotation(side*(.24*unfold+.87*gate*math.cos(phase)),3,'Z') for side in [-1,1]]
    shared_flight_wings(unfold,distal)
    return shared_flight_body(smooth((frame-RELEASE)/12))

def shared_flight_legs(phase,air=1):
    """The same connected thigh/ankle anatomy as the completed push-off."""
    bpy.context.view_layer.update()
    for key in leg_tucks+leg_swings:key.value=0
    for index,(leg,foot) in enumerate(zip(legs,feet)):
        side=[-1,1][index];adjustment=math.sin(math.tau*phase*2+side*.7)
        inverse=leg.matrix_world.inverted()
        upper_flight=inverse@(root.matrix_world@Vector((-.40+side*.04,side*.24*(1-.27),-.05+.075)))
        knee_flight=inverse@(root.matrix_world@Vector((-.16+side*.04+.018*adjustment,side*.24,-.45+.0105*adjustment)))
        attached=inverse@(torso.matrix_world@hip_in_torso[index])
        upper=attached.lerp(upper_flight,air);knee=rest_knee.lerp(knee_flight,air);ankle=foot.location.copy()
        for owner,part,key in leg_paths:
            if owner==leg:
                leg_shape(part,key,knee,ankle,upper,1-.20*air);key.value=1 if air>0 else 0
